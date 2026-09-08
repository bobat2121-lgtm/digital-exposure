"""Persist dated price estimates so historical reports never drift to today."""
from datetime import date
import json
from math import isfinite
from pathlib import Path
import re

DATA = Path(__file__).resolve().parents[1] / "data"


def estimate_path(symbol: str, edition: date) -> Path:
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise ValueError("Invalid equity symbol")
    return DATA / f"{symbol.lower()}-vwap-{edition.isoformat()}.json"


def validate_estimate(estimate: dict, symbol: str, edition: date) -> dict:
    if estimate.get("symbol") != symbol or estimate.get("edition_date") != edition.isoformat():
        raise ValueError("Saved VWAP does not match the symbol and historical edition")
    value = estimate.get("value")
    if not isinstance(value, (float, int)) or not isfinite(value) or value <= 0:
        raise ValueError("Saved VWAP must be a positive finite price")
    if estimate.get("method") not in ("hlc3_1m", "hlc3_5m") or not estimate.get("daily"):
        raise ValueError("Saved VWAP is missing its estimation method or daily audit")
    if not (date.fromisoformat(estimate["session_start"]) <= date.fromisoformat(estimate["session_end"]) < edition):
        raise ValueError("Saved VWAP contains dates outside the historical cutoff")
    return estimate


def load_estimate(symbol: str, edition: date) -> dict | None:
    path = estimate_path(symbol, edition)
    if not path.exists():
        return None
    return validate_estimate(json.loads(path.read_text(encoding="utf-8")), symbol, edition)


def save_estimate(estimate: dict, symbol: str, edition: date) -> Path:
    validate_estimate(estimate, symbol, edition)
    path = estimate_path(symbol, edition)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(estimate, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)
    return path
