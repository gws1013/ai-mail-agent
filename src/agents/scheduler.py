"""Scheduler agent — handles reservation and visit inquiries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.calendar.gcal_client import GoogleCalendarClient
from src.graph.state import MailInput, SchedulerResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class SchedulerAgent:
    """Answer facility visit and reservation inquiries.

    Args:
        api_key: OpenAI API key.
        calendar_client: GoogleCalendarClient instance.
    """

    def __init__(
        self,
        api_key: str,
        calendar_client: GoogleCalendarClient,
    ) -> None:
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.2,
            max_tokens=2048,
        )
        self._calendar = calendar_client
        self._prompt_path = _PROMPTS_DIR / "scheduler.txt"

    def draft_reply(self, mail_input: MailInput) -> SchedulerResult:
        """Draft a reply with availability info.

        Args:
            mail_input: Parsed email input.

        Returns:
            SchedulerResult with reply body and availability.
        """
        try:
            return self._call_llm(mail_input)
        except Exception:
            logger.exception(
                "Scheduler failed for message_id=%s", mail_input.message_id
            )
            return SchedulerResult(
                body="방문 예약 안내에 오류가 발생했습니다. 직접 전화 문의 부탁드립니다.",
                has_vacancy=self._calendar.has_vacancy(),
            )

    def _call_llm(self, mail_input: MailInput) -> SchedulerResult:
        """Build prompt with calendar data and call LLM."""
        available = self._calendar.get_available_dates()
        has_vacancy = self._calendar.has_vacancy()
        vacancy_count = self._calendar.get_vacancy_count()

        dates_text = "\n".join(
            f"  - {d['date']} ({d['weekday']}): {', '.join(d['time_slots'])}"
            for d in available[:10]
        ) if available else "(가능한 일정 없음)"

        template = self._prompt_path.read_text(encoding="utf-8")
        prompt_text = template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body[:2000],
            vacancy_count=vacancy_count,
            has_vacancy="있음" if has_vacancy else "없음",
            available_dates=dates_text,
        )

        response = self._llm.invoke([HumanMessage(content=prompt_text)])
        raw = str(response.content).strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        data = json.loads(raw)
        return SchedulerResult(
            body=data.get("body", ""),
            available_dates=data.get("available_dates", []),
            has_vacancy=data.get("has_vacancy", has_vacancy),
        )
