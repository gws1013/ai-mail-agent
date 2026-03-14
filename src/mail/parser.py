"""
Email parsing utilities.

Converts raw Gmail API response dicts into strongly-typed Pydantic models
that are consumed by the LangGraph pipeline.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src.graph.state import MailInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML-stripping helpers (no external dependencies)
# ---------------------------------------------------------------------------

# Matches any HTML/XML tag
_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>", re.DOTALL)
# Collapse runs of blank lines to a single blank line
_BLANK_LINES_RE: re.Pattern[str] = re.compile(r"\n{3,}")
# Common HTML entities
_HTML_ENTITIES: dict[str, str] = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
    "&#39;": "'",
    "&nbsp;": " ",
    "&ndash;": "–",
    "&mdash;": "—",
}
_ENTITY_RE: re.Pattern[str] = re.compile(
    "|".join(re.escape(k) for k in _HTML_ENTITIES)
)


def _strip_html(html: str) -> str:
    """Remove HTML markup and decode common entities from *html*.

    Uses only the standard library and compiled regex patterns; no third-party
    HTML-parsing dependency is required.

    Args:
        html: Raw HTML string.

    Returns:
        Plain-text approximation with excess blank lines collapsed.
    """
    # Replace block-level elements with newlines for readability
    text = re.sub(r"<(?:br|p|div|li|tr|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = _TAG_RE.sub("", text)
    # Decode HTML entities
    text = _ENTITY_RE.sub(lambda m: _HTML_ENTITIES[m.group(0)], text)
    # Normalise whitespace
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime:
    """Parse an RFC 2822 / RFC 5322 date string into a UTC-aware datetime.

    Falls back to ``datetime.now(UTC)`` and logs a warning when parsing fails.

    Args:
        date_str: Raw ``Date`` header value, e.g.
            ``"Tue, 01 Jan 2025 12:00:00 +0000"``.

    Returns:
        UTC-aware :class:`datetime` object.
    """
    if not date_str:
        logger.warning("Empty date string; using current UTC time as fallback.")
        return datetime.now(timezone.utc)

    try:
        dt = parsedate_to_datetime(date_str)
        # Ensure the datetime is timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse date %r (%s); using current UTC time.", date_str, exc)
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_email_to_input(raw_email: dict[str, Any]) -> MailInput:
    """Convert a Gmail API response dict to a :class:`~src.graph.state.MailInput`.

    The *raw_email* dict is expected to have the structure returned by
    :meth:`~src.mail.gmail_client.GmailClient.get_unread_emails`, i.e.:

    .. code-block:: python

        {
            "id": str,
            "threadId": str,
            "subject": str,
            "sender": str,
            "body": str,           # plain text (may be empty)
            "date": str,           # RFC 5322 date string
            "has_attachments": bool,
        }

    When the ``body`` field appears to contain HTML (detected by the presence
    of ``<`` characters), it is stripped to plain text before being stored.

    Args:
        raw_email: Dict as returned by :class:`~src.mail.gmail_client.GmailClient`.

    Returns:
        A validated :class:`~src.graph.state.MailInput` instance.

    Raises:
        KeyError: When a required field is absent from *raw_email*.
        pydantic.ValidationError: When field values fail Pydantic validation.
    """
    body: str = raw_email.get("body", "")

    # If the body looks like HTML, strip tags to get plain text
    if "<" in body and ">" in body:
        logger.debug(
            "Message %s body appears to be HTML; stripping markup.", raw_email.get("id")
        )
        body = _strip_html(body)

    received_at: datetime = _parse_date(raw_email.get("date", ""))

    mail_input = MailInput(
        subject=raw_email.get("subject", "(no subject)"),
        sender=raw_email.get("sender", ""),
        body=body,
        has_attachments=bool(raw_email.get("has_attachments", False)),
        message_id=raw_email["id"],
        thread_id=raw_email["threadId"],
        received_at=received_at,
    )

    logger.debug(
        "Parsed email %s → MailInput(subject=%r, sender=%r, received_at=%s).",
        mail_input.message_id,
        mail_input.subject,
        mail_input.sender,
        mail_input.received_at.isoformat(),
    )
    return mail_input
