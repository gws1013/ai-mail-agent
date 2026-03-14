"""Reviewer agent — quality-gates a draft before it is sent."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import DraftResult, MailInput, ReviewResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ReviewerAgent:
    """Review a draft email and decide whether it is safe to send.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-5-nano",
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=1024,
        )
        self._prompt_path = _PROMPTS_DIR / "reviewer.txt"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(self, mail_input: MailInput, draft: DraftResult) -> ReviewResult:
        """Review *draft* against the original *mail_input*.

        Business rule: if the LLM flags ``contains_sensitive_info=True``,
        ``approved`` is forced to ``False`` regardless of the model's
        ``approved`` field.

        Returns
        -------
        ReviewResult
            The review outcome.  Falls back to a rejected result with an
            error issue when the LLM call or parsing fails.
        """
        try:
            result = self._call_llm_and_parse(mail_input, draft)
        except Exception:
            logger.exception(
                "ReviewerAgent.review failed for message_id=%s",
                mail_input.message_id,
            )
            return ReviewResult(
                approved=False,
                issues=["Review failed due to an unexpected error."],
                technical_accuracy=0.0,
                tone_appropriate=False,
                contains_sensitive_info=False,
                revised_body=None,
            )

        # Enforce the sensitive-info safety rule.
        if result.contains_sensitive_info:
            logger.warning(
                "ReviewerAgent: sensitive info detected in draft for "
                "message_id=%s — forcing approved=False",
                mail_input.message_id,
            )
            result = ReviewResult(
                approved=False,
                issues=result.issues
                + ["Draft contains sensitive or confidential information."],
                technical_accuracy=result.technical_accuracy,
                tone_appropriate=result.tone_appropriate,
                contains_sensitive_info=True,
                revised_body=result.revised_body,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm_and_parse(
        self,
        mail_input: MailInput,
        draft: DraftResult,
    ) -> ReviewResult:
        """Build the reviewer prompt, call the LLM, and parse the JSON response."""
        template = self._prompt_path.read_text(encoding="utf-8")

        prompt_text = template.format(
            original_subject=mail_input.subject,
            sender=mail_input.sender,
            original_body=mail_input.body,
            draft_body=draft.body,
        )

        for attempt in range(3):
            response = self._llm.invoke([HumanMessage(content=prompt_text)])
            raw = str(response.content).strip()
            if raw:
                break
            logger.warning(
                "ReviewerAgent: empty response (attempt %d/3)", attempt + 1,
            )
        else:
            raise ValueError("LLM returned empty response after 3 attempts")

        # Strip optional markdown fences.
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("ReviewerAgent: JSON parse error: %s", exc)
            raise

        return ReviewResult(
            approved=bool(data["approved"]),
            issues=list(data.get("issues", [])),
            technical_accuracy=float(data.get("technical_accuracy", 0.0)),
            tone_appropriate=bool(data.get("tone_appropriate", False)),
            contains_sensitive_info=bool(data.get("contains_sensitive_info", False)),
            revised_body=data.get("revised_body"),
        )
