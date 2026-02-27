from fastapi import APIRouter, HTTPException, Query, Request

from ..models.queue import (
    EnqueueMessageRequest,
    EnqueueResponseRequest,
    FailMessageRequest,
)

router = APIRouter()


def _get_queue_service(request: Request):
    svc = request.app.state.queue_service
    if not svc:
        raise HTTPException(status_code=503, detail="Queue service not available")
    return svc


# ── Messages (incoming queue) ─────────────────────────────────────────────


@router.post("/api/queue/enqueue")
async def enqueue_message(data: EnqueueMessageRequest, request: Request):
    svc = _get_queue_service(request)
    row_id = await svc.enqueue_message(data)
    return {"id": row_id, "status": "pending"}


@router.get("/api/queue/next/{agent_id}")
async def claim_next_message(agent_id: str, request: Request):
    svc = _get_queue_service(request)
    msg = await svc.claim_next_message(agent_id)
    if msg is None:
        return {"message": None}
    return {"message": msg}


@router.patch("/api/queue/{row_id}/complete")
async def complete_message(row_id: int, request: Request):
    svc = _get_queue_service(request)
    await svc.complete_message(row_id)
    return {"status": "completed"}


@router.patch("/api/queue/{row_id}/fail")
async def fail_message(row_id: int, body: FailMessageRequest, request: Request):
    svc = _get_queue_service(request)
    await svc.fail_message(row_id, body.error)
    return {"status": "failed"}


@router.get("/api/queue/status")
async def get_queue_status(request: Request):
    svc = _get_queue_service(request)
    return await svc.get_queue_status()


@router.get("/api/queue/dead")
async def get_dead_messages(request: Request):
    svc = _get_queue_service(request)
    messages = await svc.get_dead_messages()
    return {"messages": messages}


@router.post("/api/queue/dead/{row_id}/retry")
async def retry_dead_message(row_id: int, request: Request):
    svc = _get_queue_service(request)
    success = await svc.retry_dead_message(row_id)
    if not success:
        raise HTTPException(status_code=404, detail="Dead message not found")
    return {"status": "retrying"}


@router.delete("/api/queue/dead/{row_id}")
async def delete_dead_message(row_id: int, request: Request):
    svc = _get_queue_service(request)
    success = await svc.delete_dead_message(row_id)
    if not success:
        raise HTTPException(status_code=404, detail="Dead message not found")
    return {"status": "deleted"}


@router.post("/api/queue/recover-stale")
async def recover_stale_messages(request: Request):
    svc = _get_queue_service(request)
    recovered = await svc.recover_stale_messages()
    return {"recovered": recovered}


@router.delete("/api/queue/prune/responses")
async def prune_acked_responses(request: Request):
    svc = _get_queue_service(request)
    pruned = await svc.prune_acked_responses()
    return {"pruned": pruned}


@router.delete("/api/queue/prune/messages")
async def prune_completed_messages(request: Request):
    svc = _get_queue_service(request)
    pruned = await svc.prune_completed_messages()
    return {"pruned": pruned}


@router.get("/api/queue/pending-agents")
async def get_pending_agents(request: Request):
    svc = _get_queue_service(request)
    agents = await svc.get_pending_agents()
    return {"agents": agents}


# ── Responses (outgoing queue) ────────────────────────────────────────────


@router.post("/api/responses/enqueue")
async def enqueue_response(data: EnqueueResponseRequest, request: Request):
    svc = _get_queue_service(request)
    row_id = await svc.enqueue_response(data)
    return {"id": row_id, "status": "pending"}


@router.get("/api/responses/pending")
async def get_responses_for_channel(
    request: Request, channel: str = Query(..., description="Channel name"),
):
    svc = _get_queue_service(request)
    responses = await svc.get_responses_for_channel(channel)
    return {"responses": responses}


@router.get("/api/responses/recent")
async def get_recent_responses(
    request: Request, limit: int = Query(20, ge=1, le=500),
):
    svc = _get_queue_service(request)
    responses = await svc.get_recent_responses(limit)
    return {"responses": responses}


@router.post("/api/responses/{response_id}/ack")
async def ack_response(response_id: int, request: Request):
    svc = _get_queue_service(request)
    await svc.ack_response(response_id)
    return {"status": "acked"}
