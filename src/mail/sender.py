"""
High-level email sending interface for the AI Mail Agent pipeline.

Sits on top of :class:`~src.mail.gmail_client.GmailClient` and applies
business logic such as:

- Using the reviewer's ``revised_body`` when it overrides the drafter's body.
- Converting Markdown to HTML for formatted replies.
- Generating human-readable preview strings for logging and human-in-the-loop
  approval flows.
"""

from __future__ import annotations

import logging
import re
import textwrap
from typing import Any

import markdown

from src.graph.state import DraftResult, ReviewResult
from src.mail.gmail_client import GmailClient

logger = logging.getLogger(__name__)

# Maximum width used when wrapping preview text for terminal display
_PREVIEW_WIDTH: int = 80
# Separator line used in preview output
_SEPARATOR: str = "-" * _PREVIEW_WIDTH


class EmailSender:
    """Composes and dispatches reply emails.

    Wraps :class:`~src.mail.gmail_client.GmailClient` and adds the following
    pipeline-specific behaviour:

    - If :attr:`~src.graph.state.ReviewResult.revised_body` is set, that
      plain-text body takes precedence over the drafter's output and is
      converted to HTML before sending.
    - Markdown in the body is converted to HTML via the ``markdown`` library.

    Args:
        gmail_client: An authenticated :class:`~src.mail.gmail_client.GmailClient`
            instance.
    """

    def __init__(self, gmail_client: GmailClient) -> None:
        self._client = gmail_client

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def send_reply(
        self,
        original_email: dict[str, Any],
        draft: DraftResult,
        review: ReviewResult,
    ) -> dict[str, Any]:
        """Send the reviewed reply for *original_email*.

        Decision logic for the body:

        1. If ``review.revised_body`` is set (reviewer produced a corrected
           version), use that as the canonical plain-text source.
        2. Otherwise use ``draft.body``.

        The chosen plain-text body is converted to HTML via
        :func:`markdown.markdown` and passed to
        :meth:`~src.mail.gmail_client.GmailClient.send_reply`.

        The original message is automatically marked as read after a
        successful send.

        Args:
            original_email: Raw email dict as returned by
                :meth:`~src.mail.gmail_client.GmailClient.get_unread_emails`.
                Must contain ``id``, ``threadId``, ``sender``, and
                ``subject`` keys.
            draft: Drafter output containing subject and body.
            review: Reviewer output; ``revised_body`` overrides the draft when
                set.

        Returns:
            The Gmail API ``messages.send`` response dict (contains ``id``
            and ``threadId`` of the sent message).

        Raises:
            googleapiclient.errors.HttpError: On Gmail API errors.
        """
        # Resolve the body to use
        if review.revised_body:
            logger.info(
                "Using reviewer-revised body instead of drafter body for message %s.",
                original_email.get("id"),
            )
            plain_body = review.revised_body
        else:
            plain_body = draft.body

        reply_html = self._to_html(plain_body)

        # Build quoted original message
        original_body: str = original_email.get("body", "")
        original_date: str = original_email.get("date", "")
        raw_sender: str = original_email.get("sender", "")

        quoted_html = self._build_quoted_reply(
            reply_html=reply_html,
            original_body=original_body,
            original_sender=raw_sender,
            original_date=original_date,
        )

        # Construct the reply subject (avoid double "Re:" prefixes)
        subject = self._ensure_re_prefix(draft.subject)

        # The reply goes back to the original sender
        # Extract bare email from "Name <email>" format
        match = re.search(r"<([^>]+)>", raw_sender)
        to_address: str = match.group(1) if match else raw_sender
        thread_id: str = original_email.get("threadId", "")
        original_message_id: str = original_email.get("id", "")

        logger.info(
            "Sending reply to %r (thread=%s, subject=%r).",
            to_address,
            thread_id,
            subject,
        )

        result = self._client.send_reply(
            original_message_id=original_message_id,
            thread_id=thread_id,
            to=to_address,
            subject=subject,
            body_html=quoted_html,
        )

        # Mark the original message as read now that we have replied
        try:
            self._client.mark_as_read(original_message_id)
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: log the warning but do not fail the send operation
            logger.warning(
                "Failed to mark message %s as read after sending reply: %s",
                original_message_id,
                exc,
            )

        return result

    def preview_reply(self, draft: DraftResult) -> str:
        """Return a formatted preview string suitable for logging or display.

        The preview includes:
        - Subject line
        - Confidence score and tone check
        - Body (wrapped to :data:`_PREVIEW_WIDTH` columns)

        Args:
            draft: The :class:`~src.graph.state.DraftResult` to preview.

        Returns:
            A multi-line string ready to be printed or logged.
        """
        wrapped_body = textwrap.fill(
            draft.body,
            width=_PREVIEW_WIDTH,
            break_long_words=False,
            break_on_hyphens=False,
        )

        lines = [
            _SEPARATOR,
            "REPLY PREVIEW",
            _SEPARATOR,
            f"Subject  : {draft.subject}",
            f"Confidence: {draft.confidence:.0%}",
            f"Tone     : {draft.tone_check}",
            _SEPARATOR,
            wrapped_body,
            _SEPARATOR,
        ]
        return "\n".join(lines)

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _to_html(plain_text: str) -> str:
        """Convert *plain_text* (Markdown) to an HTML string.

        Uses the ``markdown`` library with the ``extra`` and ``nl2br``
        extensions for sensible default rendering:

        - ``extra``: Enables tables, footnotes, fenced code blocks, etc.
        - ``nl2br``: Turns single newlines into ``<br>`` tags.

        Args:
            plain_text: Plain-text / Markdown body.

        Returns:
            Full HTML string wrapped in a ``<div>`` element.
        """
        html_content: str = markdown.markdown(
            plain_text,
            extensions=["extra", "nl2br"],
            output_format="html",
        )
        # Wrap in a div to give email clients a hook for styling
        return f'<div class="ai-mail-reply">\n{html_content}\n</div>'

    @staticmethod
    def _build_quoted_reply(
        reply_html: str,
        original_body: str,
        original_sender: str,
        original_date: str,
    ) -> str:
        """Build a full reply HTML with the original message quoted below.

        Args:
            reply_html: HTML of the new reply.
            original_body: Plain-text body of the original email.
            original_sender: Sender of the original email.
            original_date: Date header of the original email.

        Returns:
            Combined HTML with reply on top and quoted original below.
        """
        # Escape HTML entities in original body
        escaped_body = (
            original_body
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>\n")
        )

        quoted_block = (
            f'<br><br>'
            f'<div class="gmail_quote">'
            f'<div style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex">'
            f'<p style="color:#888">{original_date}, {original_sender}:</p>'
            f'<p>{escaped_body}</p>'
            f'</div>'
            f'</div>'
        )

        return f'{reply_html}{quoted_block}'

    @staticmethod
    def _ensure_re_prefix(subject: str) -> str:
        """Prepend ``Re:`` to *subject* if not already present.

        The check is case-insensitive so ``RE:``, ``re:``, etc. are recognised.

        Args:
            subject: Draft subject string.

        Returns:
            Subject guaranteed to start with ``Re: ``.
        """
        if subject.lower().startswith("re:"):
            return subject
        return f"Re: {subject}"
