"""Pull and archive a labeled one-minute equity VWAP estimate for an edition."""
from argparse import ArgumentParser
from datetime import date

from report.equity_vwap import pull_estimate
from report.vwap_store import save_estimate


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="ASST")
    parser.add_argument("--edition", type=date.fromisoformat, required=True,
                        help="Report date YYYY-MM-DD; all price inputs precede this date")
    parser.add_argument("--window", choices=("auto", "prior_week", "five_sessions"), default="auto")
    args = parser.parse_args()
    try:
        result = pull_estimate(args.symbol.upper(), args.edition, args.window)
        path = save_estimate(result, args.symbol.upper(), args.edition)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"VWAP pull failed; existing saved estimate retained: {exc}\n")
    print(f"{result['symbol']} {result['label']}: USD {result['value']:.8f}")
    print(f"{result['session_start']} through {result['session_end']} · {result['bar_count']:,} bars · {result['window']}")
    print(path)


if __name__ == "__main__":
    main()
