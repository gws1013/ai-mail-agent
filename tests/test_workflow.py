"""Tests for the LangGraph workflow."""

import json
import pytest
from unittest.mock import patch, MagicMock
from src.graph.state import AgentState


@pytest.fixture
def sample_state():
    """Create a sample initial state."""
    return AgentState(
        raw_email={
            "message_id": "msg_001",
            "thread_id": "thread_001",
            "subject": "Python question",
            "sender": "dev@company.com",
            "body": "How do I use async in FastAPI?",
            "has_attachments": False,
            "received_at": "2026-03-13T10:00:00Z",
        },
        classification=None,
        analysis=None,
        draft=None,
        review=None,
        current_step="start",
        retry_count=0,
        error=None,
        final_action="",
    )


class TestWorkflowRouting:
    """Tests for workflow routing logic."""

    def test_route_spam_to_skip(self):
        from src.graph.workflow import route_after_classify
        state = {
            "classification": {"category": "spam", "confidence": 0.99},
        }
        assert route_after_classify(state) == "skip"

    def test_route_needs_human_to_escalate(self):
        from src.graph.workflow import route_after_classify
        state = {
            "classification": {"category": "needs_human", "confidence": 0.5},
        }
        assert route_after_classify(state) == "escalate"

    @patch("src.graph.workflow.get_settings")
    def test_route_low_confidence_to_escalate(self, mock_settings):
        mock_settings.return_value.AUTO_SEND_THRESHOLD = 0.8
        from src.graph.workflow import route_after_classify
        state = {
            "classification": {"category": "tech_question", "confidence": 0.5},
        }
        assert route_after_classify(state) == "escalate"

    @patch("src.graph.workflow.get_settings")
    def test_route_high_confidence_to_analyze(self, mock_settings):
        mock_settings.return_value.AUTO_SEND_THRESHOLD = 0.8
        from src.graph.workflow import route_after_classify
        state = {
            "classification": {"category": "tech_question", "confidence": 0.95},
        }
        assert route_after_classify(state) == "analyze"

    def test_route_approved_review_to_send(self):
        from src.graph.workflow import route_after_review
        state = {
            "review": {"approved": True},
            "retry_count": 0,
        }
        assert route_after_review(state) == "send"

    @patch("src.graph.workflow.get_settings")
    def test_route_rejected_review_to_redraft(self, mock_settings):
        mock_settings.return_value.MAX_RETRY_COUNT = 2
        from src.graph.workflow import route_after_review
        state = {
            "review": {"approved": False},
            "retry_count": 0,
        }
        assert route_after_review(state) == "redraft"

    @patch("src.graph.workflow.get_settings")
    def test_route_max_retries_to_escalate(self, mock_settings):
        mock_settings.return_value.MAX_RETRY_COUNT = 2
        from src.graph.workflow import route_after_review
        state = {
            "review": {"approved": False},
            "retry_count": 2,
        }
        assert route_after_review(state) == "escalate"
