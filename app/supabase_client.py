"""
supabase_client.py — Thin analytics CRUD layer over Supabase.

Privacy-first: only metadata/telemetry is stored, never raw messages.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from app.config import settings

log = logging.getLogger("supabase_client")

# ── Singleton client ─────────────────────────────────────────────────────────

_client: Optional[Client] = None


def get_supabase() -> Client:
    """Return (and lazily create) the Supabase client."""
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        log.info("Supabase client initialised → %s", settings.SUPABASE_URL)
    return _client


# ── Sessions ─────────────────────────────────────────────────────────────────

def create_session(session_id: str) -> dict:
    """Create a new chat session (or return existing)."""
    sb = get_supabase()
    # Upsert: if the session already exists, just update last_activity
    result = (
        sb.table("chat_sessions")
        .upsert(
            {
                "id": session_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "total_messages": 0,
            },
            on_conflict="id",
        )
        .execute()
    )
    log.info("Session upserted: %s", session_id)
    return result.data[0] if result.data else {}


def update_session_activity(session_id: str, increment_messages: int = 0) -> None:
    """Touch last_activity_at and optionally bump total_messages."""
    sb = get_supabase()
    # First fetch current total_messages
    current = (
        sb.table("chat_sessions")
        .select("total_messages")
        .eq("id", session_id)
        .single()
        .execute()
    )
    new_total = (current.data.get("total_messages", 0) or 0) + increment_messages
    (
        sb.table("chat_sessions")
        .update(
            {
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "total_messages": new_total,
            }
        )
        .eq("id", session_id)
        .execute()
    )
    log.debug("Session %s updated: total_messages=%d", session_id, new_total)


# ── Interactions ─────────────────────────────────────────────────────────────

def log_interaction(
    session_id: str,
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> str:
    """Insert an interaction row; returns its UUID."""
    sb = get_supabase()
    result = (
        sb.table("chat_interactions")
        .insert(
            {
                "session_id": session_id,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "user_feedback": 0,
            }
        )
        .execute()
    )
    interaction_id = result.data[0]["id"] if result.data else ""
    log.info(
        "Interaction logged: %s (session=%s, latency=%dms)",
        interaction_id, session_id, latency_ms,
    )
    return interaction_id


def update_feedback(interaction_id: str, feedback: int) -> None:
    """Set user_feedback on a specific interaction (1 = up, -1 = down, 0 = none)."""
    sb = get_supabase()
    (
        sb.table("chat_interactions")
        .update({"user_feedback": feedback})
        .eq("id", interaction_id)
        .execute()
    )
    log.info("Feedback updated: interaction=%s → %d", interaction_id, feedback)
