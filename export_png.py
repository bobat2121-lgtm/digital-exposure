"""Export a historical or illustrative Streamlit edition without a browser."""
from argparse import ArgumentParser
from pathlib import Path

from report.png_export import render_png
from report.post_export import render_post_png
from report.presentation import build_report_view
from report.sample_data import sample_report
from report.historical_data import historical_report
from report.current_report import current_report
from report.demo_export import demo_report_view, render_demo_png


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--layout", choices=("post", "detailed", "x-demo"), default="post")
    parser.add_argument("--edition", choices=("current", "historical", "illustrative"), default="current")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = current_report() if args.edition == "current" else historical_report() if args.edition == "historical" else sample_report()
    if args.output is None:
        name = f"monday-capital-report-{report.edition_id}-{args.layout}.png"
        args.output = Path(__file__).parent / name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    view = build_report_view(report)
    if args.layout == "x-demo":
        renderer, view = render_demo_png, demo_report_view(view)
    else:
        renderer = render_post_png if args.layout == "post" else render_png
    args.output.write_bytes(renderer(view))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
