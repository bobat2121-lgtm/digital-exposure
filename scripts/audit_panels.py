"""Independent audit of the Monday, Wednesday and Friday panels.

Recomputes each headline figure from raw inputs, cross-checks it against the
issuers' own published KPIs (strategy.com, Strive's dashboard), and checks
every source's freshness. Writes checks.json and prints a table.

  python scripts/audit_panels.py --out previews          # live data
  python scripts/audit_panels.py --out previews --strict  # exit 1 on any FAIL

Status: PASS (within tolerance), WARN (explainable difference or aging data),
FAIL (wrong, missing or stale beyond its schedule).
"""
from __future__ import annotations

from argparse import ArgumentParser
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import panels  # noqa: E402,F401  (adds sources/friday to sys.path)
from panels import extras as extras_module, friday_preview, monday_preview, wednesday  # noqa: E402
from panels.extras import fred_latest, number  # noqa: E402
from report.calculations import liquid_assets  # noqa: E402

ET = ZoneInfo("America/New_York")
CHECKS: list[dict] = []


def check(panel, key, label, status, value=None, reference=None, detail="", source=""):
    CHECKS.append({"panel": panel, "id": key, "label": label, "status": status, "value": value,
                   "reference": reference, "detail": detail, "source": source})


def compare(panel, key, label, value, reference, tolerance, *, relative=False, detail="", source="", warn_only=False):
    if value is None or reference is None:
        check(panel, key, label, "FAIL", value, reference, "missing value", source)
        return
    gap = abs(value - reference) / abs(reference) if relative and reference else abs(value - reference)
    ok = gap <= tolerance
    status = "PASS" if ok else "WARN" if warn_only else "FAIL"
    suffix = f"gap {gap:.2%}" if relative else f"gap {gap:,.4g}"
    check(panel, key, label, status, round(value, 6), round(reference, 6), (detail + " · " if detail else "") + suffix, source)


def parse_number(text: str | None):
    if text is None:
        return None
    cleaned = str(text).replace("≈", "").replace("$", "").replace(",", "").replace("×", "").replace("sats", "")
    cleaned = cleaned.replace("−", "-").replace("%", "").replace("+", "").strip().split(" ")[0]
    try:
        return float(cleaned)
    except ValueError:
        return None


def business_days(start: date, end: date) -> int:
    days, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days += 1
    return days


def freshness(panel, key, label, stamp, now, max_business_days, source):
    if not stamp:
        check(panel, key, label, "FAIL", None, None, "no timestamp", source)
        return
    day = datetime.fromisoformat(str(stamp)).astimezone(ET).date() if "T" in str(stamp) else date.fromisoformat(str(stamp)[:10])
    lag = business_days(day, now.date())
    status = "PASS" if lag <= max_business_days else "WARN" if lag <= max_business_days + 2 else "FAIL"
    check(panel, key, label, status, str(day), f"≤ {max_business_days} business days", f"{lag} business days old", source)


