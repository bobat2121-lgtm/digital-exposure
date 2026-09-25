"""Show (or persist) the automatic Monday reconciliation for unreviewed weeks.

  python scripts/auto_reconcile.py            # print what the live report derives
  python scripts/auto_reconcile.py --write    # add those entries to data/report-supplements.json

The live report already applies these entries in memory; writing them is only
needed to freeze a week for review. Written entries keep "auto_reconciled": true
until a reviewer replaces them with checked figures.
"""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report import auto_reconcile, live_report  # noqa: E402
from report.filing_monitor import load_monitor_snapshot  # noqa: E402


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    feed = load_monitor_snapshot(force=True).feed or json.loads(live_report.CHECKPOINT.read_text(encoding="utf-8"))
    rows = live_report._merged_filings(feed, live_report._load(live_report.CHECKPOINT))
    committed = live_report._load(live_report.SUPPLEMENTS)
    merged, notes = auto_reconcile.augment(rows, committed)
    added = {ticker: {day: entry for day, entry in dates.items() if entry.get("auto_reconciled")}
             for ticker, dates in merged["balances"].items()}
    print(json.dumps({"notes": notes, "entries": added}, indent=1, default=str))
    if args.write and any(added.values()):
        merged.pop("auto_reconciled_notes", None)
        live_report.SUPPLEMENTS.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {live_report.SUPPLEMENTS}")


if __name__ == "__main__":
    main()
