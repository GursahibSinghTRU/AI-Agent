"""
agent.py — The Policy Agent: retrieval + LLM answering + streaming.

Improvements:
  • Streaming token generation via Ollama
  • Conversation-aware prompts
  • Query expansion for vague inputs
  • Structured timing and source metadata
"""

import json
import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx
from langchain_ollama import ChatOllama

from app.config import settings
from app.rag_core import (
    build_qa_prompt,
    format_context,
    load_vector_db,
    retrieve_with_threshold,
)

log = logging.getLogger("agent")


# ── Heuristics ───────────────────────────────────────────────────────────────

_QUESTION_STARTERS = frozenset(
    "what how when where who which why is are does do can could should would"
    " tell explain describe list summarize".split()
)


def is_vague_query(text: str) -> bool:
    """Treat very short keyword-style inputs as vague."""
    t = (text or "").strip()
    if not t:
        return True
    if "?" in t:
        return False
    words = t.split()
    if len(words) <= 2:
        first = words[0].lower().rstrip("?.,")
        return first not in _QUESTION_STARTERS
    if words[0].lower() in _QUESTION_STARTERS:
        return False
    return len(words) <= 3 and "?" not in t


def _expand_query(question: str) -> str:
    """
    Lightly expand a query so the embedding search matches better.
    Adds 'TRU policy' context when absent.
    """
    q = question.strip()
    low = q.lower()
    if "tru" not in low and "policy" not in low and "thompson rivers" not in low:
        q = f"TRU policy: {q}"
    return q


def _stream_from_ollama(prompt: str, model: str) -> Generator[str, None, None]:
    """
    Stream tokens directly from Ollama API /chat endpoint with think=false for qwen3.5.
    The /chat endpoint properly supports the think parameter.
    """
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                    "temperature": settings.TEMPERATURE,
                    "think": False,  # Disable thinking for qwen3.5 - /api/chat supports this!
                },
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    # /api/chat returns message.content, not response field
                    if "message" in chunk and chunk["message"].get("content"):
                        yield chunk["message"]["content"]
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.error("Ollama streaming error: %s", e)
        yield f"Error generating response: {str(e)}"



# ── Agent ────────────────────────────────────────────────────────────────────