# ── Monday ──────────────────────────────────────────────────────────────────
def audit_monday(report, monday, extras, rows, now):
    strategy_btc = (extras.get("strategy") or {}).get("btc") or {}
    mstr_kpi = (extras.get("strategy") or {}).get("mstr") or {}
    strive = extras.get("strive") or {}
    views = {company.ticker: company for company in monday.view.companies}
    for company in report.companies:
        t, cur, prior = company.ticker, company.current, company.prior
        view, e = views[t], monday.extras[t]
        price, btc_price = company.stock_price, report.current_btc_price
        liquid = liquid_assets(cur)
        bitcoin = cur.btc_holdings * btc_price
        nav = bitcoin + liquid - cur.debt_principal - cur.preferred_claims
        nav_ps = nav / cur.effective_common_shares
        compare("monday", f"{t}.sats", f"{t} sats per share", parse_number(view.bitcoin.value),
                cur.btc_holdings / cur.effective_common_shares * 1e8, 1, source="BTC held ÷ effective common shares")
        compare("monday", f"{t}.nav_ps", f"{t} NAV per share", parse_number(view.nav_per_share), nav_ps, .006,
                source="(BTC × price + cash − debt − preferred claims) ÷ shares")
        compare("monday", f"{t}.price_nav", f"{t} price / NAV", parse_number(view.price_to_nav), price / nav_ps, .006,
                source="price ÷ NAV per share")
        compare("monday", f"{t}.amplification", f"{t} amplification %", e.amplification_pct,
                (cur.debt_principal + cur.preferred_claims) / bitcoin * 100, .01, source="(debt + preferred) ÷ BTC value")
        raised = (e.common_capital or 0) + (e.preferred_capital or 0)
        compare("monday", f"{t}.raised", f"{t} raised = common + preferred", e.raised, raised, 1, source="ATM common + preferred")
        compare("monday", f"{t}.cash_change", f"{t} cash change", e.liquid_change, liquid - liquid_assets(prior), 1,
                source="liquid assets this week − last week")
        compare("monday", f"{t}.deployed", f"{t} deployed = raised − cash change", e.net_funding, raised - e.liquid_change, 1,
                source="waterfall arithmetic")
        if t == "MSTR":
            annual = number(strategy_btc.get("totalAnnualDividends"))
            compare("monday", "MSTR.btc_kpi", "MSTR BTC held vs strategy.com", cur.btc_holdings, number(strategy_btc.get("btcHoldings")),
                    0, source="api.strategy.com bitcoinKpis.btcHoldings", warn_only=True,
                    detail="strategy.com updates after each purchase; a newer purchase shows as a gap")
            kpi_debt = parse_number(mstr_kpi.get("debt"))
            compare("monday", "MSTR.debt_kpi", "MSTR debt (carried forward) vs strategy.com", cur.debt_principal / 1e6,
                    kpi_debt, .01, relative=True, source="api.strategy.com mstrKpiData.debt ($m)",
                    detail="debt is carried forward from the last reviewed reconciliation")
            cap, uf = parse_number(mstr_kpi.get("marketCap")), number(mstr_kpi.get("ufPrice"))
            if cap and uf:
                compare("monday", "MSTR.shares_kpi", "MSTR shares vs strategy.com market cap ÷ price",
                        cur.effective_common_shares, cap * 1e6 / uf, .002, relative=True, warn_only=True,
                        source="mstrKpiData.marketCap ÷ ufPrice (market cap rounded to $1m)",
                        detail="roll-forward misses non-ATM issuance such as employee awards")
            kpi_pref = parse_number(mstr_kpi.get("pref"))
            compare("monday", "MSTR.pref_kpi", "MSTR preferred claims vs strategy.com preferred notional", cur.preferred_claims / 1e6,
                    kpi_pref, .05, relative=True, source="mstrKpiData.pref ($m)",
                    detail="claims include accrued dividends and STRF's price floor; a new series would open a large gap")
            months = number(strategy_btc.get("usdMonthsOfDividends"))
            compare("monday", "MSTR.usd_cover", "MSTR USD cover months vs strategy.com", e.reserve_months, months, .01,
                    source="bitcoinKpis.usdMonthsOfDividends")
            compare("monday", "MSTR.coverage", "MSTR coverage years vs strategy.com", e.coverage_years,
                    number(strategy_btc.get("totalYearsOfCoverage")), .05, relative=True, warn_only=True,
                    source="bitcoinKpis.totalYearsOfCoverage", detail="BTC price timing differs")
            compare("monday", "MSTR.breakeven", "MSTR BTC break-even vs strategy.com", e.breakeven_pct,
                    number(strategy_btc.get("btcBreakevenArr")), .15, warn_only=True,
                    source="bitcoinKpis.btcBreakevenArr", detail="BTC price timing differs")
            compare("monday", "MSTR.amp_kpi", "MSTR amplification vs strategy.com debt+pref ÷ BTC NAV", e.amplification_pct,
                    number(strategy_btc.get("debtPrefByBN")), 1.5, warn_only=True, source="bitcoinKpis.debtPrefByBN",
                    detail="panel uses liquidation claims incl. accrued dividends; strategy.com uses notional")
            if annual and months:
                reserve_months = liquid / (annual / 12)
                compare("monday", "MSTR.cover_formula", "MSTR (reserve + USD cash) ÷ monthly dividends", reserve_months, months, 1.0,
                        warn_only=True, source="8-K balances ÷ strategy.com annual dividends",
                        detail="8-K balance date vs strategy.com today")
        else:
            balance = company.balance_date if hasattr(company, "balance_date") else None
            balance = next((c.balance_date for c in report.companies if c.ticker == t), None)
            cash_row = next((row for row in strive.get("cash") or [] if row.get("date") == balance), None)
            share_row = next((row for row in strive.get("shares") or [] if row.get("date") == balance), None)
            if cash_row:
                compare("monday", "ASST.cash", "ASST cash vs Strive dashboard", cur.cash, number(cash_row.get("cash")), 1,
                        source="strive.com dashboard cashDebt")
                compare("monday", "ASST.strc_held", "ASST STRC held vs Strive dashboard", cur.marketable_securities,
                        number(cash_row.get("marketable_securities")), .01, relative=True, warn_only=True,
                        source="strive.com dashboard cashDebt", detail="filing fair value vs dashboard mark")
                compare("monday", "ASST.debt", "ASST debt vs Strive dashboard", cur.debt_principal, number(cash_row.get("debt")), 1,
                        source="strive.com dashboard cashDebt")
            else:
                check("monday", "ASST.cash", "ASST cash vs Strive dashboard", "WARN", None, None,
                      f"dashboard has no row dated {balance}", "strive.com dashboard")
            if share_row:
                compare("monday", "ASST.shares", "ASST Class A + B vs Strive dashboard", cur.effective_common_shares,
                        (number(share_row.get("class_a_common")) or 0) + (number(share_row.get("class_b_common")) or 0), 1,
                        source="strive.com dashboard shares")
            trades = [row for row in strive.get("transactions") or [] if row.get("transaction_date") == balance]
            if trades:
                held = number(trades[0].get("total_btc_holdings"))
                compare("monday", "ASST.btc", "ASST BTC held vs Strive dashboard", cur.btc_holdings, held, 1,
                        source="strive.com dashboard transactions")
            period_start = (date.fromisoformat(balance) - timedelta(days=6)).isoformat() if balance else ""
            cost = sum(number(row.get("cost")) or 0 for row in strive.get("transactions") or []
                       if period_start <= (row.get("transaction_date") or "") <= (balance or "") and row.get("type", "").lower() != "sell")
            if cost and e.net_funding is not None:
                other = e.net_funding - cost
                status = "PASS" if -0.02 * cost <= other <= 0.25 * cost else "WARN"
                check("monday", "ASST.deployed_vs_cost", "ASST deployed vs BTC cost (rest = dividends, fees)", status,
                      round(e.net_funding), round(cost), f"other uses {other / 1e6:+.1f}m", "strive.com transactions cost")
            dash_months = number(((strive.get("cash") or [{}])[0]).get("dividend_reserve_months"))
            compare("monday", "ASST.cover", "ASST dividend reserve months vs dashboard", e.reserve_months, dash_months, 0,
                    source="strive.com dashboard")
        # Waterfall: the final bar is deployed funding (BTC plus dividends and other uses).
        check("monday", f"{t}.edition", f"{t} balance date", "PASS" if company.balance_date else "FAIL",
              company.balance_date, None, "", "SEC 8-K feed")
    latest = max(company.balance_date for company in report.companies)
    lag = (now.date() - date.fromisoformat(latest)).days
    check("monday", "edition_age", "Monday edition age", "PASS" if lag <= 9 else "WARN" if lag <= 13 else "FAIL",
          latest, "≤ 9 days", f"{lag} days since the newest balance date", "completeness gate")


