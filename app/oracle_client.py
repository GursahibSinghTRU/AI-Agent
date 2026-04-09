"""
oracle_client.py — Analytics CRUD layer over Oracle 23ai.

Drop-in replacement for supabase_client.py.
Privacy-first: only metadata/telemetry is stored, never raw messages.

Requires python-oracledb (thin mode — no Oracle Instant Client needed).
Connection is configured via environment variables:
    ORACLE_HOST, ORACLE_PORT, ORACLE_SERVICE, ORACLE_USER, ORACLE_PASSWORD
"""

import array
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import oracledb

from app.config import settings

log = logging.getLogger("oracle_client")

# ── Connection pool (lazy singleton) ─────────────────────────────────────────

_pool: Optional[oracledb.ConnectionPool] = None


def _get_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        dsn = f"{settings.ORACLE_HOST}:{settings.ORACLE_PORT}/{settings.ORACLE_SERVICE}"
        _pool = oracledb.create_pool(
            user=settings.ORACLE_USER,
            password=settings.ORACLE_PASSWORD,
            dsn=dsn,
            min=1,
            max=5,
            increment=1,
        )
        log.info("Oracle connection pool created → %s", dsn)
    return _pool


def _conn():
    """Acquire a connection from the pool (use as context manager)."""
    return _get_pool().acquire()


def _iso(dt) -> Optional[str]:
    """Convert an Oracle datetime to an ISO-8601 string safe for JSON."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(session_id: str) -> dict:
    """Create a new chat session (upsert — safe to call on reconnect)."""
    now = datetime.now(timezone.utc)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                MERGE INTO chat_sessions tgt
                USING (SELECT :id AS id FROM dual) src
                ON (tgt.id = src.id)
                WHEN NOT MATCHED THEN
                    INSERT (id, started_at, last_activity_at, total_messages)
                    VALUES (:id, :started_at, :last_activity_at, 0)
                WHEN MATCHED THEN
                    UPDATE SET tgt.last_activity_at = :last_activity_at
                """,
                id=session_id,
                started_at=now,
                last_activity_at=now,
            )
            conn.commit()
    log.info("Session upserted: %s", session_id)
    return {"id": session_id, "started_at": _iso(now)}


def update_session_activity(session_id: str, increment_messages: int = 0) -> None:
    """Touch last_activity_at and atomically increment total_messages."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET    last_activity_at = SYSTIMESTAMP,
                       total_messages   = total_messages + :inc
                WHERE  id = :id
                """,
                inc=increment_messages,
                id=session_id,
            )
            conn.commit()
    log.debug("Session %s activity updated (+%d messages)", session_id, increment_messages)


# ── Interactions ──────────────────────────────────────────────────────────────

def log_interaction(
    session_id: str,
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> str:
    """Insert an interaction row and return its UUID."""
    interaction_id = str(uuid.uuid4())
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_interactions
                    (id, session_id, created_at, latency_ms,
                     prompt_tokens, completion_tokens, user_feedback)
                VALUES
                    (:id, :session_id, SYSTIMESTAMP, :latency_ms,
                     :prompt_tokens, :completion_tokens, 0)
                """,
                id=interaction_id,
                session_id=session_id,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            conn.commit()
    log.info(
        "Interaction logged: %s (session=%s, latency=%dms)",
        interaction_id, session_id, latency_ms,
    )
    return interaction_id


def update_feedback(interaction_id: str, feedback: int) -> None:
    """Set user_feedback on a specific interaction (1=up, -1=down, 0=none)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_interactions
                SET    user_feedback = :feedback
                WHERE  id = :id
                """,
                feedback=feedback,
                id=interaction_id,
            )
            conn.commit()
    log.info("Feedback updated: interaction=%s → %d", interaction_id, feedback)


# ── Analytics reads ───────────────────────────────────────────────────────────

def get_all_sessions() -> List[Dict[str, Any]]:
    """Return all sessions ordered newest-first (for analytics dashboard)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, started_at, last_activity_at, total_messages
                FROM   chat_sessions
                ORDER  BY started_at DESC
                """
            )
            cols = [c[0].lower() for c in cur.description]
            rows = []
            for row in cur:
                d = dict(zip(cols, row))
                d["started_at"] = _iso(d["started_at"])
                d["last_activity_at"] = _iso(d["last_activity_at"])
                rows.append(d)
    return rows


# ── Vector store ──────────────────────────────────────────────────────────────

def store_chunk(
    chunk_id: str,
    filename: str,
    page_num: Optional[int],
    title: str,
    chunk_text: str,
    embedding: List[float],
    source_url: Optional[str] = None,
) -> None:
    """Upsert a single document chunk with its vector embedding."""
    vec = array.array("f", embedding)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                MERGE INTO doc_chunks tgt
                USING (SELECT :id AS id FROM dual) src
                ON (tgt.id = src.id)
                WHEN NOT MATCHED THEN
                    INSERT (id, filename, page_num, title, chunk_text, embedding, source_url)
                    VALUES (:id, :filename, :page_num, :title, :chunk_text, :embedding, :source_url)
                """,
                id=chunk_id,
                filename=filename,
                page_num=page_num,
                title=title,
                chunk_text=chunk_text,
                embedding=vec,
                source_url=source_url,
            )
            conn.commit()


def get_stored_chunk_ids() -> Set[str]:
    """Return the set of all chunk IDs currently stored (for dedup during ingest)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM doc_chunks")
            return {row[0] for row in cur}


def similarity_search(
    query_embedding: List[float],
    k: int = 6,
) -> List[Tuple[Dict[str, Any], float]]:
    """
    Return the top-k chunks ordered by cosine distance (ascending).
    Each result is (chunk_dict, distance) where distance is in [0, 2]:
      0 = identical, 1 = perpendicular, 2 = opposite.
    """
    vec = array.array("f", query_embedding)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, page_num, title, chunk_text, source_url,
                       VECTOR_DISTANCE(embedding, :vec, COSINE) AS dist
                FROM   doc_chunks
                ORDER  BY dist
                FETCH  FIRST :k ROWS ONLY
                """,
                vec=vec,
                k=k,
            )
            cols = ["id", "filename", "page_num", "title", "chunk_text", "source_url", "distance"]
            results = []
            for row in cur:
                d = dict(zip(cols, row))
                if d["chunk_text"] is not None:
                    d["chunk_text"] = d["chunk_text"].read() if hasattr(d["chunk_text"], "read") else str(d["chunk_text"])
                results.append((d, float(d.pop("distance"))))
    return results


def get_chunk_count() -> int:
    """Return total number of stored chunks (for stats endpoint)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM doc_chunks")
            row = cur.fetchone()
            return int(row[0]) if row else 0


# ── Analytics reads ───────────────────────────────────────────────────────────

def get_all_interactions() -> List[Dict[str, Any]]:
    """Return all interactions ordered newest-first (for analytics dashboard)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, session_id, created_at, latency_ms,
                       prompt_tokens, completion_tokens, user_feedback
                FROM   chat_interactions
                ORDER  BY created_at DESC
                """
            )
            cols = [c[0].lower() for c in cur.description]
            rows = []
            for row in cur:
                d = dict(zip(cols, row))
                d["created_at"] = _iso(d["created_at"])
                rows.append(d)
    return rows
