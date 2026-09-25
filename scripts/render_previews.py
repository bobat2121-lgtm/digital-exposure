"""Render the Monday, Wednesday and Friday preview panels and an audit file.

Examples:
  python scripts/render_previews.py --out previews
  python scripts/render_previews.py --out previews --save-extras   # refresh data/preview-extras.json
  python scripts/render_previews.py --out previews --offline       # saved inputs, demo Friday week
  python scripts/render_previews.py --out previews --themes neon,classic,orbit --layouts a,b,c

Writes monday.png, wednesday.png, friday.png and audit.json (every displayed
key value with its source, plus the page footnotes) so a scheduled auditor can
check them as text. Other styles are written as monday-<theme>.png, other
Monday layouts as monday-<layout>.png.
"""
from argparse import ArgumentParser
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import panels  # noqa: E402,F401  (adds sources/friday to sys.path)
from panels import extras as extras_module, friday_preview, monday_preview, themes, wednesday  # noqa: E402
from report.current_prices import load_current_prices, pull_current_prices  # noqa: E402
from report.live_report import resolve_complete_report  # noqa: E402


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "previews")
    parser.add_argument("--offline", action="store_true", help="Use saved prices, committed filings and demo Friday data")
    parser.add_argument("--save-extras", action="store_true", help="Save the fetched extras as the offline snapshot")
    parser.add_argument("--themes", default=themes.DEFAULT.key, help="Comma-separated: " + ", ".join(themes.THEMES))
    parser.add_argument("--layouts", default="b", help="Monday funding layouts: a (headline), b (ledger), c (waterfall)")
    args = parser.parse_args()
    chosen = [themes.get(key.strip()) for key in args.themes.split(",") if key.strip()]
    layouts = {"a": "headline", "b": "ledger", "c": "waterfall"}
    chosen_layouts = [key.strip() for key in args.layouts.split(",") if key.strip() in layouts] or ["b"]

    def name(day, theme, layout="b"):
        suffix = ("" if theme.key == themes.DEFAULT.key else f"-{theme.key}") + ("" if layout == "b" else f"-{layout}")
        return f"{day}{suffix}.png"
    args.out.mkdir(parents=True, exist_ok=True)

    extras = extras_module.load_extras(offline=args.offline)
    if args.save_extras and not extras["stale"]:
        extras_module.save_snapshot(extras)
    prices = load_current_prices() if args.offline else pull_current_prices()
    feed = json.loads((ROOT / "data" / "latest-report-filings.json").read_text(encoding="utf-8"))
    if not args.offline:
        from report.filing_monitor import load_monitor_snapshot
        feed = load_monitor_snapshot(force=True).feed or feed

    audit = {"rendered_at": datetime.now().astimezone().isoformat(), "stale_sections": extras["stale"], "panels": {}}
    report = resolve_complete_report(prices, feed).report
    monday = monday_preview.build_preview(report, prices, feed, extras)
    overflows = []
    for theme in chosen:
        for layout in chosen_layouts:
            png, missed = monday_preview.render_png(monday, theme, layouts[layout])
            (args.out / name("monday", theme, layout)).write_bytes(png)
            overflows += missed
    audit["panels"]["monday"] = {"overflows": overflows, "values": monday_preview.audit_rows(monday),
                                 "notes": monday_preview.notes(monday)}

    data = wednesday.build(extras, feed, monday)
    overflows = []
    for theme in chosen:
        png, missed = wednesday.render_png(data, theme)
        (args.out / name("wednesday", theme)).write_bytes(png)
        overflows += missed
    audit["panels"]["wednesday"] = {"overflows": overflows, "values": wednesday.audit_rows(data), "notes": wednesday.notes(data)}

    from friday import data as friday_data, metrics
    if args.offline:
        dataset = friday_data.load_demo()
    else:
        from friday.live_inputs import fetch_snapshot
        dataset = fetch_snapshot()
    panel = metrics.compute_panel(dataset)
    derived = friday_preview.derive(panel, dataset, extras, feed)
    overflows = []
    for theme in chosen:
        png, missed = friday_preview.render_png(panel, derived, stale=tuple(extras["stale"]), theme=theme)
        (args.out / name("friday", theme)).write_bytes(png)
        overflows += missed
    audit["panels"]["friday"] = {"overflows": overflows, "values": friday_preview.audit_rows(panel, derived),
                                 "notes": friday_preview.notes(panel, derived, tuple(extras["stale"])), "demo_data": args.offline}

    (args.out / "audit.json").write_text(json.dumps(audit, indent=1), encoding="utf-8")
    print(f"Wrote {len(chosen) * (2 + len(chosen_layouts))} panels and audit.json to {args.out}")
    for name, item in audit["panels"].items():
        if item["overflows"]:
            print(f"{name}: shortened text {item['overflows']}")


if __name__ == "__main__":
    main()
