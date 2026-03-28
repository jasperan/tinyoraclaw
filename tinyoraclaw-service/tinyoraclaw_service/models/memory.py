from pydantic import BaseModel
from typing import Optional


class RememberRequest(BaseModel):
    text: str
    agent_id: str = "default"
    importance: float = 0.7
    category: str = "other"


class RecallRequest(BaseModel):
    query: str
    agent_id: str = "default"
    max_results: int = 5
    min_score: float = 0.3
