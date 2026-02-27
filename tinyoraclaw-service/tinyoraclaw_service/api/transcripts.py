from fastapi import APIRouter, HTTPException, Query, Request

from ..models.transcripts import LogTranscriptRequest

router = APIRouter()


def _get_transcript_service(request: Request):
    svc = request.app.state.transcript_service
    if not svc:
        raise HTTPException(status_code=503, detail="Transcript service not available")
    return svc


@router.post("/api/transcripts/log")
async def log_transcript(data: LogTranscriptRequest, request: Request):
    svc = _get_transcript_service(request)
    result = await svc.log_transcript(
        agent_id=data.agentId,
        team_id=data.teamId,
        session_id=data.sessionId,
        channel=data.channel,
        role=data.role,
        event_type=data.eventType,
        content=data.content,
    )
    return result


@router.get("/api/transcripts/{agent_id}")
async def get_transcripts(agent_id: str, request: Request,
                          limit: int = Query(50, ge=1, le=500)):
    svc = _get_transcript_service(request)
    transcripts = await svc.get_transcripts(agent_id, limit=limit)
    return {"transcripts": transcripts}


@router.get("/api/transcripts/team/{team_id}")
async def get_transcripts_by_team(team_id: str, request: Request,
                                  limit: int = Query(50, ge=1, le=500)):
    svc = _get_transcript_service(request)
    transcripts = await svc.get_transcripts_by_team(team_id, limit=limit)
    return {"transcripts": transcripts}
