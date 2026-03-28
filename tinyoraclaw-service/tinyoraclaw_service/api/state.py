from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter()


class SetStateRequest(BaseModel):
    agentId: str = "default"
    value: Any


def _get_state_service(request: Request):
    svc = request.app.state.state_service
    if not svc:
        raise HTTPException(status_code=503, detail="State service not available")
    return svc


@router.get('/api/state/{state_key:path}')
async def get_state(state_key: str, request: Request, agentId: Optional[str] = 'default'):
    svc = _get_state_service(request)
    value = await svc.get_state(state_key, agent_id=agentId or 'default')
    return {"value": value}


@router.put('/api/state/{state_key:path}')
async def set_state(state_key: str, body: SetStateRequest, request: Request):
    svc = _get_state_service(request)
    await svc.set_state(state_key, body.value, agent_id=body.agentId)
    return {"ok": True}


@router.delete('/api/state/{state_key:path}')
async def delete_state(state_key: str, request: Request, agentId: Optional[str] = 'default'):
    svc = _get_state_service(request)
    deleted = await svc.delete_state(state_key, agent_id=agentId or 'default')
    return {"deleted": deleted}
