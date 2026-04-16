"""
agent.py — The Risk & Safety Agent: pre-retrieval RAG + LLM streaming.

Context is retrieved from the Oracle vector store BEFORE the LLM call and
injected directly into the user message. This is more reliable than tool
calling with local models, which can silently produce empty responses.
"""

import json
import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

from app.config import settings
from app.rag_core import (
    retrieve_with_threshold,
    format_context,
    SYSTEM_PROMPT,
)

log = logging.getLogger("agent")

# Words that — when they make up the entire message — indicate a conversational
# acknowledgment with no safety topic. Retrieval is skipped for these.
_CONVERSATIONAL_WORDS = {
    "hello", "hi", "hey", "thanks", "thank", "you", "ok", "okay",
    "yes", "no", "sure", "great", "cool", "bye", "goodbye", "perfect",
    "got", "it", "sounds", "good", "makes", "sense", "alright", "nice",
    "awesome", "wonderful", "excellent", "noted", "understood", "appreciate",
    "cheers", "lol", "haha", "wow", "interesting", "i", "see", "that",
}


def _should_skip_retrieval(question: str) -> bool:
    """Return True for greetings and purely conversational acknowledgments."""
    q = question.strip().lower().rstrip("!.,?")
    if len(q) < 6:
        return True
    # Skip if every word in the message is a known conversational word
    words = set(q.split())
    return words.issubset(_CONVERSATIONAL_WORDS)


def _enrich_query(question: str, chat_history: Optional[List[Dict[str, str]]]) -> str:
    """
    For short follow-up messages, build a richer search query by combining
    the current message with recent user turns. This ensures that follow-ups
    like "I'm a beginner going to Sun Peaks" inherit the skiing topic from
    earlier in the conversation instead of retrieving hiking/unrelated docs.
    """
    if not chat_history or len(question.split()) > 15:
        return question

    # Collect up to the last 3 user messages (excluding current)
    prior_user_msgs = []
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content and content != question:
                prior_user_msgs.append(content)
            if len(prior_user_msgs) >= 3:
                break

    if not prior_user_msgs:
        return question

    # Build context string from prior user turns (most recent last)
    prior_user_msgs.reverse()
    context_str = " ".join(msg[:100] for msg in prior_user_msgs)
    return f"{context_str} {question}"


def _build_messages(
    question: str,
    chat_history: Optional[List[Dict[str, str]]],
    context: Optional[str] = None,
    sources: Optional[List[Dict]] = None,
) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if chat_history:
        for msg in chat_history[-10:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    if context and sources:
        source_names = ", ".join(
            s.get("riskandsafetydoc") or s.get("file") or ""
            for s in sources if s
        )
        user_content = (
            f"{question}\n\n"
            f"[RETRIEVED CONTEXT]\n"
            f"Available sources (ONLY these may be cited): {source_names}\n\n"
            f"{context}"
        )
    elif context:
        user_content = f"{question}\n\n[RETRIEVED CONTEXT]\n{context}"
    else:
        user_content = question

    messages.append({"role": "user", "content": user_content})
    return messages


# ── Agent ─────────────────────────────────────────────────────────────────────

class RiskandSafetyAgent:
    """
    RAG agent: retrieves context from Oracle vector DB, injects it into the
    prompt, then streams a response from a local Ollama model.
    No tool calling — context injection is more reliable with local models.
    """

    def __init__(self):
        log.info("Risk & Safety Agent initialising (Oracle vector store, direct injection)...")

    # ── Core retrieval ──────────────────────────────────────────────

    def _retrieve(self, query: str):
        t0 = time.perf_counter()
        retrieved = retrieve_with_threshold(
            query,
            k=settings.K,
            score_threshold=settings.SCORE_THRESHOLD,
        )
        retrieve_ms = (time.perf_counter() - t0) * 1000

        if not retrieved:
            return None, [], [], retrieve_ms

        context, sources = format_context(retrieved, max_chars=settings.MAX_CONTEXT_CHARS)
        return context, sources, retrieved, retrieve_ms

    # ── Blocking answer ─────────────────────────────────────────────

    def answer(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Return a complete answer dict (non-streaming fallback)."""
        answer_text = ""
        sources = []
        timing = {}
        for event in self.stream(question, chat_history):
            if event["type"] == "token":
                answer_text += event["token"]
            elif event["type"] == "sources":
                sources = event["sources"]
            elif event["type"] == "done":
                timing = event["timing"]

        return {"answer": answer_text, "sources": sources, "timing": timing}

    # ── Streaming answer (SSE-friendly generator) ───────────────────

    def stream(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Yield incremental dicts suitable for Server-Sent Events:
          {"type": "sources", "sources": [...]}
          {"type": "token",   "token": "..."}
          {"type": "done",    "timing": {...}, "prompt_tokens": N, "completion_tokens": N}
        """
        t_start = time.perf_counter()
        retrieve_ms = 0.0
        context = None
        sources_to_emit = []

        # ── Step 1: retrieve context (skip for greetings) ─────────
        if not _should_skip_retrieval(question):
            search_query = _enrich_query(question, chat_history)
            if search_query != question:
                log.info("Enriched query: %r → %r", question, search_query)
            context, sources, _, retrieve_ms = self._retrieve(search_query)
            if sources:
                sources_to_emit = sources
                yield {"type": "sources", "sources": sources_to_emit}
            log.info(
                "Retrieved %d sources in %.0fms for query %r",
                len(sources_to_emit), retrieve_ms, search_query,
            )
        else:
            log.info("Skipping retrieval for conversational message: %r", question)

        # ── Step 2: build messages with injected context ──────────
        messages = _build_messages(question, chat_history, context=context, sources=sources_to_emit)

        # ── Step 3: stream the answer ─────────────────────────────
        try:
            with httpx.Client(timeout=120.0) as client:
                log.info("Streaming answer from %s...", settings.CHAT_MODEL)
                response = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.CHAT_MODEL,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": settings.TEMPERATURE,
                            "num_predict": settings.NUM_PREDICT,
                        },
                        "think": False,
                    },
                )
                response.raise_for_status()

                t_llm_start = time.perf_counter()
                collected: List[str] = []
                prompt_tokens = 0
                completion_tokens = 0

                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message") or {}
                    content = msg.get("content") or ""
                    if content:
                        collected.append(content)
                        yield {"type": "token", "token": content}
                    if chunk.get("done"):
                        prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                        completion_tokens = chunk.get("eval_count", 0) or 0

                llm_ms = (time.perf_counter() - t_llm_start) * 1000
                full_text = "".join(collected)
                log.info(
                    "Streaming complete — completion_tokens=%d, llm_ms=%.0f",
                    completion_tokens, llm_ms,
                )

                if not full_text.strip():
                    log.warning("Model produced empty response for query %r", question)

                yield {
                    "type": "done",
                    "timing": self._timing(retrieve_ms, llm_ms, t_start),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                }

        except Exception as e:
            log.error("Agent error: %s", e, exc_info=True)
            yield {"type": "token", "token": f"Error communicating with agent: {str(e)}"}
            yield {
                "type": "done",
                "timing": self._timing(retrieve_ms, 0, t_start),
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }

    @staticmethod
    def _timing(retrieve_ms: float, llm_ms: float, t_start: float) -> Dict:
        total_ms = (time.perf_counter() - t_start) * 1000
        return {
            "retrieve_ms": round(retrieve_ms),
            "llm_ms": round(llm_ms),
            "total_ms": round(total_ms),
            "total_s": round(total_ms / 1000, 2),
        }
