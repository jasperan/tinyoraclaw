"""Tests for transcript models and TranscriptService basic behavior."""

import pytest

from tinyoraclaw_service.models.transcripts import LogTranscriptRequest


class TestLogTranscriptRequest:
    def test_minimal_request(self):
        req = LogTranscriptRequest(content="Hello, world!")
        assert req.agentId == "default"
        assert req.teamId is None
        assert req.sessionId is None
        assert req.channel is None
        assert req.role is None
        assert req.eventType == "message"
        assert req.content == "Hello, world!"

    def test_full_request(self):
        req = LogTranscriptRequest(
            agentId="agent-1",
            teamId="team-1",
            sessionId="sess-abc",
            channel="discord",
            role="user",
            eventType="tool_call",
            content="Running search...",
        )
        assert req.agentId == "agent-1"
        assert req.teamId == "team-1"
        assert req.sessionId == "sess-abc"
        assert req.channel == "discord"
        assert req.role == "user"
        assert req.eventType == "tool_call"
        assert req.content == "Running search..."

    def test_missing_content(self):
        with pytest.raises(Exception):
            LogTranscriptRequest()

    def test_default_event_type(self):
        req = LogTranscriptRequest(content="test")
        assert req.eventType == "message"

    def test_custom_event_type(self):
        req = LogTranscriptRequest(content="test", eventType="function_call")
        assert req.eventType == "function_call"

    def test_all_optional_fields_none(self):
        req = LogTranscriptRequest(content="just content")
        assert req.teamId is None
        assert req.sessionId is None
        assert req.channel is None
        assert req.role is None
