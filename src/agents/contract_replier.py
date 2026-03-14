"""Contract replier agent — answers guardian questions about contracts."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import DraftResult, MailInput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ContractReplierAgent:
    """Answer contract-related questions using RAG context.

    Uses gpt-4o-mini by default; escalates to gpt-5.2 if confidence
    is too low or the question involves complex legal terms.

    Args:
        api_key: OpenAI API key.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.2,
            max_tokens=4096,
        )
        self._llm_escalated = ChatOpenAI(
            model="gpt-5.2",
            api_key=api_key,
            temperature=0.2,
            max_tokens=4096,
        )
        self._prompt_path = _PROMPTS_DIR / "contract_replier.txt"

    def draft(
        self,
        mail_input: MailInput,
        contract_context: list[str],
    ) -> DraftResult:
        """Draft a reply based on contract context.

        Args:
            mail_input: Parsed email input.
            contract_context: List of relevant contract passages from RAG.

        Returns:
            DraftResult with reply body.
        """
        try:
            result = self._call_llm(mail_input, contract_context, self._llm)

            # Escalate to gpt-5.2 if confidence is low
            if result.confidence < 0.7:
                logger.info(
                    "ContractReplier: confidence %.2f < 0.7, escalating to gpt-5.2",
                    result.confidence,
                )
                result = self._call_llm(
                    mail_input, contract_context, self._llm_escalated
                )
                result.needs_escalation = False

            return result
        except Exception:
            logger.exception(
                "ContractReplier failed for message_id=%s", mail_input.message_id
            )
            return DraftResult(
                body="계약서 관련 문의에 대한 답변 생성 중 오류가 발생했습니다.",
                confidence=0.0,
                needs_escalation=True,
            )

    def _call_llm(
        self,
        mail_input: MailInput,
        contract_context: list[str],
        llm: ChatOpenAI,
    ) -> DraftResult:
        """Build prompt and call LLM for contract reply."""
        template = self._prompt_path.read_text(encoding="utf-8")
        context_text = "\n\n".join(
            f"--- 계약서 발췌 {i+1} ---\n{ctx}"
            for i, ctx in enumerate(contract_context)
        ) if contract_context else "(관련 계약서 내용 없음)"

        prompt_text = template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body[:2000],
            contract_context=context_text,
        )

        response = llm.invoke([HumanMessage(content=prompt_text)])
        raw = str(response.content).strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        data = json.loads(raw)
        return DraftResult(
            body=data.get("body", ""),
            sources=data.get("sources", []),
            confidence=float(data.get("confidence", 0.5)),
        )
