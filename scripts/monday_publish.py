"""Publish the Monday Accretion Ledger by itself: save the week the page derives.

The page already builds a new edition in memory from the weekly 8-Ks
(report.auto_reconcile), but it rebuilds it from live sources on every view and
falls back to last week's edition whenever one of them fails. This saves
("freezes") the new week into the repository, in the formats of the reviewed
September 28 update (c3bb16f):

- data/report-supplements.json: the new weeks' automatic entries, still marked
  "auto_reconciled": true, the comparison marks the edition compares against,
  and a new "revision" (2026-10-05.1);
- data/latest-report-filings.json: the verified pair, merged into the checkpoint;
- data/asst-vwap-YYYY-MM-DD.json: Strive's VWAP, through report.vwap_store;
- data/release-prices/YYYY-MM-DD.json: the prices at publication (an archive; no code reads it).

It never writes data/reconciliation-*.json: those stay the reviewed starting point
of Strategy's share roll-forward.

  python scripts/monday_publish.py --summary out.json   # gate, freeze, check (the Action)
  python scripts/monday_publish.py --dry-run            # all of it except writing repository files
  python scripts/monday_publish.py --force              # redo the newest week's automatic entries
  python scripts/monday_publish.py --replay 2026-09-28  # derive a saved week again, print the differences
  python scripts/monday_publish.py --discord out.json --commit-url URL  # the Discord message (JSON)
  python scripts/monday_publish.py --ping-payload       # the setup-test message (JSON)

Runs from .github/workflows/monday-publish.yml. Exits 0 when it published, did a
dry run, is waiting or finds the week already published; 1 when anything failed,
in which case it has written nothing.
"""
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import traceback
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report import auto_reconcile, live_report, vwap_store  # noqa: E402

NEW_YORK = ZoneInfo("America/New_York")
PAGE_URL = "https://digital-credit-report.streamlit.app/?report=monday"
PUBLISH_DAYS = (0, 1)                    # Monday, and Tuesday after an EDGAR holiday
WINDOW = (time(7, 50), time(10, 30))     # New York time
FRESH = timedelta(days=3)                # a pair accepted earlier is not this week's
TICKERS = ("MSTR", "ASST")
NAMES = {"MSTR": "Strategy", "ASST": "Strive"}
REQUIRED = {"MSTR": ("effective_common_shares", "debt_principal", "preferred_claims_usd", "preferred_claims_eur"),
            "ASST": ("debt_principal", "preferred_claims_usd", "preferred_claims_eur")}
# --replay: how close a derived figure must come to the reviewed one.
TOLERANCE = {"preferred_claims_usd": 0.005, "preferred_claims_eur": 0.005, "debt_principal": 0,
             "effective_common_shares": 10_000}


class PublishError(Exception):
    """The edition cannot be saved; nothing was written."""


@dataclass(frozen=True)
class Gate:
    state: str                 # "publish", "waiting" or "already published"
    reason: str
    pair: dict | None = None   # ticker -> validated feed row
    redo: bool = False         # --force on a week that is already saved


def in_window(now: datetime) -> bool:
    """Monday or Tuesday, 7:50-10:30 am New York time, daylight or standard."""
    local = now.astimezone(NEW_YORK)
    return local.weekday() in PUBLISH_DAYS and WINDOW[0] <= local.time() <= WINDOW[1]


def _short(day: str) -> str:
    parsed = date.fromisoformat(day)
    return f"{parsed:%b} {parsed.day}"


def _week(row) -> str:
    start = date.fromisoformat(row["extracted"]["periodStart"])
    return (start - timedelta(days=start.weekday())).isoformat()


def _awaiting(feed: dict, since: str) -> list:
    """Filings the page holds the edition back for (live_report's rule): an amendment, or
    a filing still being fetched, parsed or validated."""
    return [row for row in feed.get("filings", []) if isinstance(row, dict) and row.get("ticker") in TICKERS
            and isinstance(row.get("filedDate"), str) and row["filedDate"] >= since
            and (row.get("form") == "8-K/A" or row.get("status") in ("pending", "partial", "document_error")
                 or (row.get("status") == "ready_for_review" and not live_report._eligible(row)))]


