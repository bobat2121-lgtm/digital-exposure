"""Verify an entire candidate edition before the scheduled task publishes it.

python scripts/check_monday_publication.py --live --output-dir <scratch-directory>
Omit --live to validate committed snapshots entirely offline. This command
does not reconcile missing inputs, change source data, or push to GitHub.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report.current_prices import load_current_prices, pull_current_prices
from report.publication_check import publication_check

FEED_URL = "https://capital-report.alatimore06370.workers.dev/api/filings"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.live:
            request = Request(FEED_URL, headers={"User-Agent": "MondayReportPublicationCheck/1.0"})
            with urlopen(request, timeout=25) as response:
                feed = json.load(response)
            prices = pull_current_prices()
        else:
            feed = json.loads((ROOT / "data/latest-report-filings.json").read_text(encoding="utf-8"))
            prices = load_current_prices()
        for name, value in (("feed.json", feed), ("prices.json", prices)):
            (args.output_dir / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary, html, png = publication_check(prices, feed)
        (args.output_dir / "monday.html").write_text(html, encoding="utf-8")
        (args.output_dir / "monday.png").write_bytes(png)
    except Exception as exc:
        summary = {"status": "reconciliation_required", "reason": str(exc)}
        (args.output_dir / "check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary))
        return 1
    (args.output_dir / "check.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