# ── Wednesday ───────────────────────────────────────────────────────────────
def audit_wednesday(data, extras, now):
    strategy = (extras.get("strategy") or {}).get("preferreds") or {}
    strive = extras.get("strive") or {}
    heroes = data["heroes"]
    strc = heroes["STRC"]["item"]
    kpi = strategy.get("STRC") or {}
    compare("wednesday", "STRC.eff", "STRC effective yield = rate ÷ price", strc.effective,
            number(kpi.get("currentDividend")) * 100 / number(kpi.get("ufPrice")), .02,
            source="strategy.com strcKpiData currentDividend, ufPrice")
    compare("wednesday", "STRC.eff_kpi", "STRC effective yield vs strategy.com effYield", strc.effective,
            number(kpi.get("effYield")), .02, source="strcKpiData.effYield")
    for series in wednesday.REST:
        item = next(row["item"] for row in data["rest"] if row["item"].ticker == series)
        row_kpi = strategy.get(series) or {}
        compare("wednesday", f"{series}.eff", f"{series} effective yield vs strategy.com", item.effective,
                number(row_kpi.get("effYield")), .02, source=f"{series.lower()}KpiData.effYield")
    paid = sorted((row for row in strive.get("sata_dividends") or [] if row.get("status") == "paid"),
                  key=lambda row: row["payDate"])
    pending = sorted((row for row in strive.get("sata_dividends") or [] if row.get("status") != "paid"),
                     key=lambda row: row["payDate"])
    if paid:
        rate = number(paid[-1]["cashAmount"]) * 252
        compare("wednesday", "SATA.rate", "SATA stated rate = latest daily dividend × 252", data["sata_rate"], rate, .001,
                source="strive.com dashboard preferredDividends")
        change = next((row for row in pending if number(row["cashAmount"]) != number(paid[-1]["cashAmount"])), None)
        check("wednesday", "SATA.next_rate", "SATA announced next rate", "WARN" if change else "PASS",
              f"{number(change['cashAmount']) * 252:.2f}% from {change['payDate']}" if change else "unchanged",
              None, "a scheduled change will move the spread" if change else "pending payments match the current rate",
              "strive.com dashboard preferredDividends (pending)")
    for ticker, hero in heroes.items():
        for label, (_, level) in data["references"]:
            spread = hero["spreads"].get(label)
            expected = (hero["item"].effective - level) * 100 if hero["item"].effective is not None and level is not None else None
            compare("wednesday", f"{ticker}.spread.{label}", f"{ticker} spread over {label}", spread, expected, .5,
                    source="(effective yield − FRED level) × 100")
    adv = heroes["STRC"]["liquidity"].get("adv")
    compare("wednesday", "STRC.adv", "STRC 30-day $ volume vs strategy.com average volume", adv / 1e6 if adv else None,
            parse_number(kpi.get("averageVolume")), .15, relative=True, warn_only=True,
            source="Yahoo close × volume vs strcKpiData.averageVolume ($m)")
    for (label, code) in wednesday.BENCHMARKS:
        day, _ = fred_latest(extras, code)
        freshness("wednesday", f"fred.{code}", f"FRED {code} latest observation", day, now, 2, "fred.stlouisfed.org")
    ledger = data["ledger"]
    check("wednesday", "ledger.weeks", "Flow ledger has four complete filing weeks", "PASS" if len(ledger) == 4 else "FAIL",
          len(ledger), 4, "", "SEC 8-K feed")
    past = [day for day, *_ in data["calendar"] if date.fromisoformat(day) < now.date()]
    check("wednesday", "calendar.future", "Calendar lists only upcoming dates", "FAIL" if past else "PASS", len(past), 0, "", "strategy.com KPIs")
    cover = data["cover"]
    for ticker, item in cover.items():
        weeks = item["weeks"]
        status = "PASS" if len(weeks) >= 4 else "WARN"
        check("wednesday", f"{ticker}.cover_weeks", f"{item['name']} USD cover weekly history", status, len(weeks), "≥ 4",
              f"latest {weeks[-1][0] if weeks else '—'}", item["basis"])


