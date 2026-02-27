from fastapi import APIRouter

from .health import router as health_router
from .init_routes import router as init_router
from .memory import router as memory_router
from .queue import router as queue_router
from .sessions import router as sessions_router
from .transcripts import router as transcripts_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(init_router, tags=["init"])
api_router.include_router(memory_router, tags=["memory"])
api_router.include_router(queue_router, tags=["queue"])
api_router.include_router(sessions_router, tags=["sessions"])
api_router.include_router(transcripts_router, tags=["transcripts"])
