"""Signer agent — handles signature request emails."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from src.graph.state import MailInput, SignerResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class SignerAgent:
    """Process signature request emails.

    Downloads attachments, prepares signed files, and drafts a reply
    for human review (saved to drafts).

    Args:
        api_key: OpenAI API key.
    """

    def __init__(self, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=api_key,
            temperature=0.2,
            max_tokens=2048,
        )
        self._prompt_path = _PROMPTS_DIR / "signer.txt"

    def process(
        self,
        mail_input: MailInput,
        attachment_paths: list[str],
    ) -> SignerResult:
        """Process a signature request email.

        Args:
            mail_input: Parsed email input.
            attachment_paths: List of downloaded attachment file paths.

        Returns:
            SignerResult with reply body and signed file path.
        """
        try:
            return self._call_llm(mail_input, attachment_paths)
        except Exception:
            logger.exception(
                "Signer failed for message_id=%s", mail_input.message_id
            )
            return SignerResult(
                signed_file_path=attachment_paths[0] if attachment_paths else "",
                reply_body="서명 처리 중 오류가 발생했습니다. 담당자에게 문의해주세요.",
                confidence=0.0,
            )

    def _call_llm(
        self,
        mail_input: MailInput,
        attachment_paths: list[str],
    ) -> SignerResult:
        """Generate reply body for signature request."""
        template = self._prompt_path.read_text(encoding="utf-8")
        attachment_names = ", ".join(
            Path(p).name for p in attachment_paths
        ) or "(없음)"

        prompt_text = template.format(
            subject=mail_input.subject,
            sender=mail_input.sender,
            body=mail_input.body[:2000],
            attachment_names=attachment_names,
        )

        response = self._llm.invoke([HumanMessage(content=prompt_text)])
        raw = str(response.content).strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()

        data = json.loads(raw)

        # Use first attachment as "signed" file (actual signing is manual)
        signed_path = attachment_paths[0] if attachment_paths else ""

        return SignerResult(
            signed_file_path=signed_path,
            reply_body=data.get("body", ""),
            confidence=float(data.get("confidence", 0.7)),
        )
