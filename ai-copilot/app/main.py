from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.config import get_settings
from app.services.memory import ConversationMemory
from app.services.rag import RagService
from app.services.session import CopilotOrchestrator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-copilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    memory = ConversationMemory(settings)
    rag = RagService(settings)
    count = rag.ingest_directory(settings.knowledge_dir)
    log.info("RAG ingested %s chunks from %s", count, settings.knowledge_dir)
    app.state.settings = settings
    app.state.memory = memory
    app.state.rag = rag
    app.state.orchestrator = CopilotOrchestrator(settings, memory, rag)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
