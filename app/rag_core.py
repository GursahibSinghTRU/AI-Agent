"""
rag_core.py — PDF ingestion, vector storage, retrieval, and prompt building.

Improvements over original:
  • Metadata-enriched chunks (policy title extracted from filename)
  • Duplicate-aware ingestion (content hashing → skip already-stored chunks)
  • Higher-quality retrieval with score-based sorting
  • Conversation-aware QA prompt
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

log = logging.getLogger("rag")


# ─── Embeddings ──────────────────────────────────────────────────────────────

def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=settings.EMBEDDING_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )


# ─── Document Loading ────────────────────────────────────────────────────────

_POLICY_RE = re.compile(
    r"^(?P<code>[A-Z]+_[\d]+-?\d*)"   # e.g. ADM_04-2
    r"[_ ]+"
    r"(?P<title>.+?)"                  # human title
    r"(?:__|_\d{4}|\d{4,5})"          # date/id suffix noise
    r".*$",
)


def _policy_title_from_filename(fname: str) -> str:
    """Extract a clean policy name from the mangled PDF filenames."""
    stem = Path(fname).stem
    m = _POLICY_RE.match(stem)
    if m:
        code = m.group("code").replace("_", " ")
        title = m.group("title").replace("_", " ").strip(" _,")
        return f"{code} – {title}"
    return stem.replace("_", " ")


def load_documents(data_dir: Path):
    """Load PDFs and text files, attaching enriched metadata."""
    docs = []
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    for fpath in sorted(data_dir.iterdir()):
        try:
            if fpath.suffix.lower() == ".pdf":
                loaded = PyPDFLoader(str(fpath)).load()
            elif fpath.suffix.lower() == ".txt":
                loaded = TextLoader(str(fpath), encoding="utf-8").load()
            else:
                continue

            policy_title = _policy_title_from_filename(fpath.name)
            for doc in loaded:
                doc.metadata["policy_title"] = policy_title
                doc.metadata["filename"] = fpath.name
            docs.extend(loaded)

        except Exception:
            log.exception("Failed to load %s — skipping", fpath.name)

    return docs


# ─── Chunking ────────────────────────────────────────────────────────────────

def chunk_documents(
    docs,
    chunk_size: int = settings.CHUNK_SIZE,
    chunk_overlap: int = settings.CHUNK_OVERLAP,
):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        length_function=len,
    )
    chunks = splitter.split_documents(docs)

    # Prefix each chunk with its policy title so the embedding captures it
    for chunk in chunks:
        title = chunk.metadata.get("policy_title", "")
        if title and not chunk.page_content.startswith(title):
            chunk.page_content = f"[{title}]\n{chunk.page_content}"

    return chunks


# ─── Content Hashing (dedup) ────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ─── Vector DB ───────────────────────────────────────────────────────────────

def load_vector_db() -> Chroma:
    return Chroma(
        embedding_function=get_embeddings(),
        persist_directory=str(settings.persist_path),
        collection_name=settings.COLLECTION_NAME,
    )


def build_vector_db(
    chunks,
    batch_size: int = 64,
) -> Chroma:
    """Create / update the Chroma collection, skipping duplicates."""
    vectordb = Chroma(
        embedding_function=get_embeddings(),
        persist_directory=str(settings.persist_path),
        collection_name=settings.COLLECTION_NAME,
    )

    # Gather existing hashes to avoid re-embedding
    existing_ids = set()
    try:
        col = vectordb._collection
        stored = col.get(include=[])
        existing_ids = set(stored["ids"]) if stored and stored.get("ids") else set()
    except Exception:
        pass

    new_chunks = []
    new_ids = []
    for chunk in chunks:
        cid = _content_hash(chunk.page_content)
        if cid not in existing_ids:
            new_chunks.append(chunk)
            new_ids.append(cid)
            existing_ids.add(cid)

    if not new_chunks:
        log.info("No new chunks to embed — DB is up-to-date.")
        return vectordb

    total = len(new_chunks)
    log.info("Embedding %d new chunks (skipped %d duplicates)", total, len(chunks) - total)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        vectordb.add_documents(
            new_chunks[start:end],
            ids=new_ids[start:end],
        )
        log.info("  embedded %d / %d", end, total)

    return vectordb


# ─── Retrieval ───────────────────────────────────────────────────────────────

def retrieve_with_threshold(
    vectordb: Chroma,
    query: str,
    k: int = settings.K,
    score_threshold: float = settings.SCORE_THRESHOLD,
) -> List[Tuple[Any, float]]:
    """
    Retrieve k candidates, filter by distance threshold,
    and return sorted best-first.
    """
    results = vectordb.similarity_search_with_score(query, k=k)
    filtered = [(doc, score) for doc, score in results if score <= score_threshold]
    filtered.sort(key=lambda x: x[1])
    return filtered


# ─── Context Formatting ─────────────────────────────────────────────────────

def format_context(
    retrieved: List[Tuple[Any, float]],
    max_chars: int = settings.MAX_CONTEXT_CHARS,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    Build a context string and structured source list from retrieved chunks.
    """
    parts: List[str] = []
    sources: List[Dict[str, str]] = []
    seen_sources = set()
    char_count = 0

    for doc, score in retrieved:
        policy = doc.metadata.get("policy_title", "Unknown Policy")
        fname = doc.metadata.get("filename", "unknown")
        page = doc.metadata.get("page")
        tag = f"{policy}" + (f" (p. {int(page) + 1})" if page is not None else "")

        chunk_text = (doc.page_content or "").strip()
        if not chunk_text:
            continue

        entry = f"[Source: {tag}]\n{chunk_text}"

        if char_count + len(entry) > max_chars:
            break

        parts.append(entry)
        char_count += len(entry) + 2

        src_key = f"{fname}:{page}"
        if src_key not in seen_sources:
            seen_sources.add(src_key)
            sources.append({
                "policy": policy,
                "file": fname,
                "page": int(page) + 1 if page is not None else None,
                "relevance": round(1.0 - score, 3),
            })

    context = "\n\n".join(parts)
    return context, sources


# ─── Prompts ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the TRU Policy Assistant — an expert on Thompson Rivers University policies.

RULES:
1. Answer **only** from the Context below. Never use outside knowledge.
2. If the Context does not contain the answer, reply with exactly:
   Not found in the provided documents.
3. Be precise. Cite the policy name and page when possible (e.g., "ADM 04-2 – Conflict of Interest, p. 3").
4. Use clear, professional language. Use bullet points for lists; keep answers concise (≤ 6 bullets or 2 short paragraphs).
5. If a question is ambiguous, answer the most likely interpretation and note any assumptions.
"""

QA_TEMPLATE = """\
{system}

{history_block}
Context:
{context}

Question:
{question}

Answer:
"""


def build_qa_prompt(
    question: str,
    context: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    history_block = ""
    if chat_history:
        turns = []
        for msg in chat_history[-4:]:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            turns.append(f"{'User' if role == 'user' else 'Assistant'}: {text}")
        if turns:
            history_block = "Recent conversation:\n" + "\n".join(turns) + "\n"

    return QA_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        history_block=history_block,
        context=context,
        question=question,
    )
