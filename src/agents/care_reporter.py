"""Care reporter agent — generates life record reports for guardians."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import CareReportResult, MailInput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class CareReporterAgent:
    """Generate care record reports for guardians.

    Args:
        api_key: OpenAI API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.3,
            max_tokens=4096,
        )
        self._prompt_path = _PROMPTS_DIR / "care_reporter.txt"

    def draft_report(
        self,
        mail_input: MailInput,
        care_data: list[str],
    ) -> CareReportResult:
        """Draft a care record report.

        Args:
            mail_input: Parsed email input.
            care_data: Relevant care record passages from RAG.

        Returns:
            CareReportResult with report body.
        """
        try:
            return self._call_llm(mail_input, care_data)
        except Exception:
            logger.exception(
                "CareReporter failed for message_id=%s", mail_input.message_id
            )
            return CareReportResult(
                body="생활기록 보고서 작성 중 오류가 발생했습니다.",
            )

    def _call_llm(
        self,
        mail_input: MailInput,
        care_data: list[str],
    ) -> CareReportResult:
        """Build prompt and call LLM for care report."""
        template = self._prompt_path.read_text(encoding="utf-8")
        care_text = "\n\n".join(
            f"--- 기록 {i+1} ---\n{d}" for i, d in enumerate(care_data)
        ) if care_data else "(해당 생활기록 데이터 없음)"

        prompt_text = template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body[:2000],
            care_data=care_text,
        )

        response = self._llm.invoke([HumanMessage(content=prompt_text)])
        raw = str(response.content).strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        data = json.loads(raw)
        return CareReportResult(
            body=data.get("body", ""),
            patient_name=data.get("patient_name", ""),
            guardian_name=data.get("guardian_name", ""),
            period=data.get("period", ""),
        )