def gate(feed: dict, supplements: dict, now: datetime, *, force: bool = False) -> Gate:
    """Go ahead only for validated 8-Ks from both companies, newer than the saved balances and
    accepted in the last three days, so no holiday calendar is needed (a Tuesday after an EDGAR
    holiday simply has Tuesday filings). ``force`` redoes a saved week and ignores the three days."""
    newest = {}
    for row in live_report._merged_filings(feed, {}):
        if row["ticker"] not in newest or row["extracted"]["balanceDate"] > newest[row["ticker"]]["extracted"]["balanceDate"]:
            newest[row["ticker"]] = row
    missing = [NAMES[ticker] for ticker in TICKERS if ticker not in newest]
    if missing:
        return Gate("waiting", f"no validated weekly 8-K from {' or '.join(missing)} in the feed")
    saved = {ticker: max(supplements.get("balances", {}).get(ticker, {}), default="") for ticker in TICKERS}
    dates = " · ".join(f"{NAMES[ticker]} {_short(newest[ticker]['extracted']['balanceDate'])}" for ticker in TICKERS)
    new = [ticker for ticker in TICKERS if newest[ticker]["extracted"]["balanceDate"] > saved[ticker]]
    if not new and not force:
        return Gate("already published", f"{dates} saved")
    if new and len(new) < len(TICKERS):
        other = next(NAMES[ticker] for ticker in TICKERS if ticker not in new)
        return Gate("waiting", f"{' and '.join(NAMES[ticker] for ticker in new)} filed; {other}'s weekly 8-K not yet validated")
    if len({_week(row) for row in newest.values()}) > 1:
        return Gate("waiting", f"{dates}: the newest 8-Ks cover different weeks")
    oldest = min(auto_reconcile.released_at(row) or datetime.min.replace(tzinfo=UTC) for row in newest.values())
    if not force and oldest < now - FRESH:
        return Gate("waiting", f"{dates}: accepted more than three days ago; publish it with --force")
    held = _awaiting(feed, max(row["filedDate"] for row in newest.values()))
    if held:
        return Gate("waiting", f"{dates}: {len(held)} newer filing(s) await validation "
                               f"({', '.join(row.get('accession', '?') for row in held)})")
    return Gate("publish", dates, dict(newest), redo=not new)


def _prior_date(row, rows) -> str | None:
    """The balance a filing compares against, as live_report._company finds it."""
    extraction = row["extracted"]
    if extraction.get("priorBalanceDate"):
        return extraction["priorBalanceDate"]
    earlier = [other["extracted"]["balanceDate"] for other in rows if other["ticker"] == row["ticker"]
               and other["extracted"]["balanceDate"] < extraction["balanceDate"]]
    return max(earlier, default=None)


def _week_keys(pair, rows):
    """[(field, date, symbol or None)]: what one edition saves. Each company's balance entry,
    the comparison marks of the balances it compares against, and Strive's own STRC mark."""
    keys = []
    for ticker, row in pair.items():
        day, prior = row["extracted"]["balanceDate"], _prior_date(row, rows)
        keys.append((f"balances.{ticker}", day, None))
        if ticker == "MSTR" and prior:
            keys += [("comparison_btc_prices", prior, None), ("comparison_release_dates", prior, None),
                     ("balance_marks", prior, "EURUSD=X")]
        if ticker == "ASST":
            keys += [("balance_marks", day, "STRC")] + ([("balance_marks", prior, "STRC")] if prior else [])
    return keys


def _lookup(supplements, key):
    field, day, symbol = key
    table = supplements.get("balances", {}).get(field.split(".")[1], {}) if field.startswith("balances.") else supplements.get(field, {})
    value = table.get(day)
    return value.get(symbol) if symbol and isinstance(value, dict) else value


def strip_week(supplements: dict, pair: dict, rows: list, *, automatic_only: bool = False) -> dict:
    """The supplements without one edition's saved entries (for --force and --replay)."""
    result = deepcopy(supplements)
    for field, day, symbol in _week_keys(pair, rows):
        if field.startswith("balances."):
            ticker = field.split(".")[1]
            entry = result.get("balances", {}).get(ticker, {}).get(day)
            if entry is not None and automatic_only and not entry.get("auto_reconciled"):
                raise PublishError(f"{NAMES[ticker]} {day} has reviewed figures; --force only redoes automatic entries")
            result.get("balances", {}).get(ticker, {}).pop(day, None)
        elif symbol:
            marks = result.get(field, {})
            marks.get(day, {}).pop(symbol, None)
            if day in marks and not marks[day]:
                del marks[day]
        else:
            result.get(field, {}).pop(day, None)
    return result


