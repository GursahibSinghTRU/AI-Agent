"""
agent.py - The Risk & Safety Agent: Context Injection + LLM Answer + Streaming

This version completely removes RAG indexing and tool calling.
It reads all text from `data/combined_context.txt` and provides it
to the LLM as the very first contextual message.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

from app.config import settings

log = logging.getLogger("agent")

SYSTEM_PROMPT = """\
You are an intelligent AI assistant Risk And Safety Services for Thompson Rivers University (TRU).
You will be provided with ALL the context from the Risk & Safety documents perfectly organized in the first user message.

CRITICAL INSTRUCTIONS:
1. The first message you receive from the user is pure context. Use it exclusively to ground your answers. Do NOT greet the context or treat it as a conversation starter.
2. Base your final answer strictly on the provided context chunks. If the provided context does not contain the answer, reply with exactly: "Not found in the provided documents."
3. **CITATIONS WITH HYPERLINKS**: When citing sources, ALWAYS include them as clickable markdown hyperlinks. Format: [Source Name](URL) or [Reference Text](URL). For example:
   - If citing from TRU_Risk_Safety_Training, use the URL from that section header
   - Example: "Health & Safety Course is available via Deltek/HRSmart [TRU_Risk_Safety_Training](https://example.com/training)"
   - Look for [URLs] in brackets in the source material and use those in your citations
   - Always make the source name or a brief descriptor clickable as a link
4. Use clear, professional language. Use bullet points for lists; keep answers concise (\u2264 6 bullets or 2 short paragraphs).
5. If the user asks a question that is not related to Risk and Safety, you should politely decline to answer and suggest they contact the appropriate department.
6. Make sure you remain neutral and objective. Do not express personal opinions or beliefs. State facts.
7. **END WITH HELPFUL NEXT STEPS**: Always end your response by being helpful and guiding the user forward. Include a related follow-up question or suggestion for what they might want to know next (e.g., "Would you like to know more about...?" or "You might also find it helpful to learn about..."). This helps nudge users toward relevant information you can help with.
"""

def _build_messages(question: str, chat_history: Optional[List[Dict[str, str]]], context_text: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Inject context as the first user message
    context_message = f"Here is all the context nicely organized. Do not consider this your first user message. Use it purely for grounding your responses:\n\n{context_text}"
    messages.append({"role": "user", "content": context_message})
    messages.append({"role": "assistant", "content": "Acknowledged. I have read the context and will base my answers solely on it."})
    
    if chat_history:
        for msg in chat_history[-4:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    messages.append({"role": "user", "content": question})
    return messages


#  Agent 

class RiskandSafetyAgent:
    """
    Agent that generates answers via a local Ollama model using an injected
    combined context file instead of RAG and tool calls.
    """

    def __init__(self):
        log.info("Loading combined context ...")
        self.context_text = ""
        context_file = os.path.join("data", "combined_context.txt")
        if os.path.exists(context_file):
            with open(context_file, "r", encoding="utf-8") as f:
                self.context_text = f.read()
            log.info(f"Loaded {len(self.context_text)} characters of context.")
        else:
            log.warning("combined_context.txt not found. Agent will have no context.")
        log.info("Risk & Safety Agent ready.")

    #  Blocking answer 

    def answer(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Return a complete answer dict (non-streaming legacy fallback)."""
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

    #  Streaming answer (SSE-friendly generator) 

    def stream(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        t_start = time.perf_counter()
        messages = _build_messages(question, chat_history, self.context_text)

        yield {"type": "sources", "sources": [{"file": "combined_context.txt", "Risk & Safety": "All Documents", "relevance": 1.0}]}

        log.info("Streaming answer based on full context ...")
        t_llm_start = time.perf_counter()
        
        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST",
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.CHAT_MODEL,
                        "messages": messages,
                        "stream": True,
                        "temperature": settings.TEMPERATURE,
                        "think": False
                    },
                ) as stream_response:
                    stream_response.raise_for_status()
                    for line in stream_response.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        token = chunk["message"]["content"]
                        if token:
                            yield {"type": "token", "token": token}
                        
                        if chunk.get("done"):
                            ms_total = (time.perf_counter() - t_start) * 1000
                            ms_llm = (time.perf_counter() - t_llm_start) * 1000
                            # Extract token counts from Ollama response
                            prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                            completion_tokens = chunk.get("eval_count", 0) or 0
                            yield {
                                "type": "done",
                                "timing": {
                                    "total_ms": int(ms_total),
                                    "llm_ms": int(ms_llm),
                                    "retrieve_ms": 0
                                },
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens
                            }
        except Exception as e:
            log.exception("Error during LLM stream")
            yield {"type": "token", "token": f"\n\n[Error: {str(e)}]"}

