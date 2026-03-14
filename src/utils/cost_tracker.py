"""API cost tracking — logs token usage and cumulative spend."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CostTracker:
    """Track LLM API costs per calendar month.

    Args:
        log_path: JSON file for persisting cost data.
    """

    # Approximate pricing per 1K tokens (USD)
    _PRICING: dict[str, dict[str, float]] = {
        "gpt-5-nano": {"input": 0.00010, "output": 0.00040},
        "gpt-5.2": {"input": 0.00250, "output": 0.01000},
    }

    def __init__(self, log_path: str = "./logs/cost.json") -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load cost file; starting fresh.")
        return {"months": {}}

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _current_month_key(self) -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m")

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record token usage and return estimated cost (USD).

        Args:
            model: Model name (e.g. 'gpt-5-nano').
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.

        Returns:
            Estimated cost in USD for this call.
        """
        pricing = self._PRICING.get(model, self._PRICING["gpt-5-nano"])
        cost = (
            (input_tokens / 1000) * pricing["input"]
            + (output_tokens / 1000) * pricing["output"]
        )

        month_key = self._current_month_key()
        if month_key not in self._data["months"]:
            self._data["months"][month_key] = {
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "calls": 0,
            }

        entry = self._data["months"][month_key]
        entry["total_cost"] = round(entry["total_cost"] + cost, 6)
        entry["total_input_tokens"] += input_tokens
        entry["total_output_tokens"] += output_tokens
        entry["calls"] += 1

        self._save()
        return cost

    def get_monthly_spend(self) -> float:
        """Return total USD spent in the current month."""
        month_key = self._current_month_key()
        return self._data.get("months", {}).get(month_key, {}).get("total_cost", 0.0)

    def is_budget_exceeded(self, limit_usd: float) -> bool:
        """Return True if the current month's spend exceeds *limit_usd*."""
        return self.get_monthly_spend() >= limit_usd
