import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import TinyoraclawSettings
from .db.connection import OracleConnectionManager
from .db.schema import init_schema
from .services.embedding_service import EmbeddingService
from .services.memory_service import MemoryService
from .services.queue_service import QueueService
from .services.session_service import SessionService
from .services.transcript_service import TranscriptService
from .api import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = TinyoraclawSettings()
    app.state.settings = settings

    conn_mgr = OracleConnectionManager(settings)
    try:
        pool = await conn_mgr.create_pool()
        app.state.pool = pool
        logger.info("Oracle connection pool created (min=%d, max=%d)",
                     settings.oracle_pool_min, settings.oracle_pool_max)
    except Exception as e:
        logger.error("Failed to create Oracle connection pool: %s", e)
        app.state.pool = None
        pool = None

    # Auto-init schema if configured
    if settings.auto_init and pool:
        try:
            result = await init_schema(pool)
            logger.info("Auto-init schema: %s", result)
        except Exception as e:
            logger.warning("Auto-init failed (run POST /api/init manually): %s", e)

    # Create queue service
    if pool:
        app.state.queue_service = QueueService(pool)
        logger.info("QueueService initialized")
    else:
        app.state.queue_service = None
        logger.warning("QueueService unavailable (no pool)")

    # Create embedding + memory services
    embedding_service = None
    if pool:
        try:
            embedding_service = EmbeddingService(settings)
            await embedding_service.initialize()
            memory_service = MemoryService(pool, embedding_service, settings)
            await memory_service.initialize()
            app.state.embedding_service = embedding_service
            app.state.memory_service = memory_service
            logger.info("EmbeddingService + MemoryService initialized")
        except Exception as e:
            logger.warning("Memory services unavailable: %s", e)
            app.state.embedding_service = None
            app.state.memory_service = None
    else:
        app.state.embedding_service = None
        app.state.memory_service = None
        logger.warning("Memory services unavailable (no pool)")

    # Create session + transcript services
    if pool:
        app.state.session_service = SessionService(pool)
        app.state.transcript_service = TranscriptService(pool)
        logger.info("SessionService + TranscriptService initialized")
    else:
        app.state.session_service = None
        app.state.transcript_service = None
        logger.warning("SessionService + TranscriptService unavailable (no pool)")

    yield

    # Shutdown
    if embedding_service:
        await embedding_service.close()
        logger.info("EmbeddingService closed")
    if pool:
        await conn_mgr.close_pool()
        logger.info("Oracle connection pool closed")


app = FastAPI(
    title="TinyOraClaw Service",
    version="0.1.0",
    description="Python sidecar for TinyOraClaw - Oracle AI Database powered multi-agent assistant",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Optional bearer token authentication.

    When TINYORACLAW_SERVICE_TOKEN is set, all requests must include
    a matching Authorization: Bearer <token> header.
    When not set, all requests are allowed (local dev mode).
    """

    async def dispatch(self, request: Request, call_next):
        token = request.app.state.settings.tinyoraclaw_service_token
        if token:
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], token):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)


app.add_middleware(BearerTokenMiddleware)

app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    settings = TinyoraclawSettings()
    uvicorn.run(
        "tinyoraclaw_service.main:app",
        host="0.0.0.0",
        port=settings.tinyoraclaw_service_port,
        reload=True,
    )
