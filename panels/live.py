"""The page's data sources, refreshed in the background so a page view never waits on them.

Each source keeps its latest good copy. A view gets that copy at once; a copy older than
its time-to-live starts one background refresh (stale-while-revalidate), and a failed
refresh keeps the last good copy. Only a source with no copy yet, the first view after a
restart, waits, and at most ``wait`` seconds, after which the caller falls back to the
committed snapshot while the fetch carries on. ``block`` makes a view wait for a refresh
of a stale copy too: the X image download uses it for prices as of the click.

Views get deep copies, so no page code can change what another visitor sees.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import threading
import time


@dataclass
class _Entry:
    value: object = None
    at: float = 0.0                        # monotonic time of the last good fetch
    thread: threading.Thread | None = None
    error: str = ""


_lock = threading.Lock()
_entries: dict[str, _Entry] = {}


def _refresh(name: str, fetch) -> None:
    try:
        value = fetch()
    except Exception as exc:  # the last good copy stays
        with _lock:
            _entries[name].error = f"{type(exc).__name__}: {exc}"[:300]
        return
    with _lock:
        entry = _entries[name]
        entry.value, entry.at, entry.error = value, time.monotonic(), ""


def get(name: str, fetch, ttl: float, *, wait: float = 10.0, block: bool = False):
    """(copy of the latest value or None, its age in seconds or None)."""
    with _lock:
        entry = _entries.setdefault(name, _Entry())
        stale = entry.value is None or time.monotonic() - entry.at >= ttl
        if stale and (entry.thread is None or not entry.thread.is_alive()):
            entry.thread = threading.Thread(target=_refresh, args=(name, fetch), daemon=True, name=f"live-{name}")
            entry.thread.start()
        thread, missing = entry.thread, entry.value is None
    if thread is not None and thread.is_alive() and (missing or (stale and block)):
        thread.join(wait)
    with _lock:
        entry = _entries[name]
        if entry.value is None:
            return None, None
        return deepcopy(entry.value), time.monotonic() - entry.at


def last(name: str):
    """A copy of the latest good value, or None, without starting a refresh."""
    with _lock:
        entry = _entries.get(name)
        return deepcopy(entry.value) if entry is not None and entry.value is not None else None


def warm(sources: dict) -> None:
    """Start fetching every source that has no copy yet: {name: fetch}. Returns at once."""
    with _lock:
        for name, fetch in sources.items():
            entry = _entries.setdefault(name, _Entry())
            if entry.value is None and (entry.thread is None or not entry.thread.is_alive()):
                entry.thread = threading.Thread(target=_refresh, args=(name, fetch), daemon=True, name=f"live-{name}")
                entry.thread.start()


def expire() -> None:
    """Make every copy stale, so the next view refreshes it (the page's Refresh data button)."""
    with _lock:
        for entry in _entries.values():
            entry.at = 0.0


def status() -> dict:
    """{name: (age in seconds or None, last error)} for the page footer and diagnostics."""
    with _lock:
        now = time.monotonic()
        return {name: (now - entry.at if entry.value is not None else None, entry.error) for name, entry in _entries.items()}
