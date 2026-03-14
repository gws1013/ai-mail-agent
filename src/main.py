"""AI Mail Agent - Main entry point."""

import time
import logging
import signal
import sys

from src.config import get_settings
from src.utils.logger import setup_logger
from src.utils.cost_tracker import CostTracker
from src.mail.gmail_client import GmailClient
from src.mail.parser import parse_email_to_input
from src.graph.workflow import process_email

logger = logging.getLogger(__name__)


class MailAgent:
    """Main mail agent that polls for new emails and processes them."""

    def __init__(self):
        self.settings = get_settings()
        setup_logger("ai_mail_agent", self.settings.LOG_DIR, self.settings.LOG_LEVEL)
        self.gmail_client = GmailClient(
            credentials_path=self.settings.GMAIL_CREDENTIALS_PATH,
            token_path=self.settings.GMAIL_TOKEN_PATH,
        )
        self.cost_tracker = CostTracker(self.settings.COST_LOG_PATH)
        self._running = True

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}. Shutting down gracefully...")
        self._running = False

    def run(self):
        """Start the mail agent polling loop."""
        logger.info("=" * 60)
        logger.info("AI Mail Agent started")
        logger.info(f"Poll interval: {self.settings.POLL_INTERVAL_SECONDS}s")
        logger.info(f"Auto-send threshold: {self.settings.AUTO_SEND_THRESHOLD}")
        logger.info(f"Monthly budget: ${self.settings.MAX_MONTHLY_COST_USD}")
        logger.info("=" * 60)

        while self._running:
            try:
                # Check budget
                if self.cost_tracker.is_budget_exceeded(self.settings.MAX_MONTHLY_COST_USD):
                    logger.warning("Monthly budget exceeded! Pausing agent.")
                    time.sleep(3600)  # Wait 1 hour before checking again
                    continue

                # Poll for new emails
                self._poll_and_process()

                # Wait for next poll
                logger.debug(f"Sleeping {self.settings.POLL_INTERVAL_SECONDS}s until next poll...")
                for _ in range(self.settings.POLL_INTERVAL_SECONDS):
                    if not self._running:
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(60)  # Wait 1 minute on error

        logger.info("AI Mail Agent stopped.")

    def _poll_and_process(self):
        """Poll for new emails and process each one."""
        logger.info("Polling for new emails...")

        try:
            emails = self.gmail_client.get_unread_emails(
                label=self.settings.GMAIL_WATCH_LABEL,
                max_results=10,
            )
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return

        if not emails:
            logger.info("No new emails found.")
            return

        logger.info(f"Found {len(emails)} new email(s)")

        for raw_email in emails:
            try:
                logger.info(f"Processing: {raw_email.get('subject', 'No subject')}")
                mail_input = parse_email_to_input(raw_email)
                result = process_email(mail_input.model_dump(mode="python"), raw_email)

                # Mark as read regardless of action
                self.gmail_client.mark_as_read(raw_email["id"])

                # Add label based on action
                action = result.get("final_action", "error")
                label_map = {
                    "sent": "AI-Replied",
                    "escalated": "AI-Escalated",
                    "skipped": "AI-Skipped",
                    "error": "AI-Error",
                }
                label = label_map.get(action, "AI-Processed")
                self.gmail_client.add_label(raw_email["id"], label)

                logger.info(f"Result: {action}")

            except Exception as e:
                logger.error(f"Failed to process email: {e}", exc_info=True)

    def process_single(self, message_id: str) -> dict:
        """Process a single email by ID (for testing/manual use)."""
        detail = self.gmail_client.get_email_detail(message_id)
        raw_email = {
            "id": detail["id"],
            "threadId": detail["threadId"],
            "subject": detail["headers"].get("Subject", "(no subject)"),
            "sender": detail["headers"].get("From", ""),
            "body": detail["body_text"],
            "date": detail["headers"].get("Date", ""),
            "has_attachments": detail["has_attachments"],
        }
        mail_input = parse_email_to_input(raw_email)
        return process_email(mail_input.model_dump(mode="python"), raw_email)


def main():
    """Entry point."""
    agent = MailAgent()
    agent.run()


if __name__ == "__main__":
    main()
