"""Email sending and draft saving helper."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import markdown as md

from src.mail.gmail_client import GmailClient

logger = logging.getLogger(__name__)


class EmailSender:
    """Send replies or save drafts via Gmail.

    Args:
        client: GmailClient instance.
    """

    def __init__(self, client: GmailClient) -> None:
        self._client = client

    def send_reply(
        self,
        raw_email: dict[str, Any],
        body_text: str,
        attachment_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a reply to the original email.

        Args:
            raw_email: Original email dict.
            body_text: Reply body (markdown or plain text).
            attachment_path: Optional file to attach.

        Returns:
            Gmail API response.
        """
        sender = raw_email.get("sender", "")
        to_addr = self._extract_email(sender)
        subject = raw_email.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body_html = self._to_html(body_text)
        return self._client.send_reply(
            original_message_id=raw_email.get("id", ""),
            thread_id=raw_email.get("threadId", ""),
            to=to_addr,
            subject=subject,
            body_html=body_html,
            attachment_path=attachment_path,
        )

    def save_draft(
        self,
        raw_email: dict[str, Any],
        body_text: str,
        attachment_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save a draft reply to Gmail drafts folder.

        Args:
            raw_email: Original email dict.
            body_text: Draft body text.
            attachment_path: Optional file to attach.

        Returns:
            Gmail API response.
        """
        sender = raw_email.get("sender", "")
        to_addr = self._extract_email(sender)
        subject = raw_email.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body_html = self._to_html(body_text)
        return self._client.create_draft(
            to=to_addr,
            subject=subject,
            body_html=body_html,
            thread_id=raw_email.get("threadId", ""),
            in_reply_to=raw_email.get("id", ""),
            attachment_path=attachment_path,
        )

    @staticmethod
    def _extract_email(sender: str) -> str:
        """Extract email address from 'Name <email>' format."""
        match = re.search(r"<([^>]+)>", sender)
        return match.group(1) if match else sender

    @staticmethod
    def _to_html(text: str) -> str:
        """Convert markdown/plain text to HTML."""
        return md.markdown(text, extensions=["tables", "fenced_code"])
