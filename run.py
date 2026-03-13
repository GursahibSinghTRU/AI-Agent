#!/usr/bin/env python3
"""
run.py — Start the TRU Risk & Safety Assistant server.

Usage:
  python run.py
  python run.py --port 9000
"""

import argparse
import logging
import sys

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(name)-12s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")


def main():
    parser = argparse.ArgumentParser(description="Start the TRU Risk & Safety Assistant")
    parser.add_argument("--host", default=settings.HOST, help="Bind address")
    parser.add_argument("--port", type=int, default=settings.PORT, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")
    args = parser.parse_args()

    # Preflight check: does the vector DB exist?
    if not settings.persist_path.exists():
        log.warning(
            "Vector DB not found at %s — run 'python ingest.py' first to build it.",
            settings.persist_path,
        )

    import uvicorn

    # Display localhost in the message for user convenience (0.0.0.0 isn't browser-accessible)
    display_host = "localhost" if args.host == "0.0.0.0" else args.host
    log.info("Starting TRU Risk & Safety Assistant on http://%s:%s", display_host, args.port)
    uvicorn.run(
        "app.server:app",
        host=args.host,
        port=args.port,
        log_level=settings.LOG_LEVEL,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
