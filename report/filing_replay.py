"""Offline, single-writer filing-update rehearsal; no SEC polling or app updates.

The parser consumes a manually normalized JSON fixture, not SEC HTML. Report
valuation inputs are supplied separately by the dated historical reconstruction.
Only the isolated published-replay.json file is an atomic publication target.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import perf_counter
from zoneinfo import ZoneInfo

from .calculations import calculate_company
from .historical_data import historical_report
from .models import CommonCapital, PreferredActivity
from .png_export import render_png
from .post_export import render_post_png
from .presentation import build_report_view


SIMULATION_NOTICE = "OFFLINE SIMULATION: normalized filing fixture; no live SEC ingestion or app publication."
SOURCE_ACCESSION = "0001193125-26-375463"
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm"
FACTS = {
    "btc_holdings": 845_050, "weekly_btc_purchases": 4_603,
    "common_issued_shares": 4_531_421, "common_repurchased_shares": 0,
    "common_issuance_proceeds_usd": 602_800_000, "common_repurchases_cash_usd": 0,
    "strc_issued_shares": 0, "strc_repurchased_shares": 1_557_177,
    "strc_issuance_proceeds_usd": 0, "strc_repurchases_cash_usd": 151_800_000,
    "other_reported_preferred_issued_shares": 0,
    "other_reported_preferred_repurchased_shares": 0,
    "other_reported_preferred_issuance_proceeds_usd": 0,
    "other_reported_preferred_repurchases_cash_usd": 0,
}
REQUIRED_METRICS = ("net_nav", "nav_per_share", "price_to_nav", "net_common_capital",
                    "net_preferred_capital", "effective_common_shares", "sats_per_share",
                    "constant_price_nav_change_pct", "net_btc_amplification", "preferred_to_btc_pct")


def simulated_filing_event() -> dict:
    """Known Aug31 Strategy facts with an explicitly simulated 15-second detection delay."""
    return {
        "schema_version": 1, "simulation": True, "issuer": "MSTR", "cik": "0001050446",
        "accession": SOURCE_ACCESSION, "source_accession": SOURCE_ACCESSION, "source_url": SOURCE_URL,
        "accepted_at": "2026-08-31T12:00:15+00:00",
        "observed_at": "2026-08-31T12:00:30+00:00",
        "period_start": "2026-08-24", "period_end": "2026-08-30",
        "basis": "Manually normalized historical 8-K facts; observation time is simulated.",
        "facts": dict(FACTS),
    }


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Filing timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_event(event: dict) -> dict:
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1 or event.get("simulation") is not True:
        raise ValueError("Only schema-1 explicitly simulated fixtures are accepted")
    if event.get("issuer") != "MSTR" or event.get("cik") != "0001050446":
        raise ValueError("This bounded rehearsal only handles the Strategy fixture")
    accession = event.get("accession", "")
    if not isinstance(accession, str) or not re.fullmatch(r"(?:\d{10}-\d{2}-\d{6}|SIMULATION-[A-Z0-9-]+)", accession):
        raise ValueError("Invalid accession or simulation identifier")
    if event.get("source_accession") != SOURCE_ACCESSION or event.get("source_url") != SOURCE_URL:
        raise ValueError("The rehearsal requires the documented historical source fixture")
    if (event.get("period_start"), event.get("period_end")) != ("2026-08-24", "2026-08-30"):
        raise ValueError("This fixture requires the documented August 24–30 reporting period")
    accepted, observed = _aware(event["accepted_at"]), _aware(event["observed_at"])
    if observed < accepted or accepted.date().isoformat() <= event["period_end"]:
        raise ValueError("Receipt must follow acceptance, after the reporting period")
    facts = event.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(FACTS):
        raise ValueError("Incomplete filing facts: every required count and cash field must be explicit")
    for name, value in facts.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"Invalid nonnegative numeric filing fact: {name}")
        if "shares" in name and value != int(value):
            raise ValueError(f"Share count must be integral: {name}")
    # This particular historical filing has a complete BTC purchase bridge.
    # Production reconciliation must additionally support disposals/transfers.
    if facts["btc_holdings"] != 840_447 + facts["weekly_btc_purchases"]:
        raise ValueError("BTC holdings do not reconcile to the fixture's prior holdings plus purchases")
    for prefix in ("common", "strc", "other_reported_preferred"):
        for count, cash in (("issued_shares", "issuance_proceeds_usd"),
                            ("repurchased_shares", "repurchases_cash_usd")):
            if facts[f"{prefix}_{count}"] == 0 and facts[f"{prefix}_{cash}"] != 0:
                raise ValueError(f"Cash activity with zero {prefix} {count}")
    for field in ("strc_issued_shares", "strc_repurchased_shares",
                  "other_reported_preferred_issued_shares", "other_reported_preferred_repurchased_shares"):
        if facts[field] != FACTS[field]:
            raise ValueError("Changed preferred share activity needs a rebuilt claim schedule; this fixture's supplemental claims are fixed")
    return event


def _candidate(event: dict):
    base = historical_report()
    strategy, strive = base.companies
    f = event["facts"]
    activity = (
        PreferredActivity("STRC", f["strc_issued_shares"], f["strc_repurchased_shares"],
                          issuance_price_assumption=None, capital_method="reported",
                          reported_issuance_proceeds=f["strc_issuance_proceeds_usd"],
                          reported_repurchases_cash=f["strc_repurchases_cash_usd"]),
        PreferredActivity("STRF / STRK / STRD", f["other_reported_preferred_issued_shares"],
                          f["other_reported_preferred_repurchased_shares"], issuance_price_assumption=None,
                          capital_method="reported", reported_issuance_proceeds=f["other_reported_preferred_issuance_proceeds_usd"],
                          reported_repurchases_cash=f["other_reported_preferred_repurchases_cash_usd"]),
    )
    strategy = replace(strategy, current=replace(strategy.current, btc_holdings=f["btc_holdings"]),
                       weekly_btc_purchases=f["weekly_btc_purchases"], preferred_activity=activity,
                       common_capital=CommonCapital(f["common_issuance_proceeds_usd"], f["common_repurchases_cash_usd"],
                                                   issued_shares=f["common_issued_shares"], repurchased_shares=f["common_repurchased_shares"],
                                                   proceeds_basis="Reported ATM proceeds · net of commissions"))
    receipt = _aware(event["observed_at"]).astimezone(ZoneInfo("America/New_York"))
    return replace(base, companies=(strategy, strive), edition_id="offline-filing-replay",
                   data_label="OFFLINE FILING REPLAY · SIMULATION",
                   report_time=f"Simulated {receipt:%b %d, %Y} · {receipt.strftime('%I:%M %p').lstrip('0')} ET",
                   subtitle="Historical filing facts + separately sourced valuation inputs",
                   capital_period_label="Capital · Aug 24–30",
                   footer="OFFLINE SIMULATION · Normalized filing fixture; supplemental balances and prices remain dated historical inputs.")


def _validate_candidate(report) -> dict:
    if tuple(company.ticker for company in report.companies) != ("MSTR", "ASST"):
        raise ValueError("Candidate must contain both expected companies")
    metrics = {}
    for company in report.companies:
        values = asdict(calculate_company(company, report.current_btc_price, report.prior_btc_price))
        for field in REQUIRED_METRICS:
            value = values[field]
            if value is None or not isfinite(value):
                raise ValueError(f"Incomplete candidate: {company.ticker} {field}")
        metrics[company.ticker] = values
    return metrics


def _render_candidate(report) -> dict:
    view = build_report_view(report)
    artifacts = {}
    for label, renderer in (("post", render_post_png), ("detailed", render_png)):
        png = renderer(view)  # Existing renderers check measured text bounds.
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Invalid {label} candidate image")
        artifacts[label] = {"bytes": len(png), "sha256": hashlib.sha256(png).hexdigest()}
    return artifacts


def _read_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("simulation") is not True or state.get("schema_version") != 1 or not isinstance(state.get("applied_accessions"), dict):
        raise ValueError("Existing rehearsal state is invalid; refusing to overwrite it")
    return state


def _atomic_publish(state: dict, path: Path) -> None:
    payload = _canonical(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".filing-replay-", suffix=".tmp", delete=False) as handle:
            pending = Path(handle.name)
            handle.write(payload + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def process_filing_event(raw: str | bytes | dict, state_path: Path) -> dict:
    """Parse, validate, render and atomically publish a complete simulation candidate.

    Identical accessions/content are no-ops. A conflicting body under the same
    accession is rejected; production amendments need explicit version rules.
    """
    started = perf_counter()
    phases = {}
    result = {"simulation": True, "status": "rejected", "notice": SIMULATION_NOTICE, "phase_ms": phases}

    def phase(name, action):
        phase_start = perf_counter()
        try:
            return action()
        finally:
            phases[name] = round((perf_counter() - phase_start) * 1000, 3)

    try:
        path = Path(state_path)
        if path.name != "published-replay.json":
            raise ValueError("Publication target must be the isolated published-replay.json file")
        event = phase("parse_normalized_json", lambda: deepcopy(raw) if isinstance(raw, dict) else json.loads(raw))
        if not isinstance(event, dict):
            raise ValueError("Filing fixture must be a JSON object")
        result["accession"] = event.get("accession")
        event = phase("validate_filing_facts", lambda: _validate_event(event))
        result["simulated_detection_ms"] = (_aware(event["observed_at"]) - _aware(event["accepted_at"])).total_seconds() * 1000
        fingerprint = hashlib.sha256(_canonical({key: value for key, value in event.items() if key != "observed_at"})).hexdigest()
        previous = phase("check_accession", lambda: _read_state(path))
        seen = previous["applied_accessions"] if previous else {}
        if event["accession"] in seen:
            if seen[event["accession"]] != fingerprint:
                raise ValueError("Conflicting content for an already processed accession")
            result.update(status="duplicate", generation=previous["generation"])
        else:
            report = phase("build_candidate", lambda: _candidate(event))
            metrics = phase("validate_complete_candidate", lambda: _validate_candidate(report))
            artifacts = phase("validate_both_png_layouts", lambda: _render_candidate(report))
            state = {
                "schema_version": 1, "simulation": True, "notice": SIMULATION_NOTICE,
                "generation": (previous["generation"] if previous else 0) + 1,
                "applied_accessions": {**seen, event["accession"]: fingerprint},
                "last_accession": event["accession"], "event": event, "report": asdict(report),
                "metrics": metrics, "render_validation": artifacts,
                "supplemental_input_basis": "historical_report(): other balances, shares, valuation estimates, prices and Strive facts; not extracted from this filing.",
            }
            phase("atomic_publish", lambda: _atomic_publish(state, path))
            result.update(status="published", generation=state["generation"], state_path=str(path.resolve()))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        result["error"] = str(exc)
    result["processing_ms"] = round((perf_counter() - started) * 1000, 3)
    if result["status"] == "published":
        result["simulated_release_to_publish_ms"] = result["simulated_detection_ms"] + result["processing_ms"]
    return result


def run_rehearsal(output_dir: Path) -> dict:
    """Run three reproducible scenarios in a fresh isolated subdirectory."""
    directory = Path(output_dir) / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-%fZ")
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "published-replay.json"
    valid = simulated_filing_event()
    invalid = deepcopy(valid)
    invalid["accession"] = "SIMULATION-INCOMPLETE-002"
    del invalid["facts"]["common_issuance_proceeds_usd"]
    (directory / "fixture-valid.json").write_text(json.dumps(valid, indent=2) + "\n", encoding="utf-8")
    (directory / "fixture-invalid.json").write_text(json.dumps(invalid, indent=2) + "\n", encoding="utf-8")
    published = process_filing_event(valid, path)
    good = path.read_bytes() if path.exists() else None
    duplicate = process_filing_event(valid, path)
    duplicate_preserved = good is not None and path.read_bytes() == good
    rejected = process_filing_event(invalid, path)
    rejected_preserved = good is not None and path.read_bytes() == good
    outcomes = [published, duplicate, rejected]
    passed = [item["status"] for item in outcomes] == ["published", "duplicate", "rejected"] and duplicate_preserved and rejected_preserved
    summary = {"simulation": True, "notice": SIMULATION_NOTICE, "passed": passed,
               "output_dir": str(directory.resolve()), "duplicate_preserved_bytes": duplicate_preserved,
               "rejected_preserved_bytes": rejected_preserved, "scenarios": outcomes}
    (directory / "rehearsal-results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = ["# Offline filing-update rehearsal", "", SIMULATION_NOTICE, "",
             "The 15-second detection delay is simulated. Processing durations below were measured locally; no release-to-display service level is established.", "",
             "| Scenario | Result | Local processing (ms) |", "|---|---|---:|"]
    lines.extend(f"| {name} | {outcome['status']} | {outcome['processing_ms']:.3f} |"
                 for name, outcome in zip(("New accession", "Duplicate receipt", "Incomplete new input"), outcomes))
    lines.extend(["", f"Checks passed: **{passed}**. Duplicate preserved bytes: **{duplicate_preserved}**; rejected input preserved bytes: **{rejected_preserved}**.", "",
                  "The published file contains the complete normalized report, calculated metrics, provenance and hashes of both successfully rendered PNGs. It is an isolated simulation artifact; the Streamlit app does not load it.", "",
                  "Detailed phase timings and the simulated end-to-end total are in rehearsal-results.json. Production work remaining is documented in LIVE_UPDATES.md in the repository."])
    (directory / "rehearsal-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
