import logging

from fastapi import APIRouter, Request, HTTPException

from ..db.schema import init_schema

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/init")
async def initialize(request: Request):
    pool = request.app.state.pool

    if not pool:
        raise HTTPException(status_code=503, detail="Database pool not available")

    # Create tables and indexes
    schema_result = await init_schema(pool)
    logger.info("Schema init result: %s", schema_result)

    return {
        "status": "initialized",
        "tables_created": schema_result.get("tables_created", []),
        "indexes_created": schema_result.get("indexes_created", []),
        "errors": schema_result.get("errors", []),
    }