class PolicyAgent:
    """
    RAG agent that retrieves from TRU policy documents and generates
    answers via a local Ollama model.  Supports both blocking and
    streaming response modes.
    """

    def __init__(self):
        log.info("Loading vector DB from %s …", settings.persist_path)
        self.vectordb = load_vector_db()
        self._llm = None
        log.info("PolicyAgent ready.")

    @property
    def llm(self) -> ChatOllama:
        if self._llm is None:
            self._llm = ChatOllama(
                model=settings.CHAT_MODEL,
                base_url=settings.OLLAMA_BASE_URL,
                temperature=settings.TEMPERATURE,
                num_predict=settings.NUM_PREDICT,
                keep_alive=settings.KEEP_ALIVE,
            )
        return self._llm

    # ── Core retrieval (shared by both modes) ────────────────────

    def _retrieve(self, question: str):
        expanded = _expand_query(question)
        t0 = time.perf_counter()
        retrieved = retrieve_with_threshold(
            self.vectordb, expanded,
            k=settings.K,
            score_threshold=settings.SCORE_THRESHOLD,
        )
        retrieve_ms = (time.perf_counter() - t0) * 1000

        if not retrieved:
            return None, [], [], retrieve_ms

        context, sources = format_context(retrieved, max_chars=settings.MAX_CONTEXT_CHARS)
        return context, sources, retrieved, retrieve_ms

    # ── Blocking answer ──────────────────────────────────────────

    def answer(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Return a complete answer dict (non-streaming)."""
        t_start = time.perf_counter()

        context, sources, _raw, retrieve_ms = self._retrieve(question)

        if context is None:
            return self._no_result(retrieve_ms, t_start)

        if not context.strip():
            return self._no_result(retrieve_ms, t_start)

        if is_vague_query(question):
            return self._vague_result(sources, retrieve_ms, t_start)

        prompt = build_qa_prompt(question, context, chat_history)
        t_llm = time.perf_counter()
        raw_answer = (self.llm.invoke(prompt).content or "").strip()
        llm_ms = (time.perf_counter() - t_llm) * 1000

        answer_text = self._sanitize(raw_answer)
        if answer_text == "Not found in the provided documents.":
            sources = []

        return {
            "answer": answer_text,
            "sources": sources[:6],
            "timing": self._timing(retrieve_ms, llm_ms, t_start),
        }

    # ── Streaming answer (SSE-friendly generator) ────────────────

    def stream(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Yield incremental dicts suitable for Server-Sent Events:
          {"type": "sources", "sources": [...]}
          {"type": "token",   "token": "..."}
          {"type": "done",    "timing": {...}}
        """
        t_start = time.perf_counter()

        context, sources, _raw, retrieve_ms = self._retrieve(question)

        if context is None or not context.strip():
            yield {"type": "token", "token": "Not found in the provided documents."}
            yield {"type": "done", "timing": self._timing(retrieve_ms, 0, t_start)}
            return

        if is_vague_query(question):
            vague_msg = (
                "I found relevant policies for that topic, but your input is too broad.\n\n"
                "Try asking a specific question, for example:\n"
                "• What are the approval requirements?\n"
                "• What are the limits or thresholds?\n"
                "• What is the required process?\n"
                "• Are there exceptions?"
            )
            yield {"type": "sources", "sources": sources[:6]}
            yield {"type": "token", "token": vague_msg}
            yield {"type": "done", "timing": self._timing(retrieve_ms, 0, t_start)}
            return

        # Emit sources first so the UI can display them while tokens stream
        yield {"type": "sources", "sources": sources[:6]}

        prompt = build_qa_prompt(question, context, chat_history)
        t_llm = time.perf_counter()
        collected = []

        # Use direct Ollama streaming with think=false instead of LangChain
        for token in _stream_from_ollama(prompt, settings.CHAT_MODEL):
            if token:
                collected.append(token)
                yield {"type": "token", "token": token}

        llm_ms = (time.perf_counter() - t_llm) * 1000

        full_text = "".join(collected).strip()
        if "Not found in the provided documents." in full_text:
            yield {"type": "clear_sources"}

        yield {"type": "done", "timing": self._timing(retrieve_ms, llm_ms, t_start)}

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _sanitize(answer: str) -> str:
        if "Not found in the provided documents." in answer:
            return "Not found in the provided documents."
        return answer

    @staticmethod
    def _timing(retrieve_ms: float, llm_ms: float, t_start: float) -> Dict:
        total_ms = (time.perf_counter() - t_start) * 1000
        return {
            "retrieve_ms": round(retrieve_ms),
            "llm_ms": round(llm_ms),
            "total_ms": round(total_ms),
            "total_s": round(total_ms / 1000, 2),
        }

    @staticmethod
    def _no_result(retrieve_ms: float, t_start: float) -> Dict[str, Any]:
        return {
            "answer": "Not found in the provided documents.",
            "sources": [],
            "timing": PolicyAgent._timing(retrieve_ms, 0, t_start),
        }

    @staticmethod
    def _vague_result(sources, retrieve_ms, t_start) -> Dict[str, Any]:
        return {
            "answer": (
                "I found relevant policies for that topic, but your input is too broad.\n\n"
                "Try asking a specific question, for example:\n"
                "• What are the approval requirements?\n"
                "• What are the limits or thresholds?\n"
                "• What is the required process?\n"
                "• Are there exceptions?"
            ),
            "sources": sources[:6],
            "timing": PolicyAgent._timing(retrieve_ms, 0, t_start),
        }
