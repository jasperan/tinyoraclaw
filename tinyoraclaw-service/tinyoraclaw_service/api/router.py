from fastapi import APIRouter

from .health import router as health_router
from .init_routes import router as init_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(init_router, tags=["init"])
