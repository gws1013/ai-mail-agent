"""Windows desktop notification helper."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify(title: str, message: str, timeout: int = 10) -> None:
    """Show a Windows desktop notification.

    Args:
        title: Notification title.
        message: Notification body text.
        timeout: Display duration in seconds.
    """
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            timeout=timeout,
            app_name="AI Mail Agent",
        )
    except ImportError:
        logger.warning("plyer not installed — skipping desktop notification.")
    except Exception:
        logger.exception("Failed to show desktop notification.")
