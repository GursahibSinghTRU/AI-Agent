"""
Configuration — all tunables in one place.

Override any value via environment variables (same name, uppercased).
Example:  CHAT_MODEL=llama3:8b  python run.py
"""

import os
from dataclasses import dataclass, fields
from pathlib import Path

# Project root = parent of the app/ package
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default):
    """Read from env; cast to the type of *default*."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    target = type(default)
    if target is bool:
        return raw.strip().lower() in ("1", "true", "yes")
    return target(raw)


@dataclass(frozen=True)
class Settings:
    # ── Paths (relative to project root) ─────────────────────────
    DATA_DIR: str          = "data"
    PERSIST_DIR: str       = "chroma_db"
    FRONTEND_DIR: str      = "frontend"
    COLLECTION_NAME: str   = "riskandsafety_docs"

    # ── Chunking ─────────────────────────────────────────────────
    CHUNK_SIZE: int        = 1000
    CHUNK_OVERLAP: int     = 200

    # ── Retrieval ────────────────────────────────────────────────
    K: int                 = 6
    SCORE_THRESHOLD: float = 1.0
    MAX_CONTEXT_CHARS: int = 8000
    RERANK_TOP_N: int      = 4

    # ── Models (100 % local via Ollama) ──────────────────────────
    EMBEDDING_MODEL: str   = "nomic-embed-text"
    CHAT_MODEL: str        = "qwen3.5:9b"

    # ── LLM behaviour ───────────────────────────────────────────
    TEMPERATURE: float     = 0.1
    NUM_PREDICT: int       = 256
    KEEP_ALIVE: str        = "5m"

    # ── Server ───────────────────────────────────────────────────
    HOST: str              = "localhost"
    PORT: int              = 8000
    ALLOWED_ORIGINS: str   = "*"
    LOG_LEVEL: str         = "info"

    # ── Ollama ───────────────────────────────────────────────────
    OLLAMA_BASE_URL: str   = "http://localhost:11434"

    # ── Supabase (Analytics) ─────────────────────────────────
    SUPABASE_URL: str      = "https://lrzztpkleysibozjculg.supabase.co"
    SUPABASE_ANON_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxyenp0cGtsZXlzaWJvempjdWxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0NTExMzQsImV4cCI6MjA5MDAyNzEzNH0.IMgJ-a4pwPAtfFecsIRlcHlmuj5KwhzywiqsX_FpCbI"

    # ── Resolved absolute paths (computed) ───────────────────────
    @property
    def data_path(self) -> Path:
        return PROJECT_ROOT / self.DATA_DIR

    @property
    def persist_path(self) -> Path:
        return PROJECT_ROOT / self.PERSIST_DIR

    @property
    def frontend_path(self) -> Path:
        return PROJECT_ROOT / self.FRONTEND_DIR


def _load() -> Settings:
    """Build a Settings instance with env-var overrides."""
    overrides = {}
    for f in fields(Settings):
        overrides[f.name] = _env(f.name.upper(), f.default)
    return Settings(**overrides)


settings = _load()
