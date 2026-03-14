"""Analyzer agent — deep-dives into an email to extract technical context."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.graph.state import AnalysisResult, ClassificationResult, MailInput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# ---------------------------------------------------------------------------
# ContextRetriever protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ContextRetriever(Protocol):
    """Minimal interface for a RAG retriever.

    Any object that exposes a ``retrieve(query: str) -> list[str]`` method
    satisfies this protocol; the concrete implementation lives in
    ``src.rag.retriever``.
    """

    def retrieve(self, query: str) -> list[str]:
        """Return a list of relevant text passages for *query*."""
        ...


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior software developer analyzing a technical email.
Your task is to extract structured information to help draft a reply.

Analyze the email thoroughly and return a JSON object with these exact fields:
{
    "tech_stack": ["list", "of", "technologies", "mentioned"],
    "core_questions": ["discrete question or ask 1", "discrete question or ask 2"],
    "suggested_approach": "High-level strategy for replying to this email"
}

Rules:
- tech_stack: include languages, frameworks, libraries, tools, cloud services, DBs
- core_questions: each item must be a single, self-contained question or request
- suggested_approach: 1-3 sentences describing what a great reply should cover
- Return ONLY the JSON object — no markdown fences, no preamble
"""


class AnalyzerAgent:
    """Perform deep analysis of an incoming email.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    retriever:
        A :class:`ContextRetriever`-compatible object used to fetch related
        knowledge-base passages.
    """

    def __init__(self, api_key: str, retriever: ContextRetriever) -> None:
        self._llm = ChatOpenAI(
            model="gpt-5-nano",
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=1024,
        )
        self._retriever = retriever

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        mail_input: MailInput,
        classification: ClassificationResult,
    ) -> AnalysisResult:
        """Analyze *mail_input* in the context of *classification*.

        Returns a fully-populated :class:`AnalysisResult`, falling back to
        sensible defaults if any step fails.
        """
        # 1. Extract code snippets locally (no LLM needed).
        code_snippets = self._extract_code_snippets(mail_input.body)

        # 2. Build a retrieval query from subject + category + first 500 chars.
        retrieval_query = (
            f"{mail_input.subject} {classification.category} "
            f"{mail_input.body[:500]}"
        )
        related_context: list[str] = []
        try:
            related_context = self._retriever.retrieve(retrieval_query)
        except Exception:
            logger.exception(
                "AnalyzerAgent: retriever failed for message_id=%s",
                mail_input.message_id,
            )

        # 3. Call the LLM for structured analysis.
        try:
            llm_result = self._call_llm(mail_input, related_context)
        except Exception:
            logger.exception(
                "AnalyzerAgent.analyze LLM call failed for message_id=%s",
                mail_input.message_id,
            )
            llm_result = {
                "tech_stack": [],
                "core_questions": [],
                "suggested_approach": "",
            }

        return AnalysisResult(
            tech_stack=llm_result.get("tech_stack", []),
            core_questions=llm_result.get("core_questions", []),
            related_context=related_context,
            code_snippets=code_snippets,
            suggested_approach=llm_result.get("suggested_approach", ""),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        mail_input: MailInput,
        related_context: list[str],
    ) -> dict:
        """Invoke the LLM and parse the JSON response."""
        context_block = (
            "\n".join(f"- {c}" for c in related_context)
            if related_context
            else "(none)"
        )
        user_content = (
            f"Subject: {mail_input.subject}\n"
            f"From: {mail_input.sender}\n"
            f"Has attachments: {mail_input.has_attachments}\n\n"
            f"Body:\n{mail_input.body}\n\n"
            f"Related knowledge-base context:\n{context_block}"
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
        for attempt in range(3):
            response = self._llm.invoke(messages)
            raw = str(response.content).strip()
            if raw:
                break
            logger.warning(
                "AnalyzerAgent: empty response (attempt %d/3)", attempt + 1,
            )
        else:
            raise ValueError("LLM returned empty response after 3 attempts")

        # Handle optional markdown fences.
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        return json.loads(raw)  # type: ignore[return-value]

    def _extract_code_snippets(self, body: str) -> list[str]:
        """Extract code blocks from *body*.

        Detects:
        * Fenced blocks: triple-backtick (with optional language tag)
        * Indented blocks: 4-space or tab-indented consecutive lines
        """
        snippets: list[str] = []

        # 1. Triple-backtick fences: ```[lang]\\n...\\n```
        fenced_pattern = re.compile(
            r"```(?:[^\n]*)?\n(.*?)```",
            re.DOTALL,
        )
        for match in fenced_pattern.finditer(body):
            code = match.group(1).rstrip()
            if code:
                snippets.append(code)

        # 2. Indented blocks (4 spaces or a tab), only when no fenced blocks
        #    were found to avoid double-capturing.
        if not snippets:
            indented_pattern = re.compile(
                r"(?m)^(?:    |\t).*(?:\n(?:    |\t).*)*"
            )
            for match in indented_pattern.finditer(body):
                code = match.group(0)
                # Dedent by removing the leading 4-space / tab prefix.
                dedented = re.sub(r"(?m)^(?:    |\t)", "", code).rstrip()
                if dedented:
                    snippets.append(dedented)

        return snippets