def missing_fields(supplements: dict, pair: dict, rows: list) -> list[str]:
    """Inputs the edition needs that the supplements lack; a missing figure is never zero."""
    missing = []
    number = live_report._number
    for ticker, row in pair.items():
        day, prior = row["extracted"]["balanceDate"], _prior_date(row, rows)
        balances = supplements.get("balances", {}).get(ticker, {})
        missing += [f"{ticker} {day} {key}" for key in REQUIRED[ticker] if number((balances.get(day) or {}).get(key)) is None]
        if not prior:
            missing.append(f"{ticker} prior balance date")
            continue
        missing += [f"{ticker} {prior} {key}" for key in REQUIRED[ticker] if number((balances.get(prior) or {}).get(key)) is None]
        marks = supplements.get("balance_marks", {}).get(prior, {})
        if ticker == "MSTR":
            if number(supplements.get("comparison_btc_prices", {}).get(prior)) is None:
                missing.append(f"comparison BTC price for {prior}")
            if not supplements.get("comparison_release_dates", {}).get(prior):
                missing.append(f"comparison release date for {prior}")
            if number(marks.get("EURUSD=X")) is None:
                missing.append(f"EUR/USD mark for {prior}")
        elif (row["extracted"].get("priorFacts") or {}).get("held_strc_shares", 0) > 0 and number(marks.get("STRC")) is None:
            missing.append(f"STRC mark for {prior}")
    return missing


def freeze(supplements: dict, rows: list, pair: dict, *, seed_before: str | None = None) -> tuple[dict, dict]:
    """(supplements with the new weeks' automatic entries, just those entries).

    The same derivation as the page's (auto_reconcile.derive_entries). Any unavailable
    source or missing figure raises, so a partial week is never saved.
    """
    merged, added, notes = auto_reconcile.derive_entries(rows, supplements, seed_before=seed_before)
    failed = [note for note in notes if "unavailable" in note]
    if failed:
        raise PublishError("automatic reconciliation unavailable: " + "; ".join(failed))
    missing = missing_fields(merged, pair, rows)
    if missing:
        raise PublishError("missing inputs: " + ", ".join(missing))
    return merged, added


def bump_revision(revision: str | None, edition: str) -> str:
    """'2026-09-28.1' becomes '2026-10-05.1'; the same edition again becomes '2026-10-05.2'."""
    stem, _, number = (revision or "").partition(".")
    return f"{edition}.{int(number) + 1}" if stem == edition and number.isdigit() else f"{edition}.1"


def merge_checkpoint(checkpoint: dict, pair: dict, now: datetime) -> dict:
    """The verified pair added to the top of the checkpoint, as the reviewed updates did."""
    result = deepcopy(checkpoint)
    known = {row.get("accession") for row in result.get("filings", [])}
    result["filings"] = [deepcopy(pair[ticker]) for ticker in TICKERS if pair[ticker]["accession"] not in known] + result.get("filings", [])
    result["reconciledAt"] = now.astimezone(UTC).isoformat()
    return result


def strive_vwap(pair: dict, *, pull=auto_reconcile.vwap_estimate) -> tuple[dict, bool]:
    """(Strive's VWAP for the edition, whether it still has to be saved). A saved estimate is kept."""
    row = pair["ASST"]
    filed = date.fromisoformat(row["filedDate"])
    saved = vwap_store.load_estimate("ASST", filed)
    if saved is not None:
        return saved, False
    try:
        estimate = dict(pull(filed))
    except Exception as exc:
        raise PublishError(f"Strive VWAP unavailable ({type(exc).__name__}: {exc})") from exc
    estimate["display_note"] = live_report.automatic_vwap_note(estimate)
    try:
        vwap_store.validate_estimate(estimate, "ASST", filed)
    except ValueError as exc:
        raise PublishError(f"Strive VWAP invalid: {exc}") from exc
    if estimate["session_start"] < row["extracted"]["periodStart"] or estimate["session_end"] > row["extracted"]["periodEnd"]:
        raise PublishError("Strive VWAP does not match the filing's activity period")
    return estimate, True


def _dump(value) -> str:
    return json.dumps(value, indent=2, allow_nan=False) + "\n"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class Files:
    """Repository writes that can be undone, so a failed check leaves the tree as it was."""

    def __init__(self):
        self.before: dict[Path, bytes | None] = {}

    def track(self, path: Path) -> Path:
        if path not in self.before:
            self.before[path] = path.read_bytes() if path.exists() else None
        return path

    def write(self, path: Path, text: str) -> None:
        self.track(path).parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def undo(self) -> None:
        for path, data in self.before.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)


