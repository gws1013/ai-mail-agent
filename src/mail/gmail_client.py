"""Gmail API client — read, send, draft, label operations."""

from __future__ import annotations

import base64
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    """Thin wrapper around Gmail API v1.

    Args:
        credentials_path: Path to OAuth2 credentials.json.
        token_path: Path to persisted OAuth2 token.
        lookback_hours: Process emails received up to N hours before init.
    """

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        lookback_hours: float = 0,
    ) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any = self._authenticate()
        self._label_cache: dict[str, str] = {}
        self._start_epoch = int(time.time()) - int(lookback_hours * 3600)

    # ── Authentication ───────────────────────────────────────────

    def _authenticate(self) -> Any:
        """Perform OAuth 2.0 flow and return Gmail API service."""
        if not self._credentials_path.exists():
            raise FileNotFoundError(
                f"Gmail credentials not found: {self._credentials_path}"
            )

        creds: Optional[Credentials] = None

        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), _SCOPES
                )
            except Exception as exc:
                logger.warning("Failed to load token (%s); re-authenticating.", exc)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired OAuth token.")
                creds.refresh(Request())
            else:
                logger.info("Starting OAuth2 consent flow.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), _SCOPES
                )
                creds = flow.run_local_server(port=0)

            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._token_path, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
            logger.info("OAuth token saved to %s", self._token_path)

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ── Reading ──────────────────────────────────────────────────

    def get_unread_emails(
        self,
        label: str = "INBOX",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Return unread emails after ``_start_epoch``, oldest first.

        Args:
            label: Gmail label to query.
            max_results: Max messages to return.

        Returns:
            List of email dicts sorted oldest-first.
        """
        query = (
            f"is:unread label:{label}"
            f" -label:AI-Replied -label:AI-Escalated"
            f" -label:AI-Skipped -label:AI-Error"
            f" after:{self._start_epoch}"
        )
        logger.debug("Gmail query: %r (max=%d)", query, max_results)

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            logger.error("Gmail list failed: %s", exc)
            raise

        messages = response.get("messages", [])
        if not messages:
            return []

        results: list[dict[str, Any]] = []
        start_ms = self._start_epoch * 1000

        for msg_stub in messages:
            try:
                detail = self.get_email_detail(msg_stub["id"])
                internal_date_ms = int(detail.get("internalDate", 0))
                if internal_date_ms < start_ms:
                    continue

                results.append({
                    "id": detail["id"],
                    "threadId": detail["threadId"],
                    "subject": detail["headers"].get("Subject", "(제목 없음)"),
                    "sender": detail["headers"].get("From", ""),
                    "body": detail["body_text"],
                    "date": detail["headers"].get("Date", ""),
                    "has_attachments": detail["has_attachments"],
                    "internalDate": internal_date_ms,
                })
            except HttpError as exc:
                logger.warning("Skipping message %s: %s", msg_stub["id"], exc)

        # Sort oldest-first
        results.sort(key=lambda e: e.get("internalDate", 0))
        logger.info("Fetched %d unread email(s) from '%s'.", len(results), label)
        return results

    def get_email_detail(self, message_id: str) -> dict[str, Any]:
        """Fetch full message detail."""
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

        payload = msg.get("payload", {})
        headers = self._parse_headers(payload.get("headers", []))
        body_text, body_html = self._decode_body_parts(payload)
        attachments = self._extract_attachments(payload)

        return {
            "id": msg["id"],
            "threadId": msg["threadId"],
            "internalDate": msg.get("internalDate", "0"),
            "headers": headers,
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
            "has_attachments": bool(attachments),
        }

    def get_attachment_data(self, message_id: str, attachment_id: str) -> bytes:
        """Download raw attachment bytes.

        Args:
            message_id: Gmail message ID.
            attachment_id: Attachment ID from message payload.

        Returns:
            Raw attachment bytes.
        """
        result = (
            self._service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = result.get("data", "")
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded)

    # ── Sending / Drafts ─────────────────────────────────────────

    def send_reply(
        self,
        original_message_id: str,
        thread_id: str,
        to: str,
        subject: str,
        body_html: str,
        attachment_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send an HTML reply, optionally with an attachment."""
        mime_msg = MIMEMultipart("mixed")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        mime_msg["In-Reply-To"] = original_message_id
        mime_msg["References"] = original_message_id

        html_part = MIMEText(body_html, "html", "utf-8")
        mime_msg.attach(html_part)

        if attachment_path:
            self._attach_file(mime_msg, attachment_path)

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        try:
            result = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw, "threadId": thread_id})
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to send reply: %s", exc)
            raise

        logger.info("Reply sent (id=%s, thread=%s).", result.get("id"), thread_id)
        return result

    def create_draft(
        self,
        to: str,
        subject: str,
        body_html: str,
        thread_id: str = "",
        in_reply_to: str = "",
        attachment_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a draft in Gmail."""
        mime_msg = MIMEMultipart("mixed")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
            mime_msg["References"] = in_reply_to

        html_part = MIMEText(body_html, "html", "utf-8")
        mime_msg.attach(html_part)

        if attachment_path:
            self._attach_file(mime_msg, attachment_path)

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
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

        logger.info("Draft created (id=%s).", result.get("id"))
        return result

    # ── Label operations ─────────────────────────────────────────

    def mark_as_read(self, message_id: str) -> None:
        """Remove UNREAD label."""
        try:
            self._service.users().messages().modify(
                userId="me", id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except HttpError as exc:
            logger.error("Failed to mark read %s: %s", message_id, exc)
            raise

    def add_label(self, message_id: str, label_name: str) -> None:
        """Apply label to message, creating if necessary."""
        label_id = self._get_or_create_label(label_name)
        try:
            self._service.users().messages().modify(
                userId="me", id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except HttpError as exc:
            logger.error("Failed to add label %r: %s", label_name, exc)
            raise

    # ── Private helpers ──────────────────────────────────────────

    def _attach_file(self, mime_msg: MIMEMultipart, file_path: str) -> None:
        """Attach a file to a MIME message."""
        path = Path(file_path)
        if not path.exists():
            logger.warning("Attachment file not found: %s", file_path)
            return

        suffix = path.suffix.lstrip(".") or "octet-stream"
        part = MIMEApplication(path.read_bytes(), _subtype=suffix)
        logger.info("Attaching file: name=%s, suffix=%s, size=%d bytes", path.name, suffix, path.stat().st_size)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=path.name,
        )
        mime_msg.attach(part)

    def _get_or_create_label(self, label_name: str) -> str:
        """Get or create a Gmail label, returning its ID."""
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        try:
            response = self._service.users().labels().list(userId="me").execute()
        except HttpError as exc:
            logger.error("Failed to list labels: %s", exc)
            raise

        for lbl in response.get("labels", []):
            self._label_cache[lbl["name"]] = lbl["id"]

        if label_name not in self._label_cache:
            try:
                new_label = (
                    self._service.users().labels().create(
                        userId="me",
                        body={
                            "name": label_name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    ).execute()
                )
                self._label_cache[label_name] = new_label["id"]
            except HttpError as exc:
                logger.error("Failed to create label %r: %s", label_name, exc)
                raise

        return self._label_cache[label_name]

    def _decode_body_parts(self, payload: dict[str, Any]) -> tuple[str, str]:
        """Recursively extract (plain, html) from MIME payload."""
        mime_type = payload.get("mimeType", "")
        parts = payload.get("parts", [])
        plain, html = "", ""

        if mime_type == "text/plain":
            plain = self._b64_decode(payload.get("body", {}).get("data", ""))
        elif mime_type == "text/html":
            html = self._b64_decode(payload.get("body", {}).get("data", ""))
        elif parts:
            for part in parts:
                pt, ht = self._decode_body_parts(part)
                if pt and not plain:
                    plain = pt
                if ht and not html:
                    html = ht
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                plain = self._b64_decode(data)

        return plain, html

    @staticmethod
    def _b64_decode(data: str) -> str:
        """URL-safe base64 decode to UTF-8 string."""
        if not data:
            return ""
        try:
            padded = data + "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Base64 decode failed: %s", exc)
            return ""

    def _extract_attachments(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Collect attachment metadata from payload."""
        attachments: list[dict[str, Any]] = []
        self._walk_attachments(payload, attachments)
        return attachments

    def _walk_attachments(
        self,
        payload: dict[str, Any],
        bucket: list[dict[str, Any]],
    ) -> None:
        """Recursively walk payload for attachments."""
        filename = payload.get("filename", "")
        body = payload.get("body", {})

        if filename and body.get("attachmentId"):
            bucket.append({
                "filename": filename,
                "mime_type": payload.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
                "attachment_id": body["attachmentId"],
            })

        for part in payload.get("parts", []):
            self._walk_attachments(part, bucket)

    @staticmethod
    def _parse_headers(headers: list[dict[str, str]]) -> dict[str, str]:
        """Extract interesting headers into a dict."""
        interesting = {
            "Subject", "From", "To", "Cc", "Date",
            "Message-ID", "In-Reply-To", "References",
        }
        return {
            h["name"]: h.get("value", "")
            for h in headers
            if h.get("name", "") in interesting
        }
