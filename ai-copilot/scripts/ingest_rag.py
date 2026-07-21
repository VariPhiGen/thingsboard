#!/usr/bin/env python3
"""Rebuild Chroma RAG index from ai-copilot/knowledge."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.rag import RagService


def main() -> None:
    settings = get_settings()
    rag = RagService(settings)
    count = rag.ingest_directory(settings.knowledge_dir)
    print(f"Ingested {count} chunks into {settings.rag_persist_dir}")


if __name__ == "__main__":
    main()
