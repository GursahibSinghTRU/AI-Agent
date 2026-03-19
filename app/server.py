"""
server.py — FastAPI backend with SSE streaming, health checks, and static UI.

Started via run.py at the project root.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import PolicyAgent
from app.config import settings

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
_agent: Optional[PolicyAgent] = None


def get_agent() -> PolicyAgent:
    global _agent
    if _agent is None:
        _agent = PolicyAgent()
    return _agent


# ── Request Models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    chat_history: Optional[List[Dict[str, str]]] = None


# ── Routes ───────────────────────────────────────────────────────────────────

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


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Blocking endpoint — returns the full answer at once."""
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")
    agent = get_agent()
    return agent.answer(req.question, chat_history=req.chat_history)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    SSE streaming endpoint — emits tokens as they are generated.

    Event types:
      sources  → {sources: [...]}
      token    → {token: "..."}
      done     → {timing: {...}}
    """
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")

    agent = get_agent()

    def event_generator():
        for event in agent.stream(req.question, chat_history=req.chat_history):
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

    return {
        "documents": pdf_count,
        "chunks": count,
        "chat_model": settings.CHAT_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
    }