# ── Friday ──────────────────────────────────────────────────────────────────
def audit_friday(panel, derived, dataset, extras, now):
    weekly = derived["weekly"]
    closes = [close for _, close in weekly]
    if len(closes) >= 50:
        compare("friday", "sma50w", "50W SMA of Friday closes", derived["sma50w"], sum(closes[-50:]) / 50, .01,
                source="recomputed from the same Friday closes")
    # RSI via an exponential form (alpha = 1/14) seeded on the first difference.
    if len(closes) > 15:
        diffs = [b - a for a, b in zip(closes, closes[1:])]
        up = down = None
        for value in diffs:
            gain, loss = max(value, 0), max(-value, 0)
            up = gain if up is None else up + (gain - up) / 14
            down = loss if down is None else down + (loss - down) / 14
        rsi = 100 - 100 / (1 + up / down) if down else 100
        compare("friday", "rsi", "Weekly RSI(14) vs exponential form", derived["rsi"], rsi, 3, warn_only=True,
                source="independent smoothing; seeds differ slightly")
    onchain = extras.get("onchain") or {}
    price = (panel.get("header") or {}).get("btc", {}).get("price")
    if onchain.get("realized_price") and price:
        compare("friday", "mvrv", "MVRV vs BTC mark ÷ realized price", onchain.get("mvrv"), price / onchain["realized_price"], .06,
                relative=True, warn_only=True, source="Checkonchain realized price", detail="Checkonchain uses its daily close")
    ext = derived["extension"]
    zone, _ = friday_preview.zone(ext)
    check("friday", "zone", "200W zone matches its extension", "PASS" if zone == derived["zone"] else "FAIL",
          derived["zone"], zone, f"{ext:+.1f}% vs 200W" if ext is not None else "", "zone thresholds 0/50/100/150%")
    counted = {state: sum(1 for *_, s in derived["checklist"] if s == state) for state in ("BULL", "NEUTRAL", "BEAR")}
    check("friday", "tally", "Checklist tally equals its cells", "PASS" if counted == derived["tally"] else "FAIL",
          derived["tally"], counted, "", "derived")
    end = date.fromisoformat(str((panel.get("period") or {}).get("end"))[:10])
    today = now.date()
    last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
    expected = last_friday if (today > last_friday or now.hour >= 16) else last_friday - timedelta(days=7)
    check("friday", "week", "Week shown is the latest completed Friday", "PASS" if end == expected else "WARN",
          str(end), str(expected), "rolls to the current week after 4:00 pm ET Friday", "exchange calendar")
    macro = derived["macro"]
    for key, label in (("dxy", "DXY"), ("tnx", "US 10Y"), ("gap", "Fed funds − 2Y")):
        rows = macro[key]
        freshness("friday", f"macro.{key}", f"{label} latest observation", rows[-1][0] if rows else None, now, 2,
                  "Yahoo" if key != "gap" else "FRED DFF, DGS2")
    for ticker, weeks in derived["turnover"].items():
        latest = weeks[-1]["pct"] if weeks else None
        check("friday", f"turnover.{ticker}", f"{ticker} weekly turnover available", "PASS" if latest is not None else "WARN",
              round(latest, 2) if latest is not None else None, None, "", "Yahoo volume ÷ shares")


