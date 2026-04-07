"""
migrate_supabase_to_oracle.py — One-time data migration from Supabase to Oracle 23ai.

Run once after the Oracle schema has been created in SQL Developer:
    python scripts/migrate_supabase_to_oracle.py

Reads from the Supabase credentials hardcoded in app/config.py and writes to
Oracle using the ORACLE_* environment variables (or defaults in config.py).

Safe to re-run: rows that already exist in Oracle are skipped (not duplicated).
"""

import sys
import os

# Allow imports from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import requests
import oracledb
from dotenv import load_dotenv

# Must load .env BEFORE importing settings so all values are available
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("migrate")

# ── Supabase source (credentials that were hardcoded in config.py) ───────────
# These are the confirmed-working credentials from the original config.py.

SUPA_URL = "https://lrzztpkleysibozjculg.supabase.co"
SUPA_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxyenp0cGtsZXlzaWJvempjdWxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0NTExMzQsImV4cCI6MjA5MDAyNzEzNH0.IMgJ-a4pwPAtfFecsIRlcHlmuj5KwhzywiqsX_FpCbI"

SUPA_HEADERS = {
    "apikey": SUPA_KEY,
    "Authorization": f"Bearer {SUPA_KEY}",
    "Accept": "application/json",
}


def supa_fetch(table: str) -> list:
    url = f"{SUPA_URL}/rest/v1/{table}?select=*&order=created_at.asc"
    # sessions use started_at not created_at
    if table == "chat_sessions":
        url = f"{SUPA_URL}/rest/v1/{table}?select=*&order=started_at.asc"
    resp = requests.get(url, headers=SUPA_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Oracle target ─────────────────────────────────────────────────────────────

def get_oracle_conn():
    dsn = f"{settings.ORACLE_HOST}:{settings.ORACLE_PORT}/{settings.ORACLE_SERVICE}"
    return oracledb.connect(
        user=settings.ORACLE_USER,
        password=settings.ORACLE_PASSWORD,
        dsn=dsn,
    )


# ── Migration ─────────────────────────────────────────────────────────────────

def migrate_sessions(conn, sessions: list) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for s in sessions:
            try:
                cur.execute(
                    """
                    INSERT INTO chat_sessions
                        (id, started_at, last_activity_at, total_messages)
                    VALUES
                        (:id, TO_TIMESTAMP_TZ(:started_at,    'YYYY-MM-DD"T"HH24:MI:SS.FF6TZH:TZM'),
                              TO_TIMESTAMP_TZ(:last_activity_at, 'YYYY-MM-DD"T"HH24:MI:SS.FF6TZH:TZM'),
                              :total_messages)
                    """,
                    id=s["id"],
                    started_at=s.get("started_at", ""),
                    last_activity_at=s.get("last_activity_at", s.get("started_at", "")),
                    total_messages=s.get("total_messages", 0) or 0,
                )
                inserted += 1
            except oracledb.IntegrityError:
                pass  # already exists — skip
        conn.commit()
    return inserted


def migrate_interactions(conn, interactions: list) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for i in interactions:
            try:
                cur.execute(
                    """
                    INSERT INTO chat_interactions
                        (id, session_id, created_at, latency_ms,
                         prompt_tokens, completion_tokens, user_feedback)
                    VALUES
                        (:id, :session_id,
                         TO_TIMESTAMP_TZ(:created_at, 'YYYY-MM-DD"T"HH24:MI:SS.FF6TZH:TZM'),
                         :latency_ms, :prompt_tokens, :completion_tokens, :user_feedback)
                    """,
                    id=i["id"],
                    session_id=i.get("session_id"),
                    created_at=i.get("created_at", ""),
                    latency_ms=i.get("latency_ms", 0) or 0,
                    prompt_tokens=i.get("prompt_tokens", 0) or 0,
                    completion_tokens=i.get("completion_tokens", 0) or 0,
                    user_feedback=i.get("user_feedback", 0) or 0,
                )
                inserted += 1
            except oracledb.IntegrityError:
                pass  # already exists — skip
        conn.commit()
    return inserted


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not SUPA_URL or not SUPA_KEY:
        log.error("Supabase credentials not found. Check app/config.py.")
        sys.exit(1)
    if not settings.ORACLE_USER or not settings.ORACLE_PASSWORD:
        log.error("Oracle credentials not set. Add ORACLE_USER / ORACLE_PASSWORD to your .env.")
        sys.exit(1)

    log.info("Fetching data from Supabase (%s)…", SUPA_URL)
    sessions = supa_fetch("chat_sessions")
    interactions = supa_fetch("chat_interactions")
    log.info("  %d sessions, %d interactions fetched.", len(sessions), len(interactions))

    log.info("Connecting to Oracle (%s:%s/%s)…",
             settings.ORACLE_HOST, settings.ORACLE_PORT, settings.ORACLE_SERVICE)
    conn = get_oracle_conn()

    log.info("Migrating sessions…")
    n_sessions = migrate_sessions(conn, sessions)
    log.info("  %d / %d sessions inserted (rest already existed).", n_sessions, len(sessions))

    log.info("Migrating interactions…")
    n_interactions = migrate_interactions(conn, interactions)
    log.info("  %d / %d interactions inserted (rest already existed).", n_interactions, len(interactions))

    conn.close()
    log.info("Migration complete.")


if __name__ == "__main__":
    main()
