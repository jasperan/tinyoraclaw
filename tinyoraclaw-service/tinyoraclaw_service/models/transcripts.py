from pydantic import BaseModel
from typing import Optional


class LogTranscriptRequest(BaseModel):
    agentId: str = "default"
    teamId: Optional[str] = None
    sessionId: Optional[str] = None
    channel: Optional[str] = None
    role: Optional[str] = None
    eventType: str = "message"
    content: str
