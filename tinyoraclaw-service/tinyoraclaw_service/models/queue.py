from pydantic import BaseModel
from typing import Optional


class EnqueueMessageRequest(BaseModel):
    messageId: str
    channel: str
    sender: str
    senderId: Optional[str] = None
    message: str
    agent: Optional[str] = None
    files: Optional[list[str]] = None
    conversationId: Optional[str] = None
    fromAgent: Optional[str] = None


class EnqueueResponseRequest(BaseModel):
    messageId: str
    channel: str
    sender: str
    senderId: Optional[str] = None
    message: str
    originalMessage: str
    agent: Optional[str] = None
    files: Optional[list[str]] = None
    metadata: Optional[dict] = None


class FailMessageRequest(BaseModel):
    error: str


class QueueStatusResponse(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    dead: int = 0
    responsesPending: int = 0


class AgentQueueStatusResponse(BaseModel):
    agent: str
    pending: int = 0
    queued: int = 0
    processing: int = 0
