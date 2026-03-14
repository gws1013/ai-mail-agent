"""Classifier agent — assigns a category and priority to an incoming email."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import ClassificationResult, MailInput

logger = logging.getLogger(__name__)

# Absolute path to the prompts directory, resolved relative to this file's
# location so it works regardless of the current working directory.
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ClassifierAgent:
    """Classify an incoming email into a category with confidence and priority.

    Parameters
    ----------
    api_key:
        Anthropic API key forwarded to :class:`ChatAnthropic`.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-5-nano",
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=512,
        )
        self._prompt_path = _PROMPTS_DIR / "classifier.txt"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, mail_input: MailInput) -> ClassificationResult:
        """Classify *mail_input* and return a :class:`ClassificationResult`.

        If the LLM call fails or the response cannot be parsed, a safe
        ``needs_human`` result with low confidence is returned so the pipeline
        can degrade gracefully.
        """
        try:
            prompt_text = self._load_prompt(mail_input)
            # Retry up to 2 times on empty responses from gpt-5-nano
            for attempt in range(3):
                response = self._llm.invoke([HumanMessage(content=prompt_text)])
                raw = str(response.content).strip()
                if raw:
                    return self._parse_response(raw)
                logger.warning(
                    "ClassifierAgent: empty response (attempt %d/3) for message_id=%s",
                    attempt + 1, mail_input.message_id,
                )
            raise ValueError("LLM returned empty response after 3 attempts")
        except Exception:
            logger.exception(
                "ClassifierAgent.classify failed for message_id=%s — "
                "falling back to needs_human",
                mail_input.message_id,
            )
            return ClassificationResult(
                category="needs_human",
                confidence=0.0,
                reasoning="Classification failed due to an unexpected error.",
                priority="medium",
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_prompt(self, mail_input: MailInput) -> str:
        """Read the classifier prompt template and format it with *mail_input*."""
        template = self._prompt_path.read_text(encoding="utf-8")
        return template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body,
        )

    def _parse_response(self, content: str) -> ClassificationResult:
        """Parse the LLM text response into a :class:`ClassificationResult`.

        The model is instructed to return JSON, but it occasionally wraps the
        JSON block in markdown fences — this method handles both cases.
        """
        # Strip optional ```json … ``` fences.
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Drop the opening fence (```json or ```) and the closing fence.
            inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            stripped = "\n".join(inner_lines).strip()

        try:
            data: dict = json.loads(stripped)
        except json.JSONDecodeError as exc:
            logger.warning("ClassifierAgent: JSON parse error: %s", exc)
            raise

        return ClassificationResult(
            category=data["category"],
            confidence=float(data["confidence"]),
            reasoning=data.get("reasoning", ""),
            priority=data["priority"],
        )
