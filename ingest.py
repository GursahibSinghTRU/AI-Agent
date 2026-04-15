#!/usr/bin/env python3
"""
ingest.py — Ingest (or re-ingest) PDFs and TXT files into the Oracle vector store.

Features:
  • Incremental — only embeds new/changed chunks (content-hashed dedup)
  • Progress reporting
  • Dry-run mode

Usage:
  python ingest.py              # incremental ingest
  python ingest.py --dry-run    # just show what would happen
"""

import argparse
import logging
import sys
import time

from app.config import settings
from app.rag_core import build_oracle_db, chunk_documents, load_documents

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-10s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def main():
    parser = argparse.ArgumentParser(description="Ingest TRU Risk & Safety docs into Oracle vector DB")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without writing")
    parser.add_argument("--wipe", action="store_true", help="Delete all existing chunks before ingesting")
    args = parser.parse_args()

    data_dir = settings.data_path

    if not data_dir.is_dir():
        log.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    files = [
        f for f in list(data_dir.glob("*.pdf")) + list(data_dir.glob("*.txt"))
        if f.name != "combined_context.txt"
    ]
    if not files:
        log.error("No PDFs or TXT files found in %s", data_dir)
        sys.exit(1)

    log.info("═══ INGEST START ═══")
    log.info("Data dir : %s  (%d files)", data_dir, len(files))

    # ── Load ─────────────────────────────────────────────────────────
    t0 = time.time()
    docs = load_documents(data_dir)
    log.info("Loaded %d page segments in %.1fs", len(docs), time.time() - t0)

    # ── Chunk ────────────────────────────────────────────────────────
    t1 = time.time()
    chunks = chunk_documents(docs)
    log.info(
        "Created %d chunks in %.1fs  (size=%d, overlap=%d)",
        len(chunks), time.time() - t1,
        settings.CHUNK_SIZE, settings.CHUNK_OVERLAP,
    )

    if args.dry_run:
        log.info("[DRY RUN] Would embed %d chunks — exiting.", len(chunks))
        return

    # ── Wipe ─────────────────────────────────────────────────────────
    if args.wipe:
        from app.oracle_client import clear_chunks
        deleted = clear_chunks()
        log.info("Wiped %d existing chunks from Oracle DB", deleted)

    # ── Embed + Store ────────────────────────────────────────────────
    t2 = time.time()
    build_oracle_db(chunks)
    elapsed = time.time() - t2

    try:
        from app.oracle_client import get_chunk_count
        final_count = get_chunk_count()
    except Exception:
        final_count = "?"

    log.info("Embedding complete in %.1fs", elapsed)
    log.info("Total chunks in Oracle DB: %s", final_count)
    log.info("═══ INGEST DONE ═══")


if __name__ == "__main__":
    main()
