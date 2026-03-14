"""Windows desktop notification utility."""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def notify(title: str, message: str) -> None:
    """Show a Windows 10/11 toast notification.

    Falls back silently if the notification cannot be displayed.

    Parameters
    ----------
    title:
        Notification title (short).
    message:
        Notification body text.
    """
    if sys.platform != "win32":
        logger.debug("Notifications only supported on Windows; skipping.")
        return

    try:
        # Use PowerShell to show a Windows toast notification (no extra deps)
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$textNodes = $template.GetElementsByTagName('text'); "
            f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{_escape_ps(title)}')) > $null; "
            f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{_escape_ps(message)}')) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('AI Mail Agent').Show($toast)"
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:
        logger.debug("Toast notification failed, trying fallback.")
        _fallback_notify(title, message)


def _fallback_notify(title: str, message: str) -> None:
    """Fallback: use a simple BalloonTip via PowerShell."""
    try:
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; "
            "$n.Visible = $true; "
            f"$n.ShowBalloonTip(5000, '{_escape_ps(title)}', '{_escape_ps(message)}', "
            "'Info'); "
            "Start-Sleep -Seconds 6; "
            "$n.Dispose()"
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    except Exception:
        logger.debug("Fallback notification also failed.")


def _escape_ps(text: str) -> str:
    """Escape single quotes for PowerShell string literals."""
    return text.replace("'", "''").replace("\n", " ")
