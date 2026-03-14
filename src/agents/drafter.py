"""Drafter agent — generates a reply draft from analysis results."""

from __future__ import annotations

import logging
from pathlib import Path

import markdown as md
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.graph.state import AnalysisResult, DraftResult, MailInput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_SELF_ASSESS_SYSTEM = """\
You are evaluating the quality of an email draft you just wrote.
Return a JSON object with exactly two fields:
{
    "confidence": <float 0.0-1.0>,
    "tone_check": "<one short phrase describing the tone>"
}
Return ONLY the JSON — no markdown fences, no preamble.
"""


class DrafterAgent:
    """Generate a reply email draft.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-5-nano",
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.3,
            max_tokens=2048,
        )
        self._llm_json = ChatOpenAI(
            model="gpt-5-nano",
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=256,
        )
        self._prompt_path = _PROMPTS_DIR / "drafter.txt"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draft(
        self,
        mail_input: MailInput,
        analysis: AnalysisResult,
        feedback: str | None = None,
    ) -> DraftResult:
        """Generate a reply draft.

        Parameters
        ----------
        mail_input:
            The original incoming email.
        analysis:
            Structured analysis produced by :class:`AnalyzerAgent`.
        feedback:
            Optional plain-text feedback from a previous reviewer rejection.
            When provided it is prepended to the prompt as an additional
            instruction so the drafter can correct the earlier attempt.

        Returns
        -------
        DraftResult
            The completed draft including plain-text and HTML bodies plus a
            self-assessed confidence and tone label.
        """
        try:
            body_text = self._generate_body(mail_input, analysis, feedback)
        except Exception:
            logger.exception(
                "DrafterAgent.draft LLM call failed for message_id=%s",
                mail_input.message_id,
            )
            body_text = (
                "I apologize, but I was unable to generate a reply at this time. "
                "Please review this email manually."
            )

        body_html = md.markdown(body_text, extensions=["fenced_code", "tables"])

        confidence, tone_check = self._self_assess(
            mail_input=mail_input,
            analysis=analysis,
            draft_body=body_text,
        )

        return DraftResult(
            subject=f"Re: {mail_input.subject}",
            body=body_text,
            body_html=body_html,
            confidence=confidence,
            tone_check=tone_check,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_body(
        self,
        mail_input: MailInput,
        analysis: AnalysisResult,
        feedback: str | None,
    ) -> str:
        """Build the prompt and call the LLM; return the raw text response."""
        template = self._prompt_path.read_text(encoding="utf-8")

        user_prompt = template.format(
            tech_stack=", ".join(analysis.tech_stack) if analysis.tech_stack else "N/A",
            core_questions="\n".join(
                f"- {q}" for q in analysis.core_questions
            ) if analysis.core_questions else "N/A",
            related_context="\n".join(
                f"- {c}" for c in analysis.related_context
            ) if analysis.related_context else "N/A",
            suggested_approach=analysis.suggested_approach or "N/A",
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body,
        )

        messages: list = []

        if feedback:
            feedback_instruction = (
                "IMPORTANT — Previous draft was rejected by the reviewer with "
                f"the following feedback. Please address ALL points:\n\n{feedback}\n\n"
                "Now write an improved reply that fixes these issues."
            )
            messages.append(SystemMessage(content=feedback_instruction))

        messages.append(HumanMessage(content=user_prompt))

        response = self._llm.invoke(messages)
        return str(response.content).strip()

    def _self_assess(
        self,
        mail_input: MailInput,
        analysis: AnalysisResult,
        draft_body: str,
    ) -> tuple[float, str]:
        """Ask the LLM to self-assess the draft's quality and tone.

        Returns a ``(confidence, tone_check)`` tuple. Falls back to safe
        defaults on any error.
        """
        import json  # local import — only needed here

        user_content = (
            f"Original email subject: {mail_input.subject}\n"
            f"Core questions addressed:\n"
            + (
                "\n".join(f"- {q}" for q in analysis.core_questions)
                if analysis.core_questions
                else "(none extracted)"
            )
            + f"\n\nDraft reply:\n{draft_body}"
        )

        try:
            response = self._llm_json.invoke(
                [
                    SystemMessage(content=_SELF_ASSESS_SYSTEM),
                    HumanMessage(content=user_content),
                ]
            )
            raw = str(response.content).strip()

            if raw.startswith("```"):
                lines = raw.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                raw = "\n".join(inner).strip()

            data: dict = json.loads(raw)
            confidence = float(data.get("confidence", 0.7))
            tone_check = str(data.get("tone_check", "professional"))
            # Clamp confidence to [0, 1].
            confidence = max(0.0, min(1.0, confidence))
            return confidence, tone_check

        except Exception:
            logger.exception(
                "DrafterAgent._self_assess failed for message_id=%s",
                mail_input.message_id,
            )
            return 0.7, "professional"
