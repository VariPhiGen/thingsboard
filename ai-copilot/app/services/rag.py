from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)


class RagService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._collection = None
        self._ready = False

    def _ensure(self) -> bool:
        if self._ready:
            return self._collection is not None
        self._ready = True
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            Path(self.settings.rag_persist_dir).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self.settings.rag_persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(name="operator_copilot")
            return True
        except Exception as exc:  # pragma: no cover
            log.warning("RAG unavailable: %s", exc)
            self._collection = None
            return False

    def ingest_directory(self, knowledge_dir: str | None = None) -> int:
        if not self._ensure() or self._collection is None:
            return 0
        root = Path(knowledge_dir or self.settings.knowledge_dir)
        if not root.exists():
            return 0
        docs: list[str] = []
        ids: list[str] = []
        metas: list[dict] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".txt", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            for idx, chunk in enumerate(self._chunk(text)):
                digest = hashlib.sha1(f"{path}:{idx}:{chunk[:64]}".encode()).hexdigest()
                docs.append(chunk)
                ids.append(digest)
                metas.append({"source": str(path.relative_to(root)), "chunk": idx})
        if not docs:
            return 0
        # upsert in batches
        batch = 50
        for i in range(0, len(docs), batch):
            self._collection.upsert(
                documents=docs[i : i + batch],
                ids=ids[i : i + batch],
                metadatas=metas[i : i + batch],
            )
        return len(docs)

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        if not query or not self._ensure() or self._collection is None:
            return []
        k = top_k or self.settings.rag_top_k
        try:
            result = self._collection.query(query_texts=[query], n_results=k)
        except Exception as exc:  # pragma: no cover
            log.warning("RAG query failed: %s", exc)
            return []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        out = []
        for doc, meta in zip(docs, metas):
            out.append({"text": doc, "source": (meta or {}).get("source", "knowledge")})
        return out

    def format_snippets(self, snippets: list[dict]) -> str:
        if not snippets:
            return ""
        parts = []
        for s in snippets:
            parts.append(f"[{s.get('source')}]\n{s.get('text')}")
        return "\n\n".join(parts)

    @staticmethod
    def _chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
        text = text.strip()
        if len(text) <= size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            chunks.append(text[start:end])
            if end == len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks
