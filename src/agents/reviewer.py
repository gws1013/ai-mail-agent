"""Reviewer agent — quality-gates a draft before sending."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import MailInput, ReviewResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ReviewerAgent:
    """Review a draft reply for quality, accuracy, and safety.

    Args:
        api_key: OpenAI API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.0,
            max_tokens=4096,
        )
        self._prompt_path = _PROMPTS_DIR / "reviewer.txt"

    def review(self, mail_input: MailInput, draft_body: str) -> ReviewResult:
        """Review a draft reply.

        If sensitive info is detected, approval is forced to False.

        Args:
            mail_input: Original email.
            draft_body: Draft reply text.

        Returns:
            ReviewResult with approval status.
        """
        try:
            result = self._call_llm(mail_input, draft_body)
        except Exception:
            logger.exception(
                "Reviewer failed for message_id=%s", mail_input.message_id
            )
            return ReviewResult(
                approved=False,
                issues=["리뷰 처리 중 오류 발생"],
            )

        # Force reject if sensitive info detected
        if result.contains_sensitive_info:
            logger.warning(
                "Reviewer: sensitive info detected — forcing rejection"
            )
            result = ReviewResult(
                approved=False,
                issues=result.issues + ["민감한 개인정보가 포함되어 있습니다."],
                tone_appropriate=result.tone_appropriate,
                contains_sensitive_info=True,
                revised_body=result.revised_body,
            )

        return result

    def _call_llm(self, mail_input: MailInput, draft_body: str) -> ReviewResult:
        """Build prompt and call LLM for review."""
        template = self._prompt_path.read_text(encoding="utf-8")
        prompt_text = template.format(
            original_subject=mail_input.subject,
            sender=mail_input.sender,
            original_body=mail_input.body[:2000],
            draft_body=draft_body,
        )

        for attempt in range(3):
            response = self._llm.invoke([HumanMessage(content=prompt_text)])
            raw = str(response.content).strip()

            if not raw:
                logger.warning("Reviewer: attempt %d/3 — empty response", attempt + 1)
                continue

            if raw.startswith("```"):
                lines = raw.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                raw = "\n".join(inner).strip()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Reviewer: JSON parse error on attempt %d", attempt + 1)
                continue

            return ReviewResult(
                approved=bool(data.get("approved", False)),
                issues=list(data.get("issues", [])),
                tone_appropriate=bool(data.get("tone_appropriate", True)),
                contains_sensitive_info=bool(data.get("contains_sensitive_info", False)),
                revised_body=data.get("revised_body"),
            )

        raise ValueError("Reviewer: no valid response after 3 attempts")
