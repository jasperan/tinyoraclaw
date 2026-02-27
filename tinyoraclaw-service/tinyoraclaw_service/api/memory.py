from fastapi import APIRouter, Request, HTTPException

from ..models.memory import RememberRequest, RecallRequest

router = APIRouter(prefix="/api/memory")


def _get_memory_service(request: Request):
    svc = getattr(request.app.state, "memory_service", None)
    if not svc:
        raise HTTPException(status_code=503, detail="Memory service not available")
    return svc


@router.post("/remember")
async def remember(request: Request, body: RememberRequest):
    """Store a memory with auto-generated vector embedding."""
    svc = _get_memory_service(request)
    result = await svc.remember(
        text=body.text,
        agent_id=body.agent_id,
        importance=body.importance,
        category=body.category,
    )
    return result


@router.post("/recall")
async def recall(request: Request, body: RecallRequest):
    """Semantic vector search over stored memories."""
    svc = _get_memory_service(request)
    results = await svc.recall(
        query=body.query,
        agent_id=body.agent_id,
        max_results=body.max_results,
        min_score=body.min_score,
    )
    return {"results": results, "count": len(results)}


@router.delete("/forget/{memory_id}")
async def forget(request: Request, memory_id: str):
    """Delete a memory by ID."""
    svc = _get_memory_service(request)
    result = await svc.forget(memory_id)
    return result


@router.get("/count")
async def count_memories(request: Request, agent_id: str = "default"):
    """Count memories for an agent."""
    svc = _get_memory_service(request)
    return await svc.count_memories(agent_id)


@router.get("/status")
async def memory_status(request: Request):
    """Get table counts for core tables."""
    svc = _get_memory_service(request)
    return await svc.get_status()
