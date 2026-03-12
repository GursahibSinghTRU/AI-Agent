"""
agent.py — The Policy Agent: retrieval + LLM answering + streaming via TOOL CALLING.

Improvements:
  • Uses Ollama's native tool calling (`tools` array) to let the LLM decide when to search.
  • Prevents blind vector searches for conversational greetings.
"""

import json
import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

from app.config import settings
from app.rag_core import (
    load_vector_db,
    retrieve_with_threshold,
    format_context,
    extract_sources_from_context,
    SYSTEM_PROMPT
)

log = logging.getLogger("agent")


def _build_messages(question: str, chat_history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if chat_history:
        for msg in chat_history[-4:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    messages.append({"role": "user", "content": question})
    return messages


# ── Agent ────────────────────────────────────────────────────────────────────

class PolicyAgent:
    """
    RAG agent that retrieves from TRU policy documents and generates
    answers via a local Ollama model. Supports streaming tool calls.
    """

    def __init__(self):
        log.info("Loading vector DB from %s …", settings.persist_path)
        self.vectordb = load_vector_db()
        log.info("PolicyAgent ready.")

        # Define the tool that Qwen can call to query the RAG database
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": "Search the TRU policy vector database for information relevant to a query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The specific query string to search for in the vector database (e.g. 'expense reimbursement rules', 'animal control policy')"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    # ── Core retrieval ────────────────────

    def _retrieve(self, query: str):
        t0 = time.perf_counter()
        retrieved = retrieve_with_threshold(
            self.vectordb, query,
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
        """Return a complete answer dict (non-streaming legacy fallback)."""
        # We will wrap the streaming logic and just collect it
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
        
        return {
            "answer": answer_text,
            "sources": sources,
            "timing": timing
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
        messages = _build_messages(question, chat_history)

        try:
            with httpx.Client(timeout=120.0) as client:
                log.info("Sending initial request with tools...")
                response = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.CHAT_MODEL,
                        "messages": messages,
                        "tools": self.tools,
                        "stream": False,
                        "temperature": settings.TEMPERATURE,
                        "think": False
                    },
                )
                response.raise_for_status()
                data = response.json()
                reply = data["message"]
                messages.append(reply)

                # Variables to hold timing if we retrieve
                retrieve_ms = 0
                sources_to_emit = []

                # Did the model call a tool?
                if reply.get("tool_calls"):
                    log.info(f"Model chose to use {len(reply['tool_calls'])} tools.")
                    for tool_call in reply["tool_calls"]:
                        fn_name = tool_call["function"]["name"]
                        args = tool_call["function"]["arguments"]
                        
                        if fn_name == "search_knowledge_base":
                            search_query = args.get("query", question)
                            log.info(f"Executing search_knowledge_base for query: '{search_query}'")
                            
                            context, sources, _, r_ms = self._retrieve(search_query)
                            retrieve_ms += r_ms
                            
                            if context:
                                tool_result = f"Documents retrieved:\n{context}"
                                sources_to_emit.extend(sources)
                            else:
                                tool_result = "No documents found matching the query."

                            # Append tool result to messages
                            messages.append({
                                "role": "tool",
                                "content": tool_result,
                                "name": fn_name
                            })
                    
                    # Emit matching sources to the UI immediately
                    if sources_to_emit:
                         yield {"type": "sources", "sources": sources_to_emit[:6]}
                    
                    # Make the follow-up request to get the final generated answer (streaming this time)
                    log.info("Streaming follow-up answer...")
                    follow_response = client.post(
                        f"{settings.OLLAMA_BASE_URL}/api/chat",
                        json={
                            "model": settings.CHAT_MODEL,
                            "messages": messages,
                            "stream": True,
                            "temperature": settings.TEMPERATURE,
                            "think": False
                        },
                    )
                    follow_response.raise_for_status()
                    
                    t_llm_start = time.perf_counter()
                    collected = []
                    for line in follow_response.iter_lines():
                        if not line: continue
                        chunk = json.loads(line)
                        if "message" in chunk and chunk["message"].get("content"):
                            token = chunk["message"]["content"]
                            collected.append(token)
                            yield {"type": "token", "token": token}
                    
                    llm_ms = (time.perf_counter() - t_llm_start) * 1000
                    
                    full_text = "".join(collected)
                    if "Not found in the provided documents." in full_text:
                         yield {"type": "clear_sources"}

                    yield {"type": "done", "timing": self._timing(retrieve_ms, llm_ms, t_start)}
                    return
                
                else:
                    # Model answered directly without querying the DB (e.g. conversational)
                    log.info("Model answered directly without tools.")
                    t_llm_start = time.perf_counter()
                    token = reply.get("content", "")
                    if token:
                        yield {"type": "token", "token": token}
                    
                    llm_ms = (time.perf_counter() - t_llm_start) * 1000
                    yield {"type": "done", "timing": self._timing(0, llm_ms, t_start)}
                    return

        except Exception as e:
            log.error("Ollama Tool/Streaming error: %s", e)
            yield {"type": "token", "token": f"Error communicating with agent: {str(e)}"}
            yield {"type": "done", "timing": self._timing(0, 0, t_start)}


    @staticmethod
    def _timing(retrieve_ms: float, llm_ms: float, t_start: float) -> Dict:
        total_ms = (time.perf_counter() - t_start) * 1000
        return {
            "retrieve_ms": round(retrieve_ms),
            "llm_ms": round(llm_ms),
            "total_ms": round(total_ms),
            "total_s": round(total_ms / 1000, 2),
        }
