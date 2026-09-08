"""Refresh once per page session; share only complete fallback snapshots in memory."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from threading import Lock

from .current_prices import load_current_prices, pull_current_prices


@dataclass(frozen=True)
class PriceRefreshResult:
    prices: dict | None
    using_saved_prices: bool = False


class PriceStore:
    """A process-wide fallback, never a cache that skips a new visitor's fetch."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: dict | None = None
        self._generation = 0
        self._latest_generation = 0
        try:
            self._latest = load_current_prices()
        except (OSError, ValueError):
            pass

    def _remember(self, snapshot: dict, generation: int) -> PriceRefreshResult:
        # Both price-source functions return validated, complete UTC snapshots.
        # Ordering uses request starts, since fetched_at records completion.
        with self._lock:
            if generation < self._latest_generation:
                return PriceRefreshResult(deepcopy(self._latest))
            if self._latest is not None and any(
                datetime.fromisoformat(quote["as_of"]) < datetime.fromisoformat(self._latest["quotes"][symbol]["as_of"])
                for symbol, quote in snapshot["quotes"].items()
            ):
                return PriceRefreshResult(deepcopy(self._latest), using_saved_prices=True)
            self._latest = deepcopy(snapshot)
            self._latest_generation = generation
            return PriceRefreshResult(deepcopy(self._latest))

    def refresh(self) -> PriceRefreshResult:
        """Always try existing sources; failures preserve the last good timestamps."""
        with self._lock:
            self._generation += 1
            generation = self._generation
        try:
            fresh = pull_current_prices()
        except (OSError, ValueError, HTTPException):
            with self._lock:
                return PriceRefreshResult(deepcopy(self._latest), using_saved_prices=True)
        return self._remember(fresh, generation)
