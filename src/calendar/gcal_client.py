"""Google Calendar client stub — mock implementation for reservation checks.

This module provides the same interface as a real Google Calendar API client
but returns mock data. When a real API key is available, replace the mock
methods with actual API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class GoogleCalendarClient:
    """Google Calendar client (stub — returns mock data).

    When a real API key is configured, this class should be updated to
    call the Google Calendar API.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._connected = bool(api_key)
        if not self._connected:
            logger.info("GoogleCalendarClient: running in mock mode (no API key).")

    def get_available_dates(
        self,
        start_date: datetime | None = None,
        days_ahead: int = 14,
    ) -> list[dict[str, Any]]:
        """Return available visit dates for the next N days.

        Args:
            start_date: Start searching from this date (default: today).
            days_ahead: Number of days to look ahead.

        Returns:
            List of dicts with date, time_slots, and vacancy info.
        """
        if self._connected:
            # TODO: Replace with real API call
            return self._fetch_real_availability(start_date, days_ahead)

        return self._mock_availability(start_date, days_ahead)

    def has_vacancy(self) -> bool:
        """Check if the facility has any available beds/spots.

        Returns:
            True if vacancies exist.
        """
        if self._connected:
            # TODO: Implement real check
            pass

        # Mock: facility has 2 available spots
        return True

    def get_vacancy_count(self) -> int:
        """Return number of available spots.

        Returns:
            Number of open spots.
        """
        if self._connected:
            # TODO: Implement real check
            pass

        return 2

    # ── Mock helpers ─────────────────────────────────────────────

    def _mock_availability(
        self,
        start_date: datetime | None,
        days_ahead: int,
    ) -> list[dict[str, Any]]:
        """Generate mock availability data."""
        base = start_date or datetime.now()
        available: list[dict[str, Any]] = []

        for i in range(days_ahead):
            day = base + timedelta(days=i)
            weekday = day.weekday()

            # No visits on weekends
            if weekday >= 5:
                continue

            # Mock: mornings available Mon/Wed/Fri, afternoons Tue/Thu
            if weekday in (0, 2, 4):
                slots = ["10:00~12:00"]
            else:
                slots = ["14:00~16:00"]

            available.append({
                "date": day.strftime("%Y-%m-%d"),
                "weekday": ["월", "화", "수", "목", "금"][weekday],
                "time_slots": slots,
                "note": "",
            })

        return available

    def _fetch_real_availability(
        self,
        start_date: datetime | None,
        days_ahead: int,
    ) -> list[dict[str, Any]]:
        """Placeholder for real Google Calendar API integration."""
        logger.warning("Real Calendar API not yet implemented; using mock data.")
        return self._mock_availability(start_date, days_ahead)
