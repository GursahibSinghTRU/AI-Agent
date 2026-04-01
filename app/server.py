"""
server.py — FastAPI backend with SSE streaming, health checks, analytics endpoints, and static UI.

Started via run.py at the project root.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import RiskandSafetyAgent
from app.config import settings
from app.weather import resolve_weather_link

log = logging.getLogger("server")

# ── Paths ────────────────────────────────────────────────────────────────────
FRONTEND_DIR = settings.frontend_path

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="TRU Risk & Safety Assistant",
    version="2.0.0",
    docs_url="/docs",
)

origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend assets at /static so HTML can reference /static/styles.css etc.
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ── Agent (lazy singleton) ───────────────────────────────────────────────────
_agent: Optional[RiskandSafetyAgent] = None


def get_agent() -> RiskandSafetyAgent:
    global _agent
    if _agent is None:
        _agent = RiskandSafetyAgent()
    return _agent


# ── Request Models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    chat_history: Optional[List[Dict[str, str]]] = None
    session_id: Optional[str] = None


class SessionRequest(BaseModel):
    session_id: str


class FeedbackRequest(BaseModel):
    interaction_id: str
    feedback: int  # 1 = thumbs up, -1 = thumbs down


# ── Page Routes ──────────────────────────────────────────────────────────────

@app.get("/")
def home():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(404, "UI not found — ensure frontend/index.html exists.")
    return FileResponse(str(index))


@app.get("/general")
def general_tru():
    """Serve the general TRU landing page."""
    page = FRONTEND_DIR / "general-tru.html"
    if not page.exists():
        raise HTTPException(404, "General TRU page not found.")
    return FileResponse(str(page))


@app.get("/analytics")
def analytics_page():
    """Serve the analytics dashboard."""
    page = FRONTEND_DIR / "analytics.html"
    if not page.exists():
        raise HTTPException(404, "Analytics dashboard not found.")
    return FileResponse(str(page))


# ── Health & Stats ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Deep health check — pings Ollama to confirm models are available."""
    ollama_ok = False
    models_loaded: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                ollama_ok = True
                data = r.json()
                models_loaded = [m["name"] for m in data.get("models", [])]
    except Exception:
        pass

    chat_ready = any(settings.CHAT_MODEL in m for m in models_loaded)
    embed_ready = any(settings.EMBEDDING_MODEL in m for m in models_loaded)

    return {
        "ok": ollama_ok and chat_ready and embed_ready,
        "ollama": ollama_ok,
        "chat_model": {"name": settings.CHAT_MODEL, "loaded": chat_ready},
        "embed_model": {"name": settings.EMBEDDING_MODEL, "loaded": embed_ready},
    }


@app.get("/api/stats")
def stats():
    """Return basic stats about the loaded knowledge base."""
    count = 1  # We now use exactly 1 combined context file
    pdf_count = len(list(settings.data_path.glob("*.pdf"))) if settings.data_path.is_dir() else 0
    txt_count = len(list(settings.data_path.glob("*.txt"))) if settings.data_path.is_dir() else 0

    return {
        "chunks_indexed": count,
        "pdf_files_found": pdf_count,
        "txt_files_found": txt_count,
        "collection": "combined_context",
    }


# ── Chat Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/chat")
def chat(req: ChatRequest):
    """Blocking endpoint — returns the full answer at once."""
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")
    agent = get_agent()
    weather_url = resolve_weather_link(req.question, chat_history=req.chat_history)
    return agent.answer(req.question, chat_history=req.chat_history, weather_url=weather_url)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    SSE streaming endpoint — emits tokens as they are generated.

    Event types:
      sources  → {sources: [...]}
      token    → {token: "..."}
      done     → {timing: {...}, interaction_id: "...", prompt_tokens: N, completion_tokens: N}
    """
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")

    agent = get_agent()
    session_id = req.session_id
    weather_url = resolve_weather_link(req.question, chat_history=req.chat_history)

    def event_generator():
        interaction_id = None
        for event in agent.stream(req.question, chat_history=req.chat_history, weather_url=weather_url):
            if event["type"] == "done" and session_id:
                # Log interaction to Supabase
                try:
                    from app.supabase_client import log_interaction, update_session_activity
                    latency_ms = event["timing"].get("total_ms", 0)
                    prompt_tokens = event.get("prompt_tokens", 0)
                    completion_tokens = event.get("completion_tokens", 0)
                    interaction_id = log_interaction(
                        session_id=session_id,
                        latency_ms=latency_ms,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                    # Increment by 2: user message + assistant response
                    update_session_activity(session_id, increment_messages=2)
                    event["interaction_id"] = interaction_id
                except Exception as e:
                    log.warning("Failed to log interaction to Supabase: %s", e)
                    event["interaction_id"] = None

            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Session & Feedback Endpoints (Analytics) ─────────────────────────────────

@app.post("/api/session")
def create_session(req: SessionRequest):
    """Create or touch a chat session."""
    try:
        from app.supabase_client import create_session as sb_create_session
        result = sb_create_session(req.session_id)
        return {"ok": True, "session": result}
    except Exception as e:
        log.warning("Failed to create session in Supabase: %s", e)
        return {"ok": False, "error": str(e)}


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """Record thumbs-up/down feedback for a specific interaction."""
    if req.feedback not in (1, -1, 0):
        raise HTTPException(400, "feedback must be 1, -1, or 0")
    try:
        from app.supabase_client import update_feedback
        update_feedback(req.interaction_id, req.feedback)
        return {"ok": True}
    except Exception as e:
        log.warning("Failed to submit feedback to Supabase: %s", e)
        return {"ok": False, "error": str(e)}
