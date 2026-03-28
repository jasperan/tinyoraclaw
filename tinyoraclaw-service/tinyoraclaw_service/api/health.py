from fastapi import APIRouter, Request

from ..db.schema import check_tables_exist, get_schema_version, ALL_TABLES

router = APIRouter()


@router.get("/api/health")
async def health(request: Request):
    pool = request.app.state.pool
    settings = request.app.state.settings

    pool_info = {"min": 0, "max": 0, "busy": 0, "open": 0}
    if pool:
        pool_info = {
            "min": pool.min,
            "max": pool.max,
            "busy": pool.busy,
            "open": pool.opened,
        }

    tables = {}
    schema_version = "unknown"
    if pool:
        try:
            tables = await check_tables_exist(pool)
        except Exception:
            tables = {t: False for t in ALL_TABLES}
        try:
            schema_version = await get_schema_version(pool)
        except Exception:
            pass

    return {
        "status": "ok",
        "pool": pool_info,
        "onnx_model": settings.oracle_onnx_model,
        "tables": tables,
        "schema_version": schema_version,
    }
