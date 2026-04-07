#!/usr/bin/env python3
"""
ingest.py — Ingest (or re-ingest) PDFs into the ChromaDB vector store.

Features:
  • Incremental — only embeds new/changed chunks (content-hashed dedup)
  • Progress reporting
  • Dry-run mode

Usage:
  python ingest.py              # incremental ingest
  python ingest.py --fresh      # wipe DB and re-ingest everything
  python ingest.py --dry-run    # just show what would happen
"""

import argparse
import logging
import shutil
import sys
import time

from app.config import settings
from app.rag_core import build_vector_db, chunk_documents, load_documents

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-10s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def main():
    parser = argparse.ArgumentParser(description="Ingest TRU Risk & Safety docs into ChromaDB")
    parser.add_argument("--fresh", action="store_true", help="Wipe existing DB and re-ingest everything")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without writing")
    args = parser.parse_args()

    data_dir = settings.data_path
    persist_dir = settings.persist_path

    # ── Validate ─────────────────────────────────────────────────────
    if not data_dir.is_dir():
        log.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    files = list(data_dir.glob("*.pdf")) + list(data_dir.glob("*.txt"))
    if not files:
        log.error("No PDFs or TXT files found in %s", data_dir)
        log.error("Drop your Risk & Safety docs into the data/ folder and run this again.")
        sys.exit(1)

    log.info("═══ INGEST START ═══")
    log.info("Data dir : %s  (%d files)", data_dir, len(files))
    log.info("DB dir   : %s", persist_dir)

    # ── Fresh mode ───────────────────────────────────────────────────
    if args.fresh and persist_dir.exists():
        if args.dry_run:
            log.info("[DRY RUN] Would delete %s", persist_dir)
        else:
            log.warning("Wiping existing DB at %s", persist_dir)
            shutil.rmtree(persist_dir)

    # ── Load ─────────────────────────────────────────────────────────
    t0 = time.time()
    docs = load_documents(data_dir)
    log.info("Loaded %d page segments in %.1fs", len(docs), time.time() - t0)

    # ── Chunk ────────────────────────────────────────────────────────
    t1 = time.time()
    chunks = chunk_documents(docs)
    log.info("Created %d chunks in %.1fs  (size=%d, overlap=%d)",
             len(chunks), time.time() - t1,
             settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)

    if args.dry_run:
        log.info("[DRY RUN] Would embed %d chunks — exiting.", len(chunks))
        return

    # ── Embed + Store ────────────────────────────────────────────────
    t2 = time.time()
    vectordb = build_vector_db(chunks)
    elapsed = time.time() - t2

    try:
        final_count = vectordb._collection.count()
    except Exception:
        final_count = "?"

    log.info("Embedding complete in %.1fs", elapsed)
    log.info("Total chunks in DB: %s", final_count)
    log.info("═══ INGEST DONE ═══")


if __name__ == "__main__":
    main()
