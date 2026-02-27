"""Unit tests for queue Pydantic models."""

import pytest
from pydantic import ValidationError

from tinyoraclaw_service.models.queue import (
    EnqueueMessageRequest,
    EnqueueResponseRequest,
    QueueStatusResponse,
)


class TestEnqueueMessageRequest:
    def test_valid_minimal(self):
        data = EnqueueMessageRequest(
            messageId="msg-001",
            channel="discord",
            sender="alice",
            message="Hello world",
        )
        assert data.messageId == "msg-001"
        assert data.channel == "discord"
        assert data.sender == "alice"
        assert data.message == "Hello world"
        assert data.senderId is None
        assert data.agent is None
        assert data.files is None
        assert data.conversationId is None
        assert data.fromAgent is None

    def test_valid_full(self):
        data = EnqueueMessageRequest(
            messageId="msg-002",
            channel="slack",
            sender="bob",
            senderId="U12345",
            message="Hi there",
            agent="coder",
            files=["file1.txt", "file2.py"],
            conversationId="conv-abc",
            fromAgent="router",
        )
        assert data.senderId == "U12345"
        assert data.agent == "coder"
        assert data.files == ["file1.txt", "file2.py"]
        assert data.conversationId == "conv-abc"
        assert data.fromAgent == "router"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            EnqueueMessageRequest(
                messageId="msg-003",
                channel="discord",
                # missing sender and message
            )

    def test_missing_message_id(self):
        with pytest.raises(ValidationError):
            EnqueueMessageRequest(
                channel="discord",
                sender="alice",
                message="Hello",
            )


class TestEnqueueResponseRequest:
    def test_valid_minimal(self):
        data = EnqueueResponseRequest(
            messageId="msg-001",
            channel="discord",
            sender="bot",
            message="Reply here",
            originalMessage="Hello world",
        )
        assert data.messageId == "msg-001"
        assert data.channel == "discord"
        assert data.sender == "bot"
        assert data.message == "Reply here"
        assert data.originalMessage == "Hello world"
        assert data.senderId is None
        assert data.agent is None
        assert data.files is None

    def test_valid_full(self):
        data = EnqueueResponseRequest(
            messageId="msg-002",
            channel="slack",
            sender="bot",
            senderId="B99999",
            message="Done!",
            originalMessage="Do something",
            agent="coder",
            files=["output.log"],
        )
        assert data.senderId == "B99999"
        assert data.agent == "coder"
        assert data.files == ["output.log"]

    def test_missing_original_message(self):
        with pytest.raises(ValidationError):
            EnqueueResponseRequest(
                messageId="msg-003",
                channel="discord",
                sender="bot",
                message="Reply",
                # missing originalMessage
            )


class TestQueueStatusResponse:
    def test_defaults(self):
        status = QueueStatusResponse()
        assert status.pending == 0
        assert status.processing == 0
        assert status.completed == 0
        assert status.dead == 0
        assert status.responsesPending == 0

    def test_custom_values(self):
        status = QueueStatusResponse(
            pending=5,
            processing=2,
            completed=100,
            dead=1,
            responsesPending=3,
        )
        assert status.pending == 5
        assert status.processing == 2
        assert status.completed == 100
        assert status.dead == 1
        assert status.responsesPending == 3
