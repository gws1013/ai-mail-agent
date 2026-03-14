"""AI Mail Agent — CLI entrypoint.

Usage:
    py -3.11 agent.py -t 0    # Process emails from now onwards
    py -3.11 agent.py -t 1    # Process emails from 1 hour ago
    py -3.11 agent.py -t 3    # Process emails from 3 hours ago
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import logging

from src.config import get_settings
from src.utils.logger import setup_logger
from src.utils.cost_tracker import CostTracker
from src.mail.gmail_client import GmailClient
from src.mail.parser import parse_email_to_input
from src.graph.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class MailAgent:
    """Main mail agent with polling loop.

    Args:
        lookback_hours: Process emails from N hours before start.
    """

    def __init__(self, lookback_hours: float = 0) -> None:
        self.settings = get_settings()
        setup_logger("ai_mail_agent", self.settings.LOG_DIR, self.settings.LOG_LEVEL)

        self.gmail_client = GmailClient(
            credentials_path=self.settings.GMAIL_CREDENTIALS_PATH,
            token_path=self.settings.GMAIL_TOKEN_PATH,
            lookback_hours=lookback_hours,
        )
        self.cost_tracker = CostTracker(self.settings.COST_LOG_PATH)
        self.orchestrator = Orchestrator(self.gmail_client)
        self._running = True
        self._lookback_hours = lookback_hours

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("Received signal %d. Shutting down...", signum)
        self._running = False

    def run(self) -> None:
        """Start the polling loop."""
        from datetime import datetime, timezone

        start_dt = datetime.fromtimestamp(
            self.gmail_client._start_epoch, tz=timezone.utc
        )

        logger.info("=" * 60)
        logger.info("AI Mail Agent started")
        logger.info("Lookback: %s hours", self._lookback_hours)
        logger.info("Processing emails after: %s", start_dt.isoformat())
        logger.info("Poll interval: %ds", self.settings.POLL_INTERVAL_SECONDS)
        logger.info("Monthly budget: $%.2f", self.settings.MAX_MONTHLY_COST_USD)
        logger.info("=" * 60)

        # Ingest RAG data on first run
        self.orchestrator.ingest_data()

        while self._running:
            try:
                if self.cost_tracker.is_budget_exceeded(
                    self.settings.MAX_MONTHLY_COST_USD
                ):
                    logger.warning("Monthly budget exceeded! Pausing 1 hour.")
                    time.sleep(3600)
                    continue

                self._poll_and_process()

                # Sleep in 1-second increments for graceful shutdown
                for _ in range(self.settings.POLL_INTERVAL_SECONDS):
                    if not self._running:
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Unexpected error: %s", e, exc_info=True)
                time.sleep(30)

        logger.info("AI Mail Agent stopped.")

    def _poll_and_process(self) -> None:
        """Poll Gmail and process each new email."""
        logger.info("Polling for new emails...")

        try:
            emails = self.gmail_client.get_unread_emails(
                label=self.settings.GMAIL_WATCH_LABEL,
                max_results=10,
            )
        except Exception as e:
            logger.error("Failed to fetch emails: %s", e)
            return

        if not emails:
            logger.debug("No new emails.")
            return

        logger.info("Found %d new email(s)", len(emails))

        for raw_email in emails:
            try:
                subject = raw_email.get("subject", "(제목 없음)")
                logger.info("Processing: %s", subject)

                result = self.orchestrator.process_email(raw_email)

                # Mark as read
                self.gmail_client.mark_as_read(raw_email["id"])

                # Label based on action
                action = result.get("final_action", "error")
                label_map = {
                    "sent": "AI-Replied",
                    "drafted": "AI-Escalated",
                    "skipped": "AI-Skipped",
                    "error": "AI-Error",
                }
                label = label_map.get(action, "AI-Processed")
                self.gmail_client.add_label(raw_email["id"], label)

                logger.info("Result: %s → label: %s", action, label)

            except Exception as e:
                logger.error("Failed to process email: %s", e, exc_info=True)


def main() -> None:
    """Parse CLI args and start the agent."""
    parser = argparse.ArgumentParser(
        description="AI Mail Agent — 요양시설 이메일 자동 응답",
    )
    parser.add_argument(
        "-t", "--time",
        type=float,
        default=0,
        help="N시간 전 메일부터 처리 (0 = 현재 시점 이후만)",
    )
    args = parser.parse_args()

    agent = MailAgent(lookback_hours=args.time)
    agent.run()


if __name__ == "__main__":
    main()