def run_check(*, frozen: bool, output_dir: Path | None = None) -> dict:
    """scripts/check_monday_publication.py --live into a folder: its summary and the prices it used.

    ``frozen`` turns the in-memory reconciliation off, so the saved files alone must make
    the newest pair complete, exactly what a view gets when a live source is down.
    """
    with TemporaryDirectory() as scratch:
        folder = Path(output_dir or scratch)
        env = {**os.environ, "DCR_AUTO_RECONCILE": "0" if frozen else "1"}
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_monday_publication.py"), "--live",
                               "--output-dir", str(folder)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
        summary = _read(folder / "check.json")
        if done.returncode != 0 or summary.get("status") != "complete":
            raise PublishError("publication check failed: " + (summary.get("reason") or done.stderr.strip()[-600:] or "no result"))
        return {"summary": summary, "prices": _read(folder / "prices.json")}


def summarize_edition(feed: dict, prices: dict) -> dict:
    """Balance dates, bitcoin bought and money in / money out per company, and Strategy's debt
    heads-up: the edition as the page now shows it."""
    from panels import extras as extras_module, monday_preview
    result = live_report.resolve_complete_report(prices, feed)
    preview = monday_preview.build_preview(result.report, prices, feed, extras_module.load_extras(offline=True))
    companies = {}
    for view in preview.view.companies:
        company = next(item for item in result.report.companies if item.ticker == view.ticker)
        activity = {metric.label: metric.value for metric in view.btc_activity}
        bought = activity.get("Bitcoin Bought", "none")
        sold = activity.get("Bitcoin Sold")
        companies[view.ticker] = {
            "name": company.name, "balance_date": company.balance_date, "balance_label": _short(company.balance_date),
            "bitcoin_bought": bought + (f" (sold {sold})" if sold else ""),
            "money": monday_preview._flows_text(preview.extras[view.ticker]),
        }
    return {"companies": companies, "heads_up": list(result.heads_up), "notice": result.notice}


def publish(*, now: datetime, feed: dict, root: Path = ROOT, dry_run: bool = False, force: bool = False,
            check=run_check, summarize=summarize_edition, pull_vwap=auto_reconcile.vwap_estimate) -> dict:
    """Gate, freeze, check. Returns the result for the workflow; PublishError leaves no file changed."""
    data = root / "data"
    supplements_path, checkpoint_path = data / "report-supplements.json", data / "latest-report-filings.json"
    supplements, checkpoint = _read(supplements_path), _read(checkpoint_path)
    decision = gate(feed, supplements, now, force=force)
    if decision.state != "publish":
        return {"status": decision.state, "reason": decision.reason}
    pair = decision.pair
    rows = live_report._merged_filings(feed, checkpoint)
    base = strip_week(supplements, pair, rows, automatic_only=True) if decision.redo else supplements
    merged, added = freeze(base, rows, pair)
    edition = max(row["filedDate"] for row in pair.values())
    merged["revision"] = bump_revision(supplements.get("revision"), edition)
    estimate, new_vwap = strive_vwap(pair, pull=pull_vwap)
    result = {"status": "dry run" if dry_run else "published", "reason": decision.reason, "edition": edition,
              "revision": merged["revision"], "added": added, "vwap": round(estimate["value"], 4),
              "commit_message": f"Publish automatic Monday edition {edition}",
              "expect": ",".join(f"{ticker}={_short(pair[ticker]['extracted']['balanceDate'])}" for ticker in TICKERS)}
    if dry_run:
        checked = check(frozen=False)  # the in-memory edition, as the page shows it now
        result["check"] = checked["summary"]
        return result
    files = Files()
    try:
        files.write(supplements_path, _dump(merged))
        files.write(checkpoint_path, _dump(merge_checkpoint(checkpoint, pair, now)))
        if new_vwap:
            filed = date.fromisoformat(pair["ASST"]["filedDate"])
            files.track(vwap_store.estimate_path("ASST", filed))
            vwap_store.save_estimate(estimate, "ASST", filed)
        checked = check(frozen=True)
        files.write(data / "release-prices" / f"{edition}.json", _dump(checked["prices"]))
        edition_summary = summarize(feed, checked["prices"])
        shown = {ticker: company["balance_date"] for ticker, company in edition_summary["companies"].items()}
        if shown != {ticker: row["extracted"]["balanceDate"] for ticker, row in pair.items()}:
            raise PublishError(f"the page would show {shown}, not the new pair")
    except Exception:
        files.undo()
        raise
    result.update(edition_summary, check=checked["summary"], files=sorted(path.relative_to(root).as_posix() for path in files.before))
    return result


