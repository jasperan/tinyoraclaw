from pydantic import BaseModel
from typing import Optional


class SaveSessionRequest(BaseModel):
    teamId: str
    agentId: str = "default"
    sessionId: Optional[str] = None
    history: str  # JSON string or markdown content
    channel: Optional[str] = None
    label: Optional[str] = None


class SessionResponse(BaseModel):
    session_key: str
    session_id: str
    team_id: str
    agent_id: str
    updated_at: int
    session_data: Optional[str] = None
    channel: Optional[str] = None
    label: Optional[str] = None
