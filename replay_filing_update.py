"""Run an isolated offline filing rehearsal; does not refresh or publish the app."""
import argparse
import json
from pathlib import Path

from report.filing_replay import process_filing_event, run_rehearsal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("work/filing-replay"))
    parser.add_argument("--input", type=Path, help="Replay one normalized simulation JSON against this directory's published-replay.json")
    args = parser.parse_args()
    if args.input:
        result = process_filing_event(args.input.read_text(encoding="utf-8"), args.output_dir / "published-replay.json")
        passed = result["status"] in ("published", "duplicate")
    else:
        result = run_rehearsal(args.output_dir)
        passed = result["passed"]
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