def replay(edition: str, *, root: Path = ROOT, pull_vwap=auto_reconcile.vwap_estimate) -> dict:
    """Derive a saved edition again, as the Action would have, and compare it with what is saved.

    That week's entries are removed in memory, with everything saved later, and Strategy's
    shares roll forward from the reconciliation files before that edition.
    """
    date.fromisoformat(edition)
    data = root / "data"
    supplements, checkpoint = _read(data / "report-supplements.json"), _read(data / "latest-report-filings.json")
    rows = [row for row in live_report._merged_filings(checkpoint, {}) if row["filedDate"] <= edition]
    pair = {}
    for ticker in TICKERS:
        matches = [row for row in rows if row["ticker"] == ticker and row["filedDate"] == edition]
        if not matches:
            raise PublishError(f"no validated {NAMES[ticker]} weekly 8-K filed on {edition} in the checkpoint")
        pair[ticker] = max(matches, key=lambda row: row["extracted"]["balanceDate"])
    newest = max(row["extracted"]["balanceDate"] for row in pair.values())
    then = deepcopy(supplements)
    for ticker in TICKERS:
        then.get("balances", {})[ticker] = {day: entry for day, entry in then.get("balances", {}).get(ticker, {}).items()
                                            if day <= pair[ticker]["extracted"]["balanceDate"]}
    # Marks on this week's balance dates or later were written by later editions.
    for field in ("comparison_btc_prices", "comparison_release_dates", "balance_marks"):
        then[field] = {day: value for day, value in then.get(field, {}).items() if day < newest}
    stripped = strip_week(then, pair, rows)
    merged, _, notes = auto_reconcile.derive_entries(rows, stripped, seed_before=edition)
    seed = auto_reconcile._seed(edition)
    comparisons, derived_only = [], {}
    for key in _week_keys(pair, rows):
        saved, derived = _lookup(supplements, key), _lookup(merged, key)
        label = " ".join(part for part in (key[0].removeprefix("balances."), key[1], key[2]) if part)
        if isinstance(saved, dict) or isinstance(derived, dict):
            for field in sorted(set(saved or {}) | set(derived or {})):
                if field in TOLERANCE:
                    comparisons.append(_compare(f"{label} {field}", (saved or {}).get(field), (derived or {}).get(field), TOLERANCE.get(field)))
        elif saved is None:
            derived_only[label] = derived
        else:
            comparisons.append(_compare(label, saved, derived, None))
    filed = date.fromisoformat(pair["ASST"]["filedDate"])
    saved_vwap = vwap_store.load_estimate("ASST", filed)
    try:
        fresh = pull_vwap(filed)
        derived_vwap = {"value": fresh["value"], "method": fresh["method"]}
    except Exception as exc:
        derived_vwap = {"error": f"{type(exc).__name__}: {exc}"}
    if saved_vwap:
        comparisons.append(_compare(f"ASST VWAP {filed} ({saved_vwap['method']} saved, {derived_vwap.get('method', '—')} now)",
                                    saved_vwap["value"], derived_vwap.get("value"), None))
    checked = [item for item in comparisons if item["within_tolerance"] is not None]
    return {"edition": edition, "seed": seed["source"] if seed else None, "notes": notes,
            "comparisons": comparisons, "derived_only": derived_only, "vwap_now": derived_vwap,
            "within_tolerance": bool(checked) and all(item["within_tolerance"] for item in checked) and not
            any("unavailable" in note for note in notes)}


def _compare(label, saved, derived, tolerance) -> dict:
    numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (saved, derived))
    difference = derived - saved if numeric else None
    within = None if tolerance is None else (numeric and abs(difference) <= tolerance)
    return {"field": label, "saved": saved, "derived": derived, "difference": difference,
            "tolerance": tolerance, "within_tolerance": within}


