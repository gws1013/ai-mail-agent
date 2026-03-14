"""Tests for the drafter agent."""

import json
import pytest
from unittest.mock import patch, MagicMock
from src.graph.state import MailInput, AnalysisResult, DraftResult
from src.agents.drafter import DrafterAgent


@pytest.fixture
def drafter():
    return DrafterAgent(api_key="test-key")


@pytest.fixture
def sample_mail_input():
    return MailInput(
        message_id="msg_001",
        thread_id="thread_001",
        subject="Python FastAPI async question",
        sender="junior@company.com",
        body="Should I use async def or def in FastAPI with sync ORM?",
        has_attachments=False,
        received_at="2026-03-13T10:00:00Z",
    )


@pytest.fixture
def sample_analysis():
    return AnalysisResult(
        tech_stack=["Python", "FastAPI"],
        core_questions=["async vs sync endpoint with synchronous ORM"],
        related_context=[],
        code_snippets=[],
        suggested_approach="Explain that sync ORM in async endpoint blocks the event loop",
    )


class TestDrafterAgent:
    @patch("src.agents.drafter.ChatOpenAI")
    def test_draft_creates_reply(self, mock_chat_class, sample_mail_input, sample_analysis):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="Use `def` instead of `async def` when calling synchronous ORMs in FastAPI. "
                    "When you use `async def`, the synchronous ORM call blocks the entire event loop."
        )
        mock_chat_class.return_value = mock_llm

        drafter = DrafterAgent(api_key="test-key")
        result = drafter.draft(sample_mail_input, sample_analysis)

        assert isinstance(result, DraftResult)
        assert "Re:" in result.subject
        assert len(result.body) > 0
        assert len(result.body_html) > 0

    @patch("src.agents.drafter.ChatOpenAI")
    def test_draft_with_feedback(self, mock_chat_class, sample_mail_input, sample_analysis):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="Revised answer with more detail about thread pools."
        )
        mock_chat_class.return_value = mock_llm

        drafter = DrafterAgent(api_key="test-key")
        result = drafter.draft(
            sample_mail_input, sample_analysis,
            feedback="Need more detail about thread pool executor"
        )

        assert isinstance(result, DraftResult)