def audit_sources(extras, now):
    freshness("sources", "strategy", "strategy.com KPIs", (extras.get("strategy") or {}).get("as_of"), now, 1, "api.strategy.com")
    freshness("sources", "strive", "Strive dashboard", (extras.get("strive") or {}).get("as_of"), now, 1, "strive.com")
    freshness("sources", "onchain", "Checkonchain charts", (extras.get("onchain") or {}).get("as_of"), now, 2, "checkonchain.com")
    for symbol in ("STRC", "SATA", "BTC-USD", "DX-Y.NYB"):
        item = ((extras.get("yahoo") or {}).get(symbol)) or {}
        freshness("sources", f"yahoo.{symbol}", f"Yahoo {symbol}", item.get("as_of"), now, 1, "query1.finance.yahoo.com")
    calendar = extras.get("calendar") or {}
    upcoming = [day for day in calendar.get("fomc") or [] if day >= now.date().isoformat()]
    check("sources", "fomc", "Fed FOMC calendar parsed", "PASS" if upcoming else "FAIL", upcoming[0] if upcoming else None,
          None, f"{len(calendar.get('fomc') or [])} meetings", "federalreserve.gov")
    for ticker, item in (calendar.get("earnings") or {}).items():
        check("sources", f"earnings.{ticker}", f"{ticker} next earnings date", "PASS" if item and not item.get("estimated") else "WARN",
              item.get("date") if item else None, None,
              "Nasdaq estimate; add the confirmed date to data/calendar-events.json" if item and item.get("estimated") else "",
              "api.nasdaq.com")
    stale = extras.get("stale") or []
    check("sources", "snapshot", "No section fell back to the saved snapshot", "FAIL" if stale else "PASS",
          ", ".join(stale) or "none", "none", "", "panels.extras")


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "previews")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any check FAILs")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ET)

    from report.current_prices import pull_current_prices
    from report.filing_monitor import load_monitor_snapshot
    from report.live_report import _load, _merged_filings, CHECKPOINT, resolve_complete_report
    from friday import metrics
    from friday.live_inputs import fetch_snapshot

    extras = extras_module.load_extras()
    try:
        prices = pull_current_prices()
    except Exception:
        from report.current_prices import load_current_prices
        prices = load_current_prices()
        check("sources", "quotes", "Live quotes refreshed", "WARN", None, None, "using saved quotes", "report.current_prices")
    feed = load_monitor_snapshot(force=True).feed or json.loads((ROOT / "data" / "latest-report-filings.json").read_text())
    result = resolve_complete_report(prices, feed)
    report = result.report
    rows = _merged_filings(feed, _load(CHECKPOINT))
    monday = monday_preview.build_preview(report, prices, feed, extras)
    audit_sources(extras, now)

    def guarded(panel, step):
        try:
            step()
        except Exception as exc:  # report the failure as a check instead of stopping the audit
            check(panel, f"{panel}.error", f"{panel.title()} audit ran", "FAIL", None, None, f"{type(exc).__name__}: {exc}", "")

    guarded("monday", lambda: audit_monday(report, monday, extras, rows, now))
    guarded("wednesday", lambda: audit_wednesday(wednesday.build(extras, feed, monday), extras, now))

    def friday_step():
        dataset = fetch_snapshot()
        panel = metrics.compute_panel(dataset)
        audit_friday(panel, friday_preview.derive(panel, dataset, extras, feed), dataset, extras, now)
    guarded("friday", friday_step)

    summary = {status: sum(1 for item in CHECKS if item["status"] == status) for status in ("PASS", "WARN", "FAIL")}
    payload = {"generated_at": now.isoformat(), "summary": summary, "monday_notice": result.notice, "checks": CHECKS}
    (args.out / "checks.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    width = max(len(item["label"]) for item in CHECKS)
    for item in CHECKS:
        print(f"{item['status']:4}  {item['panel']:9} {item['label']:<{width}}  {item['value']!s:>22}  {item['reference']!s:>22}  {item['detail']}")
    print(f"\n{summary}  →  {args.out / 'checks.json'}")
    if args.strict and summary["FAIL"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
