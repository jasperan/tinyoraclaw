from fastapi import APIRouter, HTTPException, Request

from ..models.sessions import SaveSessionRequest

router = APIRouter()


def _get_session_service(request: Request):
    svc = request.app.state.session_service
    if not svc:
        raise HTTPException(status_code=503, detail="Session service not available")
    return svc


@router.post("/api/sessions/save")
async def save_session(data: SaveSessionRequest, request: Request):
    svc = _get_session_service(request)
    result = await svc.save_session(
        team_id=data.teamId,
        agent_id=data.agentId,
        session_id=data.sessionId,
        history=data.history,
        channel=data.channel,
        label=data.label,
    )
    return result


@router.get("/api/sessions/{team_id}")
async def get_sessions(team_id: str, request: Request):
    svc = _get_session_service(request)
    sessions = await svc.get_session(team_id)
    return {"sessions": sessions}


@router.get("/api/sessions")
async def list_sessions(request: Request):
    svc = _get_session_service(request)
    sessions = await svc.list_sessions()
    return {"sessions": sessions}


@router.delete("/api/sessions/{session_key}")
async def delete_session(session_key: str, request: Request):
    svc = _get_session_service(request)
    result = await svc.delete_session(session_key)
    return result
