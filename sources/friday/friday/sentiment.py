"""CoinMarketCap-only Fear & Greed history and a separate current observation.

The public chart requests /data-api/v3/fear-greed/chart with Unix start/end
dates. The same response contains UTC-midnight historical observations and an
intraday `historicalValues.now` snapshot. The latter never becomes a daily bar.
No API key, account session, synthetic series or Alternative.me fallback is used.
The public website endpoint is not the separately documented Pro API and may
change; malformed or unsuccessful responses fail closed.
"""
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc
SOURCE = "CoinMarketCap"
SOURCE_URL = "https://coinmarketcap.com/charts/fear-and-greed-index/"
API_URL = "https://api.coinmarketcap.com/data-api/v3/fear-greed/chart"
START_DATE = date(2023, 7, 1)
MAX_BYTES = 4_000_000


class CMCSentimentError(ValueError):
    """No validated CoinMarketCap sentiment observation can be supplied."""


def _utc(now):
    now = now or datetime.now(UTC)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CMCSentimentError("Collection time must include a timezone")
    return now.astimezone(UTC)


def _fetch_json(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (FridayPanel/1.0)", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CMCSentimentError("CoinMarketCap response exceeds the size limit")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CMCSentimentError("CoinMarketCap returned an invalid JSON document") from exc


def _score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CMCSentimentError("Invalid CoinMarketCap score")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise CMCSentimentError("Invalid CoinMarketCap score") from exc
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise CMCSentimentError("CoinMarketCap score is outside 0–100")
    return value


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
        raise CMCSentimentError("Invalid CoinMarketCap observation timestamp")
    try:
        stamp = datetime.fromtimestamp(int(value), UTC)
    except (OverflowError, ValueError, OSError) as exc:
        raise CMCSentimentError("Invalid CoinMarketCap observation timestamp") from exc
    if stamp.date() < START_DATE:
        raise CMCSentimentError("CoinMarketCap timestamp precedes index history")
    return stamp


def _bands(config):
    if not isinstance(config, list) or not config:
        raise CMCSentimentError("Missing CoinMarketCap classification bands")
    bands = []
    for row in config:
        if not isinstance(row, dict):
            raise CMCSentimentError("Invalid CoinMarketCap classification bands")
        start, end = _score(row.get("start")), _score(row.get("end"))
        name = row.get("name")
        if end <= start or not isinstance(name, str) or not name.strip():
            raise CMCSentimentError("Invalid CoinMarketCap classification band")
        bands.append({"start": start, "end": end, "name": name})
    bands.sort(key=lambda row: row["start"])
    if bands[0]["start"] != 0 or bands[-1]["end"] != 100 or any(a["end"] != b["start"] for a, b in zip(bands, bands[1:])):
        raise CMCSentimentError("CoinMarketCap classification bands are not continuous")
    return bands


def _observation(item, bands):
    if not isinstance(item, dict):
        raise CMCSentimentError("Invalid CoinMarketCap observation")
    value, stamp = _score(item.get("score")), _timestamp(item.get("timestamp"))
    classification = item.get("name")
    if not isinstance(classification, str) or not classification.strip():
        raise CMCSentimentError("Missing CoinMarketCap classification")
    band = next(row for row in bands if row["start"] <= value and (value < row["end"] or row["end"] == value == 100))
    if classification.strip().casefold() != band["name"].strip().casefold():
        raise CMCSentimentError("CoinMarketCap score and classification disagree")
    return {"date": stamp.date().isoformat(), "value": value, "classification": classification,
            "as_of": stamp.isoformat(), "source_timestamp": stamp.isoformat(), "source": SOURCE}, stamp


def parse_cmc_sentiment(payload, *, now=None, start_date=START_DATE, min_rows=365):
    """Preserve CMC raw scores/classifications; separate current and daily data.

    Historical timestamps are retained exactly and labeled in UTC. A midnight
    UTC date can appear as the prior calendar day on a locally formatted CMC
    page. `start_date`/`min_rows` support bounded parser fixtures; production
    requests always start July 1, 2023 with at least one year of observations.
    """
    now = _utc(now)
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict):
        raise CMCSentimentError("Invalid CoinMarketCap response status")
    if str(payload["status"].get("error_code")) != "0":
        raise CMCSentimentError("CoinMarketCap reported a provider error")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("dataList"), list):
        raise CMCSentimentError("Missing CoinMarketCap history")
    if len(data["dataList"]) > 10_000:
        raise CMCSentimentError("Unexpectedly large CoinMarketCap history")
    bands = _bands(data.get("dialConfig"))
    observations, excluded = {}, 0
    for item in data["dataList"]:
        row, stamp = _observation(item, bands)
        if stamp > now or stamp.time() != time.min:
            excluded += 1
            continue
        if stamp.date() < start_date:
            continue
        if row["date"] in observations:
            raise CMCSentimentError("Duplicate CoinMarketCap historical date")
        observations[row["date"]] = row
    rows = [observations[key] for key in sorted(observations)]
    if not isinstance(min_rows, int) or min_rows < 1 or len(rows) < min_rows or rows[0]["date"] != start_date.isoformat():
        raise CMCSentimentError("CoinMarketCap history is shortened or missing its requested start date")
    notices = []
    latest = None
    historical = data.get("historicalValues")
    current = historical.get("now") if isinstance(historical, dict) else None
    try:
        latest, stamp = _observation(current, bands)
        if stamp > now or stamp < datetime.fromisoformat(rows[-1]["as_of"]):
            raise CMCSentimentError("Current CoinMarketCap timestamp is invalid or older than its history")
    except CMCSentimentError:
        latest = None
        notices.append("CoinMarketCap's current snapshot is unavailable or invalid; its dated daily history is retained.")
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        difference = (date.fromisoformat(current["date"]) - date.fromisoformat(previous["date"])).days
        if difference != 1:
            gaps.append({"after": previous["date"], "before": current["date"]})
    if gaps:
        notices.append(f"CoinMarketCap history has {len(gaps)} date gaps; no missing scores were interpolated.")
    age = (now.date() - date.fromisoformat(rows[-1]["date"])).days
    if age > 3:
        notices.append(f"CoinMarketCap daily history ends {rows[-1]['date']}; this is not a current daily reading.")
    if latest and now - datetime.fromisoformat(latest["as_of"]) > timedelta(days=2):
        notices.append(f"CoinMarketCap's latest snapshot is dated {latest['as_of']}; the source may be stale.")
    recent = [row for row in rows if date.fromisoformat(row["date"]) >= now.date() - timedelta(days=90)]
    extreme = [row for row in recent if row["classification"].strip().casefold() == "extreme greed"]
    return {"rows": rows, "source": SOURCE, "source_url": SOURCE_URL, "sources": [SOURCE_URL, API_URL],
            "latest": latest, "fetched_at": now.isoformat(), "method": "CMC public chart daily history and separate current snapshot",
            "notices": notices, "dial_config": bands,
            "diagnostics": {"observations": len(rows), "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
                            "lag_days": age, "excluded_intraday_current_or_future": excluded, "gaps": gaps,
                            "recent_90d_high": max(recent, key=lambda row: row["value"]) if recent else None,
                            "recent_90d_extreme_greed": extreme}}


def fetch_cmc_sentiment(*, now=None):
    """Retrieve one public CMC response; no other-provider fallback or splice."""
    requested_at = _utc(now)
    query = urlencode({"start": int(datetime.combine(START_DATE, time.min, UTC).timestamp()),
                       "end": int(datetime.combine(requested_at.date(), time.min, UTC).timestamp())})
    url = API_URL + "?" + query
    result = parse_cmc_sentiment(_fetch_json(url), now=_utc(now))
    result["sources"][1] = url
    return result
