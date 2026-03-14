"""
Gmail API client for reading, sending, and labelling messages.

Handles OAuth 2.0 authentication, token persistence, and all direct
interactions with the Gmail REST API.  Higher-level pipeline components
should use this class rather than calling the API directly.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# OAuth 2.0 scopes required by this client
_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    """Thin wrapper around the Gmail API v1.

    Provides high-level helpers for the mail-agent pipeline:
    - Fetching unread messages
    - Sending replies
    - Marking messages as read / adding labels

    Args:
        credentials_path: Path to the OAuth2 ``credentials.json`` file
            downloaded from Google Cloud Console.
        token_path: Path where the OAuth2 access/refresh token is stored
            (created automatically on first run).
    """

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any = self._authenticate()
        # Cache of label name → label id to avoid repeated API round-trips
        self._label_cache: dict[str, str] = {}
        # Only process emails received after this timestamp (agent start time)
        import time
        self._start_epoch = int(time.time())

    # ---------------------------------------------------------------------- #
    # Authentication
    # ---------------------------------------------------------------------- #

    def _authenticate(self) -> Any:
        """Perform OAuth 2.0 flow and return an authorised Gmail API service.

        Loads an existing token from *token_path* when available and valid.
        If the token is expired but a refresh token exists, it is refreshed
        automatically.  Otherwise the full browser-based consent flow is
        triggered and the resulting token is saved for future runs.

        Returns:
            A ``googleapiclient`` service resource for ``gmail`` v1.

        Raises:
            FileNotFoundError: When *credentials_path* does not exist.
            google.auth.exceptions.TransportError: On network failures during
                token refresh.
        """
        if not self._credentials_path.exists():
            raise FileNotFoundError(
                f"Gmail credentials file not found: {self._credentials_path}"
            )

        creds: Optional[Credentials] = None

        # Try to load an existing token
        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), _SCOPES
                )
                logger.debug("Loaded existing OAuth token from %s", self._token_path)
            except Exception as exc:
                logger.warning("Failed to load token file (%s); re-authenticating.", exc)
                creds = None

        # Refresh or acquire new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired OAuth token.")
                creds.refresh(Request())
            else:
                logger.info(
                    "Starting OAuth2 consent flow; a browser window will open."
                )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), _SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Persist the (possibly refreshed) token
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
            logger.info("OAuth token saved to %s", self._token_path)

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        logger.debug("Gmail API service initialised.")
        return service

    # ---------------------------------------------------------------------- #
    # Public helpers – reading
    # ---------------------------------------------------------------------- #

    def get_unread_emails(
        self,
        label: str = "INBOX",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Return a list of unread message dicts from *label*.

        Each dict contains the following keys:

        - ``id``              – Gmail message ID (str)
        - ``threadId``        – Gmail thread ID (str)
        - ``subject``         – Email subject (str)
        - ``sender``          – Envelope sender address (str)
        - ``body``            – Decoded plain-text body (str)
        - ``date``            – Raw Date header value (str)
        - ``has_attachments`` – True when the message carries attachments (bool)

        Args:
            label: Gmail label name to query (default ``"INBOX"``).
            max_results: Maximum number of messages to return (default 10).

        Returns:
            List of email dicts ordered newest-first.

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        query = (
            f"is:unread label:{label}"
            f" -label:AI-Replied -label:AI-Escalated -label:AI-Skipped -label:AI-Error"
            f" after:{self._start_epoch}"
        )
        logger.debug("Querying Gmail: %r (max_results=%d)", query, max_results)

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            logger.error("Gmail list request failed: %s", exc)
            raise

        messages: list[dict[str, Any]] = response.get("messages", [])
        if not messages:
            logger.debug("No unread messages found for query %r.", query)
            return []

        results: list[dict[str, Any]] = []
        for msg_stub in messages:
            try:
                detail = self.get_email_detail(msg_stub["id"])
                results.append(
                    {
                        "id": detail["id"],
                        "threadId": detail["threadId"],
                        "subject": detail["headers"].get("Subject", "(no subject)"),
                        "sender": detail["headers"].get("From", ""),
                        "body": detail["body_text"],
                        "date": detail["headers"].get("Date", ""),
                        "has_attachments": detail["has_attachments"],
                    }
                )
            except HttpError as exc:
                logger.warning("Skipping message %s – fetch failed: %s", msg_stub["id"], exc)

        logger.info("Fetched %d unread message(s) from label %r.", len(results), label)
        return results

    def get_email_detail(self, message_id: str) -> dict[str, Any]:
        """Fetch the full representation of a single message.

        Returns a dict with:

        - ``id``              – Message ID
        - ``threadId``        – Thread ID
        - ``headers``         – Parsed header dict (Subject, From, Date, …)
        - ``body_text``       – Decoded plain-text body
        - ``body_html``       – Decoded HTML body (may be empty string)
        - ``attachments``     – List of ``{filename, mime_type, size}`` dicts
        - ``has_attachments`` – True when *attachments* is non-empty

        Args:
            message_id: Gmail message ID to fetch.

        Returns:
            Full email detail dict.

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to fetch message %s: %s", message_id, exc)
            raise

        payload: dict[str, Any] = msg.get("payload", {})
        headers = self._parse_headers(payload.get("headers", []))

        body_text, body_html = self._decode_body_parts(payload)
        attachments = self._extract_attachments(payload)

        return {
            "id": msg["id"],
            "threadId": msg["threadId"],
            "headers": headers,
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
            "has_attachments": bool(attachments),
        }

    # ---------------------------------------------------------------------- #
    # Public helpers – sending / modifying
    # ---------------------------------------------------------------------- #

    def send_reply(
        self,
        original_message_id: str,
        thread_id: str,
        to: str,
        subject: str,
        body_html: str,
    ) -> dict[str, Any]:
        """Send an HTML reply to *original_message_id* within *thread_id*.

        Sets the ``In-Reply-To`` and ``References`` MIME headers so that email
        clients thread the reply correctly.

        Args:
            original_message_id: The ``Message-ID`` header value of the mail
                being replied to (e.g. ``<xyz@mail.gmail.com>``).
            thread_id: Gmail thread ID to attach the reply to.
            to: Recipient address.
            subject: Reply subject line (should start with ``Re:``).
            body_html: Full HTML body of the reply.

        Returns:
            The ``messages.send`` API response dict (contains ``id`` and
            ``threadId`` of the sent message).

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        mime_msg = MIMEMultipart("alternative")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        mime_msg["In-Reply-To"] = original_message_id
        mime_msg["References"] = original_message_id

        mime_msg.attach(MIMEText(body_html, "html", "utf-8"))

        raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        try:
            result = (
                self._service.users()
                .messages()
                .send(
                    userId="me",
                    body={"raw": raw_bytes, "threadId": thread_id},
                )
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to send reply to thread %s: %s", thread_id, exc)
            raise

        logger.info(
            "Reply sent (message_id=%s, thread_id=%s).", result.get("id"), thread_id
        )
        return result

    def mark_as_read(self, message_id: str) -> None:
        """Remove the ``UNREAD`` label from *message_id*.

        Args:
            message_id: Gmail message ID to mark as read.

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        try:
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except HttpError as exc:
            logger.error("Failed to mark message %s as read: %s", message_id, exc)
            raise

        logger.debug("Message %s marked as read.", message_id)

    def add_label(self, message_id: str, label_name: str) -> None:
        """Apply *label_name* to *message_id*, creating the label if necessary.

        The resolved label ID is cached in-process to avoid redundant API
        calls on repeated invocations.

        Args:
            message_id: Gmail message ID to label.
            label_name: Human-readable label name (case-sensitive).

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        label_id = self._get_or_create_label(label_name)

        try:
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except HttpError as exc:
            logger.error(
                "Failed to add label %r to message %s: %s", label_name, message_id, exc
            )
            raise

        logger.debug("Label %r applied to message %s.", label_name, message_id)

    def create_draft(
        self,
        to: str,
        subject: str,
        body_html: str,
        thread_id: str = "",
        in_reply_to: str = "",
    ) -> dict[str, Any]:
        """Create a draft message in the user's mailbox.

        Args:
            to: Recipient address.
            subject: Email subject line.
            body_html: HTML body of the draft.
            thread_id: Optional Gmail thread ID to attach the draft to.
            in_reply_to: Optional Message-ID for threading headers.

        Returns:
            The ``drafts.create`` API response dict.
        """
        mime_msg = MIMEMultipart("alternative")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
            mime_msg["References"] = in_reply_to

        mime_msg.attach(MIMEText(body_html, "html", "utf-8"))
        raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        draft_body: dict[str, Any] = {"message": {"raw": raw_bytes}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        try:
            result = (
                self._service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to create draft: %s", exc)
            raise

        logger.info("Draft created (draft_id=%s).", result.get("id"))
        return result

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    def _get_or_create_label(self, label_name: str) -> str:
        """Return the Gmail label ID for *label_name*, creating it if absent.

        Args:
            label_name: Human-readable label name.

        Returns:
            Gmail label ID string.

        Raises:
            googleapiclient.errors.HttpError: On API errors.
        """
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        # Fetch all labels and populate the cache
        try:
            response = self._service.users().labels().list(userId="me").execute()
        except HttpError as exc:
            logger.error("Failed to list Gmail labels: %s", exc)
            raise

        for lbl in response.get("labels", []):
            self._label_cache[lbl["name"]] = lbl["id"]

        if label_name not in self._label_cache:
            logger.info("Creating new Gmail label: %r", label_name)
            try:
                new_label = (
                    self._service.users()
                    .labels()
                    .create(
                        userId="me",
                        body={
                            "name": label_name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                    .execute()
                )
            except HttpError as exc:
                logger.error("Failed to create label %r: %s", label_name, exc)
                raise

            self._label_cache[label_name] = new_label["id"]
            logger.debug("Label %r created with id %s.", label_name, new_label["id"])

        return self._label_cache[label_name]

    def _decode_body(self, payload: dict[str, Any]) -> str:
        """Extract the best available plain text from a message payload.

        Prefers ``text/plain`` parts; falls back to ``text/html`` when no
        plain-text alternative is present.  Handles both single-part and
        multipart MIME structures recursively.

        Args:
            payload: The ``payload`` dict from a Gmail ``messages.get``
                response.

        Returns:
            Decoded body string (may be empty if no text parts exist).
        """
        text, _ = self._decode_body_parts(payload)
        return text

    def _decode_body_parts(
        self, payload: dict[str, Any]
    ) -> tuple[str, str]:
        """Recursively extract (text/plain, text/html) from a MIME payload.

        Args:
            payload: Gmail message payload dict.

        Returns:
            A ``(plain_text, html_text)`` tuple.  Either or both may be empty.
        """
        mime_type: str = payload.get("mimeType", "")
        parts: list[dict[str, Any]] = payload.get("parts", [])

        plain_text = ""
        html_text = ""

        if mime_type == "text/plain":
            plain_text = self._b64_decode(payload.get("body", {}).get("data", ""))
        elif mime_type == "text/html":
            html_text = self._b64_decode(payload.get("body", {}).get("data", ""))
        elif parts:
            for part in parts:
                pt, ht = self._decode_body_parts(part)
                if pt and not plain_text:
                    plain_text = pt
                if ht and not html_text:
                    html_text = ht
        else:
            # Fallback for non-multipart with inline body data
            data = payload.get("body", {}).get("data", "")
            if data:
                plain_text = self._b64_decode(data)

        return plain_text, html_text

    @staticmethod
    def _b64_decode(data: str) -> str:
        """URL-safe base64 decode *data* and return the UTF-8 string.

        Args:
            data: Base64url-encoded string as returned by the Gmail API.

        Returns:
            Decoded UTF-8 string, or empty string on decoding failure.
        """
        if not data:
            return ""
        try:
            padded = data + "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Base64 decode failed: %s", exc)
            return ""

    def _extract_attachments(
        self, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Collect attachment metadata from a message payload.

        Does not download attachment data; returns only descriptive info.

        Args:
            payload: Gmail message payload dict.

        Returns:
            List of dicts with keys ``filename``, ``mime_type``, ``size``.
        """
        attachments: list[dict[str, Any]] = []
        self._collect_attachments(payload, attachments)
        return attachments

    def _collect_attachments(
        self,
        payload: dict[str, Any],
        bucket: list[dict[str, Any]],
    ) -> None:
        """Recursively walk *payload* and append attachment info to *bucket*.

        Args:
            payload: Gmail message payload (or sub-part) dict.
            bucket: Mutable list to accumulate attachment dicts.
        """
        filename: str = payload.get("filename", "")
        body: dict[str, Any] = payload.get("body", {})

        if filename and body.get("attachmentId"):
            bucket.append(
                {
                    "filename": filename,
                    "mime_type": payload.get("mimeType", "application/octet-stream"),
                    "size": body.get("size", 0),
                    "attachment_id": body["attachmentId"],
                }
            )

        for part in payload.get("parts", []):
            self._collect_attachments(part, bucket)

    @staticmethod
    def _parse_headers(headers: list[dict[str, str]]) -> dict[str, str]:
        """Convert a Gmail header list into a plain dict.

        Extracts the following headers (others are discarded):
        ``Subject``, ``From``, ``To``, ``Cc``, ``Date``, ``Message-ID``,
        ``In-Reply-To``, ``References``.

        Args:
            headers: List of ``{name: str, value: str}`` dicts from the Gmail
                API ``payload.headers`` field.

        Returns:
            Dict mapping header names to their values.
        """
        _INTERESTING = {
            "Subject",
            "From",
            "To",
            "Cc",
            "Date",
            "Message-ID",
            "In-Reply-To",
            "References",
        }
        result: dict[str, str] = {}
        for hdr in headers:
            name: str = hdr.get("name", "")
            if name in _INTERESTING:
                result[name] = hdr.get("value", "")
        return result
