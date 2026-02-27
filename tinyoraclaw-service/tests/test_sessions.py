"""Tests for session models and SessionService basic behavior."""

import pytest

from tinyoraclaw_service.models.sessions import SaveSessionRequest, SessionResponse


class TestSaveSessionRequest:
    def test_minimal_request(self):
        req = SaveSessionRequest(teamId="team-1", history="some history")
        assert req.teamId == "team-1"
        assert req.agentId == "default"
        assert req.sessionId is None
        assert req.history == "some history"
        assert req.channel is None
        assert req.label is None

    def test_full_request(self):
        req = SaveSessionRequest(
            teamId="team-2",
            agentId="agent-x",
            sessionId="sess-123",
            history='{"messages": []}',
            channel="discord",
            label="Test Session",
        )
        assert req.teamId == "team-2"
        assert req.agentId == "agent-x"
        assert req.sessionId == "sess-123"
        assert req.history == '{"messages": []}'
        assert req.channel == "discord"
        assert req.label == "Test Session"

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            SaveSessionRequest()

    def test_missing_history(self):
        with pytest.raises(Exception):
            SaveSessionRequest(teamId="team-1")


class TestSessionResponse:
    def test_full_response(self):
        resp = SessionResponse(
            session_key="team-1_default_1234567890",
            session_id="uuid-1234",
            team_id="team-1",
            agent_id="default",
            updated_at=1234567890,
            session_data='{"messages": []}',
            channel="slack",
            label="My Session",
        )
        assert resp.session_key == "team-1_default_1234567890"
        assert resp.session_id == "uuid-1234"
        assert resp.team_id == "team-1"
        assert resp.agent_id == "default"
        assert resp.updated_at == 1234567890
        assert resp.session_data == '{"messages": []}'
        assert resp.channel == "slack"
        assert resp.label == "My Session"

    def test_minimal_response(self):
        resp = SessionResponse(
            session_key="key-1",
            session_id="sid-1",
            team_id="team-1",
            agent_id="default",
            updated_at=1000,
        )
        assert resp.session_data is None
        assert resp.channel is None
        assert resp.label is None

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            SessionResponse(session_key="key-1")
