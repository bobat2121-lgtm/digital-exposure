"""Copy the FRED series behind the panels' benchmarks for the Rates relay Action.

FRED's CSV service stalls for Streamlit Community Cloud, so the live page kept the ICE BofA IG and
HY yields from the committed snapshot, days old. GitHub's runners reach FRED: this script fetches
each series (with retries and a longer timeout than the page allows) and writes fred.json, which
.github/workflows/rates-relay.yml publishes to the `rates` branch. panels.extras.fetch_fred reads
it when FRED does not answer. A series that fails here keeps its previously published copy, with
its original fetch time, so the page can tell a current copy from an old one.

  python scripts/publish_rates.py --out relay
"""
from argparse import ArgumentParser
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panels import extras  # noqa: E402

ATTEMPTS, TIMEOUT = 3, 30


def fetch(series: str) -> list[list]:
    for attempt in range(ATTEMPTS):
        try:
            return extras.fetch_fred_series(series, timeout=TIMEOUT)
        except Exception as exc:
            print(f"{series}: attempt {attempt + 1} failed ({type(exc).__name__}: {exc})")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"FRED {series} unavailable")


def previous() -> dict:
    try:
        return extras._json(extras.FRED_RELAY)
    except Exception:  # first run, or the branch is unreachable
        return {}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "relay")
    args = parser.parse_args()
    before = previous()
    payload = {"schemaVersion": 1, "generated_at": datetime.now(UTC).isoformat(), "source": "fred.stlouisfed.org fredgraph.csv",
               "series": {}, "fetched_at": {}}
    failed = []
    for series in extras.FRED_SERIES:
        try:
            payload["series"][series] = fetch(series)
            payload["fetched_at"][series] = datetime.now(UTC).isoformat()
        except RuntimeError:
            failed.append(series)
            if (before.get("series") or {}).get(series) and (before.get("fetched_at") or {}).get(series):
                payload["series"][series] = before["series"][series]
                payload["fetched_at"][series] = before["fetched_at"][series]
    if not payload["series"]:
        sys.exit("FRED unavailable and no earlier copy: nothing to publish")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "fred.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    for series, rows in payload["series"].items():
        print(f"{series}: {rows[-1][0]} {rows[-1][1]} (fetched {payload['fetched_at'][series]})")
    if failed:
        print("Kept the earlier copy for: " + ", ".join(failed))


if __name__ == "__main__":
    main()
