"""Classifier agent — categorises incoming emails with softmax probabilities."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import ClassificationResult, MailInput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

CATEGORIES = [
    "signature_request",
    "contract_inquiry",
    "care_record",
    "reservation",
    "spam_or_other",
]


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    """Apply softmax to raw scores and return probability distribution.

    Args:
        scores: Raw scores per category (0-100 scale).

    Returns:
        Normalised probability distribution.
    """
    values = [scores.get(c, 0.0) for c in CATEGORIES]
    max_val = max(values)
    exps = [math.exp(v - max_val) for v in values]
    total = sum(exps)
    return {c: round(e / total, 4) for c, e in zip(CATEGORIES, exps)}


class ClassifierAgent:
    """Classify incoming emails into 5 categories using softmax probabilities.

    Args:
        api_key: OpenAI API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.0,
            max_tokens=2048,
        )
        self._prompt_path = _PROMPTS_DIR / "classifier.txt"

    def classify(self, mail_input: MailInput) -> ClassificationResult:
        """Classify an email and return softmax probabilities.

        Args:
            mail_input: Parsed email input.

        Returns:
            ClassificationResult with category and probability distribution.
        """
        try:
            return self._call_llm(mail_input)
        except Exception:
            logger.exception(
                "Classifier failed for message_id=%s", mail_input.message_id
            )
            return ClassificationResult(
                category="spam_or_other",
                probabilities={c: 0.2 for c in CATEGORIES},
                reasoning="분류 실패 — 기본값 반환",
            )

    def _call_llm(self, mail_input: MailInput) -> ClassificationResult:
        """Build prompt, call LLM, parse response with softmax."""
        template = self._prompt_path.read_text(encoding="utf-8")
        prompt_text = template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body[:2000],
            has_attachments="있음" if mail_input.has_attachments else "없음",
        )

        for attempt in range(3):
            response = self._llm.invoke([HumanMessage(content=prompt_text)])
            raw = str(response.content).strip()

            if not raw:
                logger.warning("Classifier: attempt %d/3 — empty response", attempt + 1)
                continue

            # Strip markdown fences
            if raw.startswith("```"):
                lines = raw.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                raw = "\n".join(inner).strip()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Classifier: JSON parse error: %s", exc)
                continue

            raw_scores = data.get("scores", {})
            probabilities = _softmax(raw_scores)
            category = data.get("category", "spam_or_other")

            # Log softmax probabilities
            prob_str = " | ".join(
                f"{c}: {probabilities.get(c, 0):.2%}" for c in CATEGORIES
            )
            logger.info("Classifier softmax: %s → %s", prob_str, category)

            return ClassificationResult(
                category=category,
                probabilities=probabilities,
                reasoning=data.get("reasoning", ""),
            )

        raise ValueError("Classifier: LLM returned no valid response after 3 attempts")
