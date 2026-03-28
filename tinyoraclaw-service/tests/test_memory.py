"""Tests for memory models and API endpoints."""

import pytest
from pydantic import ValidationError

from tinyoraclaw_service.models.memory import RememberRequest, RecallRequest


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


class TestRememberRequest:
    def test_valid_defaults(self):
        req = RememberRequest(text="hello world")
        assert req.text == "hello world"
        assert req.agent_id == "default"
        assert req.importance == 0.7
        assert req.category == "other"

    def test_custom_fields(self):
        req = RememberRequest(
            text="important fact",
            agent_id="agent-1",
            importance=0.95,
            category="knowledge",
        )
        assert req.text == "important fact"
        assert req.agent_id == "agent-1"
        assert req.importance == 0.95
        assert req.category == "knowledge"

    def test_missing_text_raises(self):
        with pytest.raises(ValidationError):
            RememberRequest()

    def test_empty_text_allowed(self):
        req = RememberRequest(text="")
        assert req.text == ""


class TestRecallRequest:
    def test_valid_defaults(self):
        req = RecallRequest(query="what do you know?")
        assert req.query == "what do you know?"
        assert req.agent_id == "default"
        assert req.max_results == 5
        assert req.min_score == 0.3

    def test_custom_fields(self):
        req = RecallRequest(
            query="recent events",
            agent_id="agent-2",
            max_results=10,
            min_score=0.5,
        )
        assert req.query == "recent events"
        assert req.agent_id == "agent-2"
        assert req.max_results == 10
        assert req.min_score == 0.5

    def test_missing_query_raises(self):
        with pytest.raises(ValidationError):
            RecallRequest()

    def test_serialization_roundtrip(self):
        req = RememberRequest(text="test", agent_id="a1", importance=0.8, category="fact")
        data = req.model_dump()
        assert data == {
            "text": "test",
            "agent_id": "a1",
            "importance": 0.8,
            "category": "fact",
        }
        restored = RememberRequest(**data)
        assert restored == req


# ---------------------------------------------------------------------------
# API endpoint tests (mock-based, no real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_endpoints_503_without_service(client_no_db):
    """Memory endpoints should return 503 when memory_service is None."""
    resp = await client_no_db.post("/api/memory/remember", json={"text": "hello"})
    assert resp.status_code == 503

    resp = await client_no_db.post("/api/memory/recall", json={"query": "hello"})
    assert resp.status_code == 503

    resp = await client_no_db.delete("/api/memory/forget/some-id")
    assert resp.status_code == 503

    resp = await client_no_db.get("/api/memory/count")
    assert resp.status_code == 503

    resp = await client_no_db.get("/api/memory/status")
    assert resp.status_code == 503
