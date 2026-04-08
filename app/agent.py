"""
agent.py — The Risk & Safety Agent: RAG tool calling + LLM streaming.

Uses Ollama's native tool calling to let the LLM decide when to search
the Oracle vector knowledge base. Weather links are pre-resolved by
the server and injected into the user message via [WEATHER_LINK] tags.
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


def _build_messages(
    question: str,
    chat_history: Optional[List[Dict[str, str]]],
    weather_url: Optional[str] = None,
) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if chat_history:
        for msg in chat_history[-10:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    if weather_url:
        user_content = f"{question}\n\n[WEATHER_LINK]: {weather_url}"
    else:
        user_content = question

    messages.append({"role": "user", "content": user_content})
    return messages


# ── Agent ─────────────────────────────────────────────────────────────────────

class RiskandSafetyAgent:
    """
    RAG agent that retrieves from Oracle vector DB and generates
    answers via a local Ollama model. Supports streaming tool calls.
    """

    def __init__(self):
        log.info("Risk & Safety Agent initialising (Oracle vector store)...")
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": (
                        "Search the TRU Risk & Safety vector knowledge base for information "
                        "relevant to a query. Call this for any question about policies, "
                        "procedures, safety guidelines, or factual Risk & Safety topics."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "The specific query to search for "
                                    "(e.g. 'chemical spill procedure', 'PPE requirements')"
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        log.info("Risk & Safety Agent ready.")

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
        weather_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a complete answer dict (non-streaming fallback)."""
        answer_text = ""
        sources = []
        timing = {}
        for event in self.stream(question, chat_history, weather_url=weather_url):
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
        weather_url: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Yield incremental dicts suitable for Server-Sent Events:
          {"type": "sources", "sources": [...]}
          {"type": "token",   "token": "..."}
          {"type": "done",    "timing": {...}, "prompt_tokens": N, "completion_tokens": N}
        """
        t_start = time.perf_counter()
        messages = _build_messages(question, chat_history, weather_url=weather_url)

        try:
            with httpx.Client(timeout=120.0) as client:
                # ── Step 1: ask model whether to call a tool ──────────
                log.info("Sending initial request with tools...")
                response = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.CHAT_MODEL,
                        "messages": messages,
                        "tools": self.tools,
                        "stream": False,
                        "temperature": settings.TEMPERATURE,
                        "think": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                reply = data["message"]
                messages.append(reply)

                retrieve_ms = 0.0
                sources_to_emit = []

                # ── Step 2: execute tool calls if any ─────────────────
                if reply.get("tool_calls"):
                    log.info("Model called %d tool(s).", len(reply["tool_calls"]))

                    for tool_call in reply["tool_calls"]:
                        fn_name = tool_call["function"]["name"]
                        args = tool_call["function"]["arguments"]

                        if fn_name == "search_knowledge_base":
                            search_query = args.get("query", question)
                            log.info("Executing search_knowledge_base: %r", search_query)

                            context, sources, _, r_ms = self._retrieve(search_query)
                            retrieve_ms += r_ms

                            if context:
                                tool_result = f"Documents retrieved:\n{context}"
                                sources_to_emit.extend(sources)
                            else:
                                tool_result = "No documents found matching the query."

                            messages.append({
                                "role": "tool",
                                "content": tool_result,
                                "name": fn_name,
                            })

                    if sources_to_emit:
                        yield {"type": "sources", "sources": sources_to_emit[:6]}

                    # ── Step 3: stream the final answer ───────────────
                    log.info("Streaming follow-up answer...")
                    follow = client.post(
                        f"{settings.OLLAMA_BASE_URL}/api/chat",
                        json={
                            "model": settings.CHAT_MODEL,
                            "messages": messages,
                            "stream": True,
                            "temperature": settings.TEMPERATURE,
                            "think": False,
                        },
                    )
                    follow.raise_for_status()

                    t_llm_start = time.perf_counter()
                    collected: List[str] = []
                    prompt_tokens = 0
                    completion_tokens = 0

                    for line in follow.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if "message" in chunk and chunk["message"].get("content"):
                            token = chunk["message"]["content"]
                            collected.append(token)
                            yield {"type": "token", "token": token}
                        if chunk.get("done"):
                            prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                            completion_tokens = chunk.get("eval_count", 0) or 0

                    llm_ms = (time.perf_counter() - t_llm_start) * 1000
                    full_text = "".join(collected)
                    if "Not found in the provided documents." in full_text:
                        yield {"type": "clear_sources"}

                    yield {
                        "type": "done",
                        "timing": self._timing(retrieve_ms, llm_ms, t_start),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                    }

                else:
                    # ── Direct answer (conversational, no tool needed) ─
                    log.info("Model answered directly (no tool call).")
                    t_llm_start = time.perf_counter()
                    token = reply.get("content", "")
                    if token:
                        yield {"type": "token", "token": token}

                    llm_ms = (time.perf_counter() - t_llm_start) * 1000
                    yield {
                        "type": "done",
                        "timing": self._timing(0, llm_ms, t_start),
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    }

        except Exception as e:
            log.error("Agent error: %s", e)
            yield {"type": "token", "token": f"Error communicating with agent: {str(e)}"}
            yield {"type": "done", "timing": self._timing(0, 0, t_start), "prompt_tokens": 0, "completion_tokens": 0}

    @staticmethod
    def _timing(retrieve_ms: float, llm_ms: float, t_start: float) -> Dict:
        total_ms = (time.perf_counter() - t_start) * 1000
        return {
            "retrieve_ms": round(retrieve_ms),
            "llm_ms": round(llm_ms),
            "total_ms": round(total_ms),
            "total_s": round(total_ms / 1000, 2),
        }