def discord_payload(summary: dict, *, commit_url: str) -> dict:
    """One embed for the webhook: balance dates, bitcoin bought, money in / money out, the debt
    heads-up and links. ``allowed_mentions`` is empty, so nothing in it can ping anyone."""
    companies = summary["companies"]
    fields = [{"name": f"{companies[ticker]['name']} · bitcoin bought", "value": companies[ticker]["bitcoin_bought"], "inline": True}
              for ticker in TICKERS]
    fields += [{"name": f"{companies[ticker]['name']} · money in / money out", "value": companies[ticker]["money"], "inline": False}
               for ticker in TICKERS]
    fields += [{"name": "Strategy debt heads-up", "value": note, "inline": False} for note in summary.get("heads_up") or []]
    links = f"[Accretion Ledger]({PAGE_URL})" + (f" · [commit]({commit_url})" if commit_url else "")
    fields.append({"name": "Links", "value": links, "inline": False})
    for field in fields:
        field["value"] = field["value"][:1024] or "—"
    return {"embeds": [{
        "title": "📘 Accretion Ledger updated", "url": PAGE_URL, "color": 0x2F6FB0,
        "description": (f"Strategy balance {companies['MSTR']['balance_label']} · Strive balance "
                        f"{companies['ASST']['balance_label']} · automatic reconciliation from the 8-Ks"),
        "fields": fields,
    }], "allowed_mentions": {"parse": []}}


def ping_payload() -> dict:
    return {"embeds": [{
        "title": "Setup test — Monday publish workflow (no new edition)", "url": PAGE_URL, "color": 0x8A8F98,
        "description": "The Monday publish GitHub Action can reach this channel. Nothing was published.",
    }], "allowed_mentions": {"parse": []}}


def load_feed() -> dict | None:
    from report.filing_monitor import load_monitor_snapshot
    return load_monitor_snapshot(force=True).feed


def _write_summary(path: Path | None, result: dict) -> None:
    if path:
        path.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = ArgumentParser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="do everything except write repository files")
    parser.add_argument("--force", action="store_true", help="redo a week that is already saved (automatic entries only)")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", help="derive that saved edition again and print the differences")
    parser.add_argument("--ignore-window", action="store_true", help="run outside Mon/Tue 7:50-10:30 am New York (manual runs)")
    parser.add_argument("--summary", type=Path, help="write the result for the workflow here")
    parser.add_argument("--check-dir", type=Path, help="keep the publication check's HTML and PNG here")
    parser.add_argument("--discord", type=Path, metavar="SUMMARY", help="print the Discord message for a published summary")
    parser.add_argument("--commit-url", default="")
    parser.add_argument("--ping-payload", action="store_true", help="print the setup-test Discord message")
    args = parser.parse_args(argv)

    if args.ping_payload:
        print(json.dumps(ping_payload(), ensure_ascii=False))
        return 0
    if args.discord:
        print(json.dumps(discord_payload(json.loads(args.discord.read_text(encoding="utf-8")), commit_url=args.commit_url),
                         ensure_ascii=False))
        return 0
    if args.replay:
        try:
            outcome = replay(args.replay)
        except (PublishError, ValueError) as exc:
            print(f"replay failed: {exc}")
            return 1
        for item in outcome["comparisons"]:
            flag = {True: "ok", False: "OUTSIDE TOLERANCE", None: "info"}[item["within_tolerance"]]
            difference = "—" if item["difference"] is None else f"{item['difference']:,.6g}"
            print(f"{item['field']:<58} saved {item['saved']!s:>22}  derived {item['derived']!s:>22}  diff {difference:>12}  {flag}")
        print(json.dumps({key: outcome[key] for key in ("edition", "seed", "notes", "derived_only", "vwap_now", "within_tolerance")},
                         indent=1, default=str))
        return 0 if outcome["within_tolerance"] else 1

    now = datetime.now(UTC)
    if not args.ignore_window and not in_window(now):
        result = {"status": "outside window", "reason": "runs Mon/Tue 7:50-10:30 am New York time"}
    else:
        feed = load_feed()
        if not feed:
            result = {"status": "waiting", "reason": "the filing feed is unavailable"}
        else:
            try:
                result = publish(now=now, feed=feed, dry_run=args.dry_run, force=args.force,
                                 check=lambda frozen: run_check(frozen=frozen, output_dir=args.check_dir))
            except Exception as exc:  # PublishError, or anything unexpected: nothing was written
                if not isinstance(exc, PublishError):
                    traceback.print_exc()
                result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}" if not isinstance(exc, PublishError) else str(exc)}
    _write_summary(args.summary, result)
    print(f"{result['status']}: {result.get('reason', '')}")
    if result["status"] in ("published", "dry run"):
        print(json.dumps({key: value for key, value in result.items() if key not in ("status", "reason")}, indent=1, default=str))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
