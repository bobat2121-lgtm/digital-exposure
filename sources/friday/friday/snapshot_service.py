"""Background-only provider, calculation and chart preparation with JSON cache.

Published snapshots are immutable by contract: callers must not modify the
dict returned by peek() or a Future. peek() reads only a pointer under a short
lock; JSON, copying, provider requests, calculations and disk writes run outside
that lock. Every request submits distinct work, even when another is pending.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from threading import Lock
from time import perf_counter

UTC = timezone.utc
CACHE_SCHEMA = "friday-panel-snapshot"
CACHE_VERSION = 1
MAX_CACHE_BYTES = 20_000_000


class SnapshotRefreshError(RuntimeError):
    """A failed background stage; the last good snapshot remains available."""


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an aware ISO string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(UTC)


def _valid_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("mode") != "latest":
        return False
    if any(type(snapshot.get(key)) is not int or snapshot[key] < 1 for key in ("revision", "request_id")):
        return False
    if snapshot["revision"] != snapshot["request_id"]:
        return False
    data, panel, timings = snapshot.get("data"), snapshot.get("panel"), snapshot.get("timings")
    if not isinstance(data, dict) or data.get("mode") != "latest" or not isinstance(panel, dict) or panel.get("mode") != "latest":
        return False
    if not isinstance(timings, dict):
        return False
    for name in ("fetch_ms", "compute_ms", "prepare_ms", "total_ms"):
        value = timings.get(name)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            return False
    if "charts" in snapshot and not isinstance(snapshot["charts"], (dict, list)):
        return False
    meta = data.get("refresh_meta", {})
    if not isinstance(meta, dict) or any(not isinstance(meta.get(group, {}), dict) for group in ("histories", "indicators")):
        return False
    try:
        _stamp(snapshot.get("updated_at"))
        _stamp(data.get("fetched_at"))
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON number")


class SnapshotService:
    """Persistent last-good Latest snapshot with two bounded worker threads.

    ``fetch`` receives a private copy of previous provider data, or None for a
    first load. The default resolves data.load_latest/data.refresh_latest when
    the job runs. ``compute(data)`` and optional ``prepare(panel)`` also receive
    private inputs. The prepare callback must return JSON chart specs and must
    not call Streamlit. Future.result() is that request's own result; use peek()
    when rendering so an older completed request cannot replace newer data.

    Failures leave peek() and the disk file unchanged. status() exposes the
    failed request and stale flag for explicit UI treatment of retained data.
    """

    def __init__(self, cache_path, *, fetch=None, compute=None, prepare=None):
        self.cache_path = Path(cache_path)
        self._fetch = fetch
        self._compute = compute
        self._prepare = prepare
        self._lock = Lock()
        self._publish_lock = Lock()
        self._snapshot = self._load_cache()
        self._published_id = self._snapshot["request_id"] if self._snapshot else 0
        self._next_id = self._published_id
        self._failed_id = 0
        self._last_error = None
        self._futures = {}
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="friday-snapshot")

    def _load_cache(self):
        try:
            with self.cache_path.open("rb") as file:
                raw = file.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                return None
            envelope = json.loads(raw, parse_constant=_invalid_constant)
            if not isinstance(envelope, dict) or envelope.get("schema") != CACHE_SCHEMA or type(envelope.get("version")) is not int or envelope["version"] != CACHE_VERSION:
                return None
            snapshot = envelope.get("snapshot")
            return snapshot if _valid_snapshot(snapshot) else None
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            return None

    def peek(self):
        """Return the published read-only-by-contract snapshot immediately."""
        with self._lock:
            return self._snapshot

    def status(self):
        """Cheap status for labeling retained snapshots after failed requests."""
        with self._lock:
            stale = self._failed_id > self._published_id
            if self._snapshot:
                meta = self._snapshot["data"].get("refresh_meta", {})
                stale = stale or any(record.get("status") in ("stale_last_good", "unavailable")
                                     for group in (meta.get("histories", {}), meta.get("indicators", {}))
                                     for record in group.values() if isinstance(record, dict))
            return {"pending": len(self._futures), "latest_requested_id": self._next_id,
                    "published_request_id": self._published_id, "failed_request_id": self._failed_id or None,
                    "last_error": dict(self._last_error) if self._last_error else None,
                    "stale": stale, "closed": self._closed}

    @property
    def last_error(self):
        return self.status()["last_error"]

    def request(self) -> Future:
        """Always submit a new provider request and return its Future promptly."""
        with self._lock:
            if self._closed:
                raise RuntimeError("SnapshotService is closed")
            self._next_id += 1
            request_id = self._next_id
            future = self._executor.submit(self._run, request_id)
            self._futures[request_id] = future
        future.add_done_callback(lambda _future: self._finished(request_id))
        return future

    def _finished(self, request_id):
        with self._lock:
            self._futures.pop(request_id, None)

    def _provider(self, previous):
        if self._fetch is not None:
            return self._fetch(previous)
        # Import modules in the job, so tests and application composition can
        # patch the current implementation after construction.
        from friday import data as providers
        return providers.refresh_latest(previous) if previous is not None else providers.load_latest()

    def _calculate(self, data):
        if self._compute is not None:
            return self._compute(data)
        from friday import metrics
        return metrics.compute_panel(data)

    def _run(self, request_id):
        started = perf_counter()
        stage = "fetch"
        try:
            with self._lock:
                prior = self._snapshot
            previous = deepcopy(prior["data"]) if prior else None
            fetched = self._provider(previous)
            if not isinstance(fetched, dict) or fetched.get("mode") != "latest":
                raise ValueError("Only Latest provider data may be cached")
            data = deepcopy(fetched)
            fetched_done = perf_counter()
            stage = "compute"
            panel = self._calculate(deepcopy(data))
            if not isinstance(panel, dict) or panel.get("mode") != "latest":
                raise ValueError("Only a Latest panel may be cached")
            panel = deepcopy(panel)
            for field, value in data.items():
                if field == "sources" or field.endswith("_source") or field.endswith("_source_url") or field == "supply_method":
                    panel[field] = deepcopy(value)
            computed_done = perf_counter()
            stage = "prepare"
            charts = self._prepare(deepcopy(panel)) if self._prepare is not None else None
            prepared_done = perf_counter()
            snapshot = {"mode": "latest", "data": data, "panel": panel,
                        "updated_at": datetime.now(UTC).isoformat(), "revision": request_id, "request_id": request_id,
                        "timings": {"fetch_ms": (fetched_done - started) * 1000,
                                    "compute_ms": (computed_done - fetched_done) * 1000,
                                    "prepare_ms": (prepared_done - computed_done) * 1000,
                                    "total_ms": (prepared_done - started) * 1000}}
            if charts is not None:
                snapshot["charts"] = charts
            stage = "persist"
            return self._publish(snapshot)
        except Exception as exc:
            message = f"Snapshot {stage} failed ({type(exc).__name__}); the last completed snapshot is retained."
            with self._lock:
                if request_id >= self._failed_id and request_id > self._published_id:
                    self._failed_id = request_id
                    self._last_error = {"request_id": request_id, "stage": stage, "message": message}
            raise SnapshotRefreshError(message) from exc

    def _publish(self, snapshot):
        # Only publication/disk ordering is serialized. peek()/request() never
        # wait for JSON encoding, fsync or replace because they use _lock only.
        with self._publish_lock:
            with self._lock:
                current = self._snapshot
                superseded = snapshot["request_id"] <= self._published_id
                if not superseded and current:
                    next_stamp = max(datetime.now(UTC), _stamp(current["updated_at"]) + timedelta(microseconds=1))
                    snapshot["updated_at"] = next_stamp.isoformat()
            if not _valid_snapshot(snapshot):
                raise ValueError("Invalid Latest snapshot schema")
            envelope = {"schema": CACHE_SCHEMA, "version": CACHE_VERSION, "snapshot": snapshot}
            encoded = json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > MAX_CACHE_BYTES:
                raise ValueError("Snapshot cache size limit exceeded")
            # Detach returned JSON specs and any provider-owned nested values.
            frozen = json.loads(encoded)["snapshot"]
            if superseded:
                return frozen
            self._atomic_write(encoded)
            with self._lock:
                self._snapshot = frozen
                self._published_id = frozen["request_id"]
                if self._failed_id <= self._published_id:
                    self._failed_id = 0
                    self._last_error = None
            return frozen

    def _atomic_write(self, encoded):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.cache_path.parent,
                                             prefix="." + self.cache_path.name + ".", suffix=".tmp", delete=False) as file:
                name = file.name
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.cache_path)
            name = None
        finally:
            if name is not None:
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass

    def close(self):
        """Stop accepting requests and wait for running workers (test cleanup)."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
