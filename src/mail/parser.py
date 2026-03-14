"""Parse raw Gmail API response dicts into MailInput models."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.graph.state import MailInput

logger = logging.getLogger(__name__)


def parse_email_to_input(raw: dict[str, Any]) -> MailInput:
    """Convert a raw email dict (from GmailClient) to a MailInput model.

    Args:
        raw: Dict with keys like id, threadId, subject, sender, body, etc.

    Returns:
        Populated MailInput instance.
    """
    internal_date_ms = raw.get("internalDate", 0)
    if internal_date_ms:
        received_dt = datetime.fromtimestamp(
            int(internal_date_ms) / 1000, tz=timezone.utc
        )
        received_at = received_dt.isoformat()
    else:
        received_at = raw.get("date", "")

    attachment_ids = []
    if raw.get("has_attachments"):
        # get_email_detail stores full attachment metadata;
        # extract just the IDs for downstream agents
        detail_attachments = raw.get("attachments", [])
        attachment_ids = [a["attachment_id"] for a in detail_attachments if "attachment_id" in a]

    return MailInput(
        message_id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        subject=raw.get("subject", ""),
        sender=raw.get("sender", ""),
        body=raw.get("body", ""),
        received_at=received_at,
        has_attachments=raw.get("has_attachments", False),
        attachment_ids=attachment_ids,
    )
