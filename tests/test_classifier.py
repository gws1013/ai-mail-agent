"""Tests for the classifier agent."""

import json
import pytest
from unittest.mock import patch, MagicMock
from src.graph.state import MailInput, ClassificationResult
from src.agents.classifier import ClassifierAgent


@pytest.fixture
def sample_emails():
    """Load sample emails from fixtures."""
    from pathlib import Path
    fixtures_path = Path(__file__).parent / "fixtures" / "sample_emails.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def classifier():
    """Create a classifier with mocked LLM."""
    return ClassifierAgent(api_key="test-key")


class TestClassifierAgent:
    """Tests for ClassifierAgent."""

    def test_mail_input_parsing(self, sample_emails):
        """Test that sample emails can be parsed into MailInput."""
        for email_data in sample_emails:
            mail_input = MailInput(**email_data)
            assert mail_input.subject
            assert mail_input.sender
            assert mail_input.body

    @patch("src.agents.classifier.ChatOpenAI")
    def test_classify_tech_question(self, mock_chat_class, sample_emails):
        """Test classification of a tech question email."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "category": "tech_question",
                "confidence": 0.95,
                "reasoning": "The email asks about Python FastAPI async patterns",
                "priority": "medium",
            })
        )
        mock_chat_class.return_value = mock_llm

        classifier = ClassifierAgent(api_key="test-key")
        mail_input = MailInput(**sample_emails[0])
        result = classifier.classify(mail_input)

        assert isinstance(result, ClassificationResult)
        assert result.category == "tech_question"
        assert result.confidence > 0.8

    @patch("src.agents.classifier.ChatOpenAI")
    def test_classify_spam(self, mock_chat_class, sample_emails):
        """Test classification of spam email."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "category": "spam",
                "confidence": 0.99,
                "reasoning": "Marketing promotional email",
                "priority": "low",
            })
        )
        mock_chat_class.return_value = mock_llm

        classifier = ClassifierAgent(api_key="test-key")
        mail_input = MailInput(**sample_emails[2])
        result = classifier.classify(mail_input)

        assert result.category == "spam"
        assert result.confidence > 0.9


class TestClassificationResult:
    """Tests for ClassificationResult model."""

    def test_valid_result(self):
        result = ClassificationResult(
            category="tech_question",
            confidence=0.95,
            reasoning="Technical question about Python",
            priority="medium",
        )
        assert result.category == "tech_question"

    def test_invalid_category(self):
        with pytest.raises(Exception):
            ClassificationResult(
                category="invalid_category",
                confidence=0.95,
                reasoning="test",
                priority="medium",
            )
