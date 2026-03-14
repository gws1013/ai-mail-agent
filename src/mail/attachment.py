"""Attachment download and file handling utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DOWNLOAD_DIR = Path("./downloads")


def download_attachments(
    gmail_client: Any,
    message_id: str,
    attachments: list[dict[str, Any]],
    download_dir: Path = _DOWNLOAD_DIR,
) -> list[str]:
    """Download all attachments for a message and return file paths.

    Args:
        gmail_client: GmailClient instance.
        message_id: Gmail message ID.
        attachments: List of attachment metadata dicts.
        download_dir: Directory to save downloaded files.

    Returns:
        List of downloaded file paths.
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    for att in attachments:
        filename = att.get("filename", "unknown")
        attachment_id = att.get("attachment_id", "")

        if not attachment_id:
            logger.warning("No attachment_id for '%s' — skipping.", filename)
            continue

        try:
            data = gmail_client.get_attachment_data(message_id, attachment_id)
            file_path = download_dir / f"{message_id}_{filename}"
            file_path.write_bytes(data)
            paths.append(str(file_path))
            logger.info("Downloaded attachment: %s (%d bytes)", file_path, len(data))
        except Exception:
            logger.exception("Failed to download attachment '%s'.", filename)

    return paths
