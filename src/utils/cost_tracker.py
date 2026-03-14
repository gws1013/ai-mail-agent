"""API cost tracking for AI Mail Agent.

Persists token-usage records to a JSON file and provides daily/monthly cost
summaries and budget-exceeded checks.  No external database required.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Model pricing table  (USD per 1 000 tokens, input / output)
# Update these whenever Anthropic publishes new pricing.
# ---------------------------------------------------------------------------
_MODEL_PRICING: dict[str, dict[str, float]] = {
    # claude-sonnet-4-6
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    # claude-haiku-4-5  (lighter / cheaper)
    "claude-haiku-4-5": {"input": 0.00025, "output": 0.00125},
    # claude-opus-4     (escalation model)
    "claude-opus-4": {"input": 0.015, "output": 0.075},
    # Legacy aliases kept for backward compatibility
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-20241022": {"input": 0.00025, "output": 0.00125},
    "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
}

_DEFAULT_DATA_PATH = Path(__file__).parent.parent.parent / "logs" / "cost_tracker.json"


class CostTracker:
    """File-backed tracker for Anthropic API usage and costs.

    All monetary amounts are in USD.  Records are appended to a JSON file so
    that history survives process restarts.  A threading lock ensures safe
    concurrent writes when the agent runs multiple sub-agents in parallel.

    Args:
        data_path: Path to the JSON file used for persistent storage.
            Created (along with parent directories) if it does not exist.
        model_pricing: Optional override for the default pricing table.
            Keys are model IDs; values are dicts with ``"input"`` and
            ``"output"`` keys (USD per 1 000 tokens).
        monthly_budget_usd: Maximum allowed spend in the current calendar
            month.  Used by :meth:`is_budget_exceeded`.

    Example::

        tracker = CostTracker(monthly_budget_usd=50.0)
        tracker.record_usage(model="claude-sonnet-4-6", input_tokens=500, output_tokens=200)
        print(tracker.get_daily_cost())
        print(tracker.is_budget_exceeded())
    """

    def __init__(
        self,
        data_path: Optional[str | Path] = None,
        model_pricing: Optional[dict[str, dict[str, float]]] = None,
        monthly_budget_usd: float = 50.0,
    ) -> None:
        self._path = Path(data_path) if data_path is not None else _DEFAULT_DATA_PATH
        self._pricing: dict[str, dict[str, float]] = {
            **_MODEL_PRICING,
            **(model_pricing or {}),
        }
        self.monthly_budget_usd = monthly_budget_usd
        self._lock = threading.Lock()

        # Ensure storage directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing records into memory
        self._records: list[dict] = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Record a single LLM API call and persist it to disk.

        Args:
            model: Model identifier exactly as returned by the API
                (e.g. ``"claude-sonnet-4-6"``).
            input_tokens: Number of prompt/input tokens consumed.
            output_tokens: Number of completion/output tokens produced.
            timestamp: UTC timestamp for the call.  Defaults to *now*.
            metadata: Optional free-form dict attached to the record
                (e.g. ``{"email_id": "...", "agent": "classifier"}``).

        Returns:
            The newly created record dict (includes computed ``cost_usd``).

        Raises:
            ValueError: If *model* is not in the pricing table.
        """
        if model not in self._pricing:
            raise ValueError(
                f"Unknown model {model!r}. "
                f"Known models: {sorted(self._pricing)}"
            )

        ts = timestamp or datetime.now(tz=timezone.utc)
        cost = self._calculate_cost(model, input_tokens, output_tokens)

        record: dict = {
            "timestamp": ts.isoformat(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost, 8),
            "metadata": metadata or {},
        }

        with self._lock:
            self._records.append(record)
            self._save()

        return record

    def get_daily_cost(self, date: Optional[datetime] = None) -> float:
        """Return total USD cost for a given calendar day (UTC).

        Args:
            date: Day to query.  Defaults to today (UTC).

        Returns:
            Total cost in USD, rounded to 6 decimal places.
        """
        target = (date or datetime.now(tz=timezone.utc)).date()
        total = sum(
            r["cost_usd"]
            for r in self._records
            if datetime.fromisoformat(r["timestamp"]).date() == target
        )
        return round(total, 6)

    def get_monthly_cost(self, year: Optional[int] = None, month: Optional[int] = None) -> float:
        """Return total USD cost for a given calendar month (UTC).

        Args:
            year: 4-digit year.  Defaults to the current UTC year.
            month: 1-based month number.  Defaults to the current UTC month.

        Returns:
            Total cost in USD, rounded to 6 decimal places.
        """
        now = datetime.now(tz=timezone.utc)
        y = year if year is not None else now.year
        m = month if month is not None else now.month
        total = sum(
            r["cost_usd"]
            for r in self._records
            if _record_in_month(r, y, m)
        )
        return round(total, 6)

    def is_budget_exceeded(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> bool:
        """Check whether monthly spending has reached the configured budget.

        Args:
            year: Year to check.  Defaults to current UTC year.
            month: Month to check.  Defaults to current UTC month.

        Returns:
            ``True`` if :meth:`get_monthly_cost` >= ``monthly_budget_usd``.
        """
        return self.get_monthly_cost(year=year, month=month) >= self.monthly_budget_usd

    def get_usage_summary(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> dict:
        """Return a per-model usage breakdown for a calendar month.

        Args:
            year: Year to summarise.  Defaults to current UTC year.
            month: Month to summarise.  Defaults to current UTC month.

        Returns:
            Dict with keys:

            * ``"period"`` – ``"YYYY-MM"`` string.
            * ``"total_cost_usd"`` – aggregate cost.
            * ``"budget_usd"`` – configured monthly limit.
            * ``"budget_remaining_usd"`` – budget minus cost (may be negative).
            * ``"by_model"`` – per-model breakdown dicts with
              ``input_tokens``, ``output_tokens``, ``calls``, ``cost_usd``.
        """
        now = datetime.now(tz=timezone.utc)
        y = year if year is not None else now.year
        m = month if month is not None else now.month

        monthly_records = [r for r in self._records if _record_in_month(r, y, m)]

        by_model: dict[str, dict] = {}
        for r in monthly_records:
            entry = by_model.setdefault(
                r["model"],
                {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_usd": 0.0},
            )
            entry["input_tokens"] += r["input_tokens"]
            entry["output_tokens"] += r["output_tokens"]
            entry["calls"] += 1
            entry["cost_usd"] = round(entry["cost_usd"] + r["cost_usd"], 8)

        total = round(sum(e["cost_usd"] for e in by_model.values()), 6)
        return {
            "period": f"{y:04d}-{m:02d}",
            "total_cost_usd": total,
            "budget_usd": self.monthly_budget_usd,
            "budget_remaining_usd": round(self.monthly_budget_usd - total, 6),
            "by_model": by_model,
        }

    def get_all_records(self) -> list[dict]:
        """Return a shallow copy of all stored usage records.

        Returns:
            List of record dicts ordered by insertion time.
        """
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        """Delete all stored records from memory and disk.

        Warning:
            This operation is irreversible.  Use only in tests or when
            intentionally resetting history.
        """
        with self._lock:
            self._records = []
            self._save()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Compute USD cost for one API call.

        Args:
            model: Model identifier (must be in pricing table).
            input_tokens: Prompt token count.
            output_tokens: Completion token count.

        Returns:
            Cost in USD.
        """
        pricing = self._pricing[model]
        input_cost = (input_tokens / 1_000) * pricing["input"]
        output_cost = (output_tokens / 1_000) * pricing["output"]
        return input_cost + output_cost

    def _load(self) -> list[dict]:
        """Read records from the JSON file.  Returns empty list on missing/corrupt file."""
        if not self._path.exists():
            return []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
            # Handle wrapped format for forward-compat
            return data.get("records", [])
        except (json.JSONDecodeError, OSError):
            # Corrupt file – start fresh but don't delete the original
            backup = self._path.with_suffix(".json.bak")
            self._path.rename(backup)
            return []

    def _save(self) -> None:
        """Atomically write records to disk using a temp file + rename."""
        tmp = self._path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._records, fh, indent=2, ensure_ascii=False)
            # Atomic replace (POSIX) / best-effort on Windows
            tmp.replace(self._path)
        except OSError:
            # Remove incomplete temp file if write failed
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _record_in_month(record: dict, year: int, month: int) -> bool:
    """Return True if *record*'s timestamp falls in the given year/month."""
    ts = datetime.fromisoformat(record["timestamp"])
    return ts.year == year and ts.month == month


# ---------------------------------------------------------------------------
# Convenience singleton factory
# ---------------------------------------------------------------------------

_default_tracker: Optional[CostTracker] = None
_tracker_lock = threading.Lock()


def get_cost_tracker(
    data_path: Optional[str | Path] = None,
    monthly_budget_usd: float = 50.0,
) -> CostTracker:
    """Return the process-wide singleton :class:`CostTracker`.

    The first call initialises the tracker; subsequent calls return the same
    instance regardless of arguments.  This makes it safe to call from any
    module without worrying about duplicate file handles.

    Args:
        data_path: Passed to :class:`CostTracker` on first call only.
        monthly_budget_usd: Passed to :class:`CostTracker` on first call only.

    Returns:
        The singleton :class:`CostTracker` instance.
    """
    global _default_tracker
    if _default_tracker is None:
        with _tracker_lock:
            if _default_tracker is None:
                _default_tracker = CostTracker(
                    data_path=data_path,
                    monthly_budget_usd=monthly_budget_usd,
                )
    return _default_tracker
