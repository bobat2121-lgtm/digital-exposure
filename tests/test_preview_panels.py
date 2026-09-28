"""Offline preview panels: saved extras snapshot, committed filings, demo Friday data."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "sources" / "friday") not in sys.path:
    sys.path.insert(0, str(ROOT / "sources" / "friday"))

from panels import extras as extras_module
from panels import friday_preview, monday_preview, wednesday
from report import live_report
from report.current_prices import load_current_prices
from report.live_report import resolve_live_report

FEED = json.loads((ROOT / "data" / "latest-report-filings.json").read_text())
# The saved dashboard snapshot and assertions describe the September 21 edition.
FEED["filings"] = [row for row in FEED["filings"] if row["filedDate"] <= "2026-09-21"]


def reviewed_report(prices):
    result = resolve_live_report(prices, FEED, through_date="2026-09-20")
    assert result.notice is None, result.notice
    return result.report


def assert_phone_ready(case, png):
    """X shows up to 3:4 uncropped; the type scale assumes a 1440-px width."""
    from io import BytesIO
    from PIL import Image
    image = Image.open(BytesIO(png))
    case.assertEqual(image.width, 1440)
    case.assertLessEqual(image.height / image.width, 4 / 3)


def offline_extras():
    return extras_module.load_extras(offline=True)


class ExtrasTests(unittest.TestCase):
    def test_offline_snapshot_supplies_every_section_marked_stale(self):
        extras = offline_extras()
        for section in extras_module.SECTIONS:
            self.assertIsNotNone(extras[section], section)
        self.assertEqual(sorted(extras["stale"]), sorted(extras_module.SECTIONS))

    def test_failed_section_falls_back_to_snapshot(self):
        def broken():
            raise OSError("offline")
        with patch.dict(extras_module.FETCHERS, {"fred": broken}):
            extras = extras_module.load_extras(("fred",))
        self.assertEqual(extras["stale"], ["fred"])
        self.assertEqual(extras["fred"], extras_module.load_snapshot()["fred"])

    def test_fred_series_fall_back_one_by_one_and_official_sources_extend_them(self):
        # FRED stalls: the rates come from Treasury and the NY Fed on top of the snapshot; IG/HY stay saved.
        def fred(series, keep=420):
            raise TimeoutError("FRED stalled")
        treasury = {"DGS3MO": [("2099-01-02", 4.1)], "DGS2": [("2099-01-02", 3.9)], "DGS10": [("2099-01-02", 4.4)]}
        nyfed = {"SOFR": [("2099-01-02", 4.0)], "DFF": [("2099-01-02", 4.05)]}
        with patch.object(extras_module, "fetch_fred_series", fred), \
             patch.object(extras_module, "fetch_treasury_curve", lambda: treasury), \
             patch.object(extras_module, "fetch_nyfed_rates", lambda: nyfed):
            extras = extras_module.load_extras(("fred",))
        self.assertEqual(extras["stale"], ["fred"])
        self.assertIn("BAMLH0A0HYM2EY", extras["errors"][0])
        self.assertEqual(extras["fred"]["DGS3MO"][-1], ["2099-01-02", 4.1])
        self.assertEqual(extras["fred"]["SOFR"][-1], ["2099-01-02", 4.0])
        saved = extras_module.load_snapshot()["fred"]
        self.assertEqual(extras["fred"]["BAMLC0A0CMEY"], saved["BAMLC0A0CMEY"])
        # FRED back up: no fallback, and an overlay outage changes nothing.
        def down():
            raise OSError("offline")
        with patch.object(extras_module, "fetch_fred_series", lambda series, keep=420: [["2099-01-02", 1.0]]), \
             patch.object(extras_module, "fetch_treasury_curve", down), patch.object(extras_module, "fetch_nyfed_rates", down):
            self.assertEqual(extras_module.fetch_fred()["DGS10"], [["2099-01-02", 1.0]])

    def test_number_rejects_non_numeric(self):
        self.assertIsNone(extras_module.number(True))
        self.assertIsNone(extras_module.number("nan"))
        self.assertEqual(extras_module.number("1,234.5"), 1234.5)


class MondayPreviewTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.report = reviewed_report(self.prices)
        self.preview = monday_preview.build_preview(self.report, self.prices, FEED, offline_extras())

    def test_amplification_uses_each_issuers_own_formula(self):
        strive = next(c for c in self.report.companies if c.ticker == "ASST")
        current = strive.current
        bitcoin = current.btc_holdings * self.report.current_btc_price
        # Strive: its dashboard's Amplification Ratio, (debt + SATA notional) ÷ BTC value (about 50%),
        # kept as exposure, 1 + the ratio (about 1.5×), and shown as the ratio in % (about 50%).
        asst = self.preview.extras["ASST"]
        ratio = (current.debt_principal + current.preferred_claims) / bitcoin
        self.assertAlmostEqual(asst.amplification_pct, ratio * 100)
        self.assertAlmostEqual(asst.amplification_x, 1 + ratio)
        self.assertEqual(monday_preview._amplification(asst)[0], f"{ratio * 100:.0f}%")  # 1.51× reads 51%
        # Same SATA notional as Strive's dashboard, so at its BTC value the ratio is Strive's own figure.
        dashboard = offline_extras()["strive"]["dashboard_amplification"]
        self.assertEqual(current.preferred_claims, dashboard["sata_notional"])
        self.assertAlmostEqual((current.debt_principal + current.preferred_claims) / dashboard["btc_nav"] * 100,
                               dashboard["amplification_pct"])
        # Strategy: its strategy.com KPI, BTC reserve ÷ net BTC reserve.
        strategy = self.preview.extras["MSTR"]
        kpi = offline_extras()["strategy"]["btc"]["amplification"]
        self.assertAlmostEqual(strategy.amplification_x, kpi)
        self.assertEqual(monday_preview._amplification(strategy)[0], f"{(kpi - 1) * 100:.0f}%")
        self.assertTrue(monday_preview._amplification(strategy)[1].endswith(" pp"))

    def test_funding_splits_into_bitcoin_and_dividends(self):
        strategy = self.preview.extras["MSTR"]
        # Sep 14–20: $0 common, −$174.0m STRC, cash and reserve fell $310m.
        self.assertEqual(strategy.liquid_change, -310_000_000)
        self.assertAlmostEqual(strategy.net_funding, 0 - 174_000_000 + 310_000_000)
        # The 8-K: 950 BTC for $75.7m; $57.4m of dividends and interest (the rest is balance rounding).
        self.assertEqual(strategy.btc_cost, 75_700_000)
        self.assertEqual(strategy.stated_dividends, 57_400_000)
        self.assertAlmostEqual(strategy.dividends, 136_000_000 - 75_700_000)
        for extra in self.preview.extras.values():
            self.assertAlmostEqual(extra.btc_cost + extra.dividends, extra.net_funding)
            self.assertFalse(extra.btc_cost_source.startswith("estimate"), extra.ticker)

    def test_filed_bitcoin_cost_wins_over_the_transcribed_history(self):
        company = next(c for c in self.report.companies if c.ticker == "MSTR")
        cost, source = monday_preview._btc_cost("MSTR", company, {"weekly_btc_cost_usd": 1.0, "weekly_btc_purchases": 950},
                                                offline_extras(), self.report.current_btc_price)
        self.assertEqual((cost, source), (1.0, "SEC 8-K aggregate purchase price"))

    def test_unfiled_bitcoin_cost_is_estimated_from_the_weeks_closes(self):
        from dataclasses import replace
        company = next(c for c in self.report.companies if c.ticker == "MSTR")
        later = replace(company, balance_date="2099-01-04", prior_balance_date="2098-12-28")
        extras = {"yahoo": {"BTC-USD": {"rows": [{"date": "2098-12-30", "close": 100.0}, {"date": "2099-01-02", "close": 200.0}]}}}
        cost, source = monday_preview._btc_cost("MSTR", later, {"weekly_btc_purchases": 10}, extras, 1.0)
        self.assertEqual(cost, 10 * 150.0)
        self.assertTrue(source.startswith("estimate"))

    def test_unextracted_cost_basis_rolls_the_prior_filing_forward(self):
        # Sep 27 has no 8-K totals yet: Sep 20's filed $63.80B plus the week's $75.7m, over BTC held.
        from dataclasses import replace
        company = next(c for c in self.report.companies if c.ticker == "MSTR")
        later = replace(company, balance_date="2026-09-27", prior_balance_date="2026-09-20")
        basis, average, source = monday_preview._cost_basis("MSTR", later, {}, offline_extras(),
                                                            (75_700_000, "SEC 8-K aggregate purchase price"))
        self.assertEqual(basis, 63_800_000_000 + 75_700_000)
        self.assertAlmostEqual(average, basis / company.current.btc_holdings)
        self.assertEqual(source, "prior 8-K cost basis + this week's BTC cost")
        _, _, estimated = monday_preview._cost_basis("MSTR", later, {}, offline_extras(), (1.0, "estimate: BTC bought × average"))
        self.assertIn("estimated", estimated)
        # A sale, or no prior filed basis, leaves the box blank rather than guess.
        self.assertEqual(monday_preview._cost_basis("MSTR", later, {"weekly_btc_sales": 5}, offline_extras(), (1.0, "x"))[0], None)
        gap = replace(company, balance_date="2099-01-04", prior_balance_date="2098-12-28")
        self.assertEqual(monday_preview._cost_basis("MSTR", gap, {}, offline_extras(), (1.0, "x"))[0], None)

    def test_warrant_flag_disappears_after_the_deadline(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        late = datetime(2026, 10, 14, 9, tzinfo=ZoneInfo("America/New_York"))
        preview = monday_preview.build_preview(self.report, self.prices, FEED, offline_extras(), now=late)
        self.assertIsNone(preview.extras["ASST"].warrants)
        self.assertIsNotNone(self.preview.extras["ASST"].warrants)

    def test_every_layout_and_style_renders_phone_ready(self):
        # Overflows include any text drawn below the 28-px phone minimum.
        from panels import themes
        for theme in themes.THEMES.values():
            for layout in monday_preview.VARIANTS:
                with self.subTest(theme=theme.key, layout=layout):
                    png, overflows = monday_preview.render_png(self.preview, theme, layout)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)

    def test_live_styles_sign_the_x_image(self):
        from panels import themes, trial_styles
        self.assertEqual(trial_styles.HANDLE, "@WallyXIX")
        for key, signed in (("terminal", True), ("broadsheet", True), ("neon", False)):
            with self.subTest(theme=key), patch.object(trial_styles, "_handle", wraps=trial_styles._handle) as handle:
                monday_preview.render_png(self.preview, themes.get(key))
                self.assertEqual(handle.called, signed)

    def test_bitcoin_cost_box_uses_filed_cost_basis(self):
        strategy, strive = self.preview.extras["MSTR"], self.preview.extras["ASST"]
        # Sep 20 8-K: 846,000 BTC for $63.80B, $75,416 each; Strive's dashboard cost basis.
        self.assertEqual((strategy.cost_basis, strategy.average_cost), (63_800_000_000, 75_416))
        self.assertAlmostEqual(strive.average_cost, strive.cost_basis / 26_355.180562789996, places=6)

    def test_waterfall_labels_cash_by_direction(self):
        # Strategy drew $310m of cash; Strive kept $25.3m of its raise as cash.
        self.assertEqual(monday_preview.cash_step_label(self.preview.extras["MSTR"]), "FROM CASH")
        self.assertEqual(monday_preview.cash_step_label(self.preview.extras["ASST"]), "TO CASH")

    def test_waterfall_shows_money_in_then_money_out(self):
        # Each flow once, with its direction; the two sides add up to the same total.
        flows = {t: monday_preview.funding_flows(e) for t, e in self.preview.extras.items()}
        money_in, money_out = flows["MSTR"]
        self.assertEqual([(label, round(amount)) for label, amount, _ in money_in], [("FROM CASH", 310_000_000)])
        self.assertEqual([label for label, _, _ in money_out], ["STRC BUYBACK", "BTC", "DIVs"])
        self.assertEqual(round(money_out[0][1]), 174_000_000)  # the buyback is money out, not a negative raise
        money_in, money_out = flows["ASST"]
        self.assertEqual([label for label, _, _ in money_in], ["COMMON", "PREF"])
        self.assertEqual([label for label, _, _ in money_out], ["BTC", "DIVs", "TO CASH"])
        for money_in, money_out in flows.values():
            self.assertAlmostEqual(sum(a for _, a, _ in money_in), sum(a for _, a, _ in money_out), places=2)
        self.assertIn("out STRC BUYBACK −$174.0m", monday_preview._flows_text(self.preview.extras["MSTR"]))

    def test_gross_preferred_sold_and_bought_back_are_separate_rows(self):
        from dataclasses import replace
        from report.models import PreferredActivity
        activities = (PreferredActivity("STRC", 500_000, 200_000, capital_method="reported",
                                        reported_issuance_proceeds=50e6, reported_repurchases_cash=20e6),
                      PreferredActivity("STRF", 0, 0, capital_method="reported",
                                        reported_issuance_proceeds=0.0, reported_repurchases_cash=0.0))
        self.assertEqual(monday_preview._preferred_split(activities, 30e6), (50e6, 20e6, ("STRC",)))
        # A net that doesn't match the gross pieces falls back to the net on its side.
        self.assertEqual(monday_preview._preferred_split(activities, 31e6), (31e6, 0.0, ()))
        self.assertEqual(monday_preview._split(-5e6), (0.0, 5e6))
        # A busy week: common and preferred both sold and bought back, cash drawn: seven rows, all legible.
        busy = replace(self.preview.extras["MSTR"], common_in=100e6, common_out=10e6, preferred_in=50e6, preferred_out=20e6,
                       preferred_bought_back=("STRC", "STRF"), liquid_change=-30e6, btc_cost=120e6, dividends=30e6)
        money_in, money_out = monday_preview.funding_flows(busy)
        self.assertEqual([label for label, _, _ in money_in], ["COMMON", "PREF", "FROM CASH"])
        self.assertEqual([label for label, _, _ in money_out], ["MSTR BUYBACK", "PREF BUYBACK", "BTC", "DIVs"])
        preview = replace(self.preview, extras={**self.preview.extras, "MSTR": busy})
        from panels import themes
        for theme in themes.THEMES.values():
            with self.subTest(theme=theme.key):
                _, overflows = monday_preview.render_png(preview, theme)
                self.assertEqual(overflows, [])

    def test_strive_cash_shows_its_strc_portion(self):
        strive = self.preview.extras["ASST"]
        company = next(c for c in self.report.companies if c.ticker == "ASST")
        self.assertIn("STRC", strive.liquid_detail)
        self.assertIn(monday_preview._money(company.current.marketable_securities, False), strive.liquid_detail)

    def test_footnotes_live_on_the_page(self):
        lines = monday_preview.notes(self.preview)
        self.assertTrue(any(line.startswith("Amplification uses each issuer's own formula") for line in lines))
        self.assertTrue(any(line.startswith("Avg cost = aggregate bitcoin purchase price") for line in lines))
        self.assertTrue(any(line.startswith("BTC = the week's bitcoin purchase cost") for line in lines))


class QuoteTests(unittest.TestCase):
    """A strategy.com price is a current trade, an old quote, or a mark nobody traded (STRE)."""

    def test_zero_volume_is_a_mark_and_old_quotes_are_stale(self):
        from datetime import date
        wednesday_ = date(2026, 9, 30)
        stre = {"timeStamp": "09/21/2026 07:50 AM", "sharesVolume": 0, "dailyVolume": "0.0", "averageVolume": "0.0"}
        self.assertEqual(wednesday._quote(stre, wednesday_), ("no_trades", "2026-09-21"))
        fresh = {"timeStamp": "09/30/2026 12:25 PM", "sharesVolume": 19248.4, "dailyVolume": "2.0", "averageVolume": "6.9"}
        self.assertEqual(wednesday._quote(fresh, wednesday_), ("live", "2026-09-30"))
        self.assertEqual(wednesday._quote({**fresh, "timeStamp": "09/29/2026 04:00 PM"}, wednesday_)[0], "live")
        self.assertEqual(wednesday._quote({**fresh, "timeStamp": "09/25/2026 04:00 PM"}, wednesday_), ("stale", "2026-09-25"))
        # Monday looks back to Friday; no volume fields at all is not evidence of no trades.
        self.assertEqual(wednesday._quote({"timeStamp": "09/25/2026 04:00 PM"}, date(2026, 9, 28))[0], "live")
        item = wednesday.Ladder("STRF", 103.6, 10, 9.65, quote="stale", as_of="2026-09-25")
        self.assertEqual(wednesday.quote_tag(item), "LAST SEP 25")
        self.assertEqual(wednesday.quote_tag(wednesday.Ladder("STRE", 80, 10, 12.5, "EUR", "no_trades")), "NOT TRADED")
        self.assertIsNone(wednesday.quote_tag(wednesday.Ladder("STRC", 98.4, 11.5, 11.7)))


class CalendarTests(unittest.TestCase):
    def test_rate_announcements_come_from_their_patterns(self):
        from datetime import date
        # STRC: the month's last business day. SATA: the 15th, or the business day before.
        self.assertEqual(wednesday._rate_announcements(date(2026, 10, 16)),
                         [("2026-10-30", "STRC Nov rate", "rate:STRC"), ("2026-11-13", "SATA rate est.", "rate:SATA")])
        self.assertEqual(wednesday._rate_announcements(date(2026, 12, 20))[0], ("2026-12-31", "STRC Jan rate", "rate:STRC"))

    def test_a_curated_entry_replaces_the_generated_one(self):
        from datetime import date
        events = wednesday._scheduled_events(offline_extras(), date(2026, 9, 28))
        rates = [event for event in events if "rate" in event[1]]
        self.assertEqual(rates, [("2026-09-30", "STRC Oct rate", "curated"), ("2026-10-15", "SATA rate est.", "curated")])
        # After the curated dates pass, the calendar still shows the next ones.
        later = {event[1]: event[0] for event in wednesday._scheduled_events(offline_extras(), date(2026, 10, 16))}
        self.assertEqual((later["STRC Nov rate"], later["SATA rate est."]), ("2026-10-30", "2026-11-13"))

    def test_only_confirmed_earnings_dates_are_shown(self):
        import tempfile
        from datetime import date
        extras = offline_extras()
        extras["calendar"] = {"fomc": [], "earnings": {
            "MSTR": {"date": "2026-10-29", "estimated": True, "source": "nasdaq.com"},
            "ASST": {"date": "2026-11-09", "estimated": False, "source": "nasdaq.com"}}}
        curated = {"events": [
            {"date": "2026-10-30", "label": "MSTR earnings est.", "kind": "earnings", "ticker": "MSTR", "confirmed": False},
            {"date": "2026-11-12", "label": "ASST earnings", "kind": "earnings", "ticker": "ASST", "confirmed": True}]}

        def earnings(events_file):
            with patch.object(wednesday, "EVENTS", events_file):
                return [event for event in wednesday._scheduled_events(extras, date(2026, 10, 1)) if "earnings" in event[1]]

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            path.write_text(json.dumps(curated))
            # Neither estimate appears; ASST's curated confirmed date replaces Nasdaq's.
            self.assertEqual(earnings(path), [("2026-11-12", "ASST earnings", "curated")])
            path.write_text(json.dumps({"events": []}))
            self.assertEqual(earnings(path), [("2026-11-09", "ASST earnings", "earnings")])  # Nasdaq, once confirmed

    def test_nasdaq_estimate_wording_is_recognised(self):
        estimate = ("Strategy Inc Common Stock Class A is estimated to report earnings on  10/29/2026. The upcoming earnings "
                    "date is derived from an algorithm based on a company's historical reporting dates.")
        with patch.object(extras_module, "_json", lambda url: {"data": {"reportText": estimate}}):
            self.assertEqual(extras_module.fetch_earnings("MSTR"), {"date": "2026-10-29", "estimated": True, "source": "nasdaq.com"})
        confirmed = "Strategy Inc Common Stock Class A is expected to report earnings on 10/29/2026 after market close."
        with patch.object(extras_module, "_json", lambda url: {"data": {"reportText": confirmed}}):
            self.assertFalse(extras_module.fetch_earnings("MSTR")["estimated"])


class TypeTests(unittest.TestCase):
    def test_lines_of_one_size_share_a_baseline(self):
        # Pillow's "lt" anchor tops each string's own ink; the canvas puts the capitals' top at y instead.
        from panels.draw import Canvas, cap_height, fontset
        with fontset("terminal"):
            boxes = {}
            for text in ("59", "bull", "HELD", "—"):
                canvas = Canvas((400, 120), "#000")
                canvas.text(10, 40, text, 34, "#fff", True)
                boxes[text] = canvas.image.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
            baseline = 40 + cap_height(34, True)
            for text in ("59", "bull", "HELD"):
                self.assertAlmostEqual(boxes[text][3], baseline, delta=1, msg=text)
            self.assertEqual(boxes["HELD"][1], 40)
            self.assertGreater(boxes["—"][1], 46)  # a dash sits mid-line, not at the capitals' top

    def test_wordmarks_are_recoloured_for_dark_cards(self):
        import numpy as np
        art, middle = monday_preview.logo_art("strive", "#FFFFFF", 32)
        solid = np.asarray(art)
        solid = solid[solid[..., 3] > 250][:, :3]
        self.assertTrue((solid == 255).all(axis=1).any())                   # white letters
        self.assertTrue(((solid[:, 0] > 200) & (solid[:, 2] < 80)).any())  # Strive's orange bar kept
        self.assertFalse((solid.max(axis=1) < 60).any())                    # no black left
        self.assertAlmostEqual(middle, art.height / 2, delta=3)
        strategy, _ = monday_preview.logo_art("strategy", "#FFFFFF", 40)
        self.assertTrue(200 < strategy.width < 220)


class WednesdayTests(unittest.TestCase):
    def test_ladder_sorted_and_panel_renders(self):
        prices = load_current_prices()
        report = reviewed_report(prices)
        monday = monday_preview.build_preview(report, prices, FEED, offline_extras())
        original_load = live_report._load
        with patch.object(live_report, "_load", side_effect=lambda path:
                          FEED if path == live_report.CHECKPOINT else original_load(path)):
            data = wednesday.build(offline_extras(), FEED, monday)
        yields = [item.effective for item in data["ladder"] if item.effective is not None]
        self.assertEqual(yields, sorted(yields, reverse=True))
        sata = next(item for item in data["ladder"] if item.ticker == "SATA")
        self.assertAlmostEqual(sata.effective, sata.rate * 100 / sata.price)
        self.assertEqual(len(data["ledger"]), 4)
        self.assertEqual(data["headline"], "3M bill")
        # Strategy's USD cover reaches back through the transcribed 8-K balances (12 weeks).
        self.assertEqual(len(data["cover"]["MSTR"]["weeks"]), 12)
        self.assertEqual(data["cover"]["MSTR"]["weeks"][0][0], "2026-07-05")
        strc = data["heroes"]["STRC"]
        self.assertAlmostEqual(strc["spreads"]["3M bill"], (strc["item"].effective - data["bill"]) * 100)
        # STRE's €80 is strategy.com's zero-volume mark: yield kept, no spreads, labelled on image and page.
        stre = next(row for row in data["rest"] if row["item"].ticker == "STRE")
        self.assertEqual(stre["item"].quote, "no_trades")
        self.assertTrue(all(value is None for value in stre["spreads"].values()))
        self.assertIn("STRE: no reported trades", " ".join(wednesday.notes(data)))
        from panels import themes
        for theme in themes.THEMES.values():
            for extra in (False, True):
                with self.subTest(theme=theme.key, extra=extra):
                    png, overflows = wednesday.render_png(data, theme, extra=extra)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)
        # strategy.com's STRC floor matches (debt + STRF + STRC notional − USD) ÷ BTC held; SATA uses the same formula.
        self.assertGreater(data["backing"]["STRC"]["floor"], 0)
        self.assertGreater(data["backing"]["SATA"]["floor"], 0)


class FridayPreviewTests(unittest.TestCase):
    def test_indicator_helpers(self):
        self.assertEqual(friday_preview.zone(-5)[0], "VERY CHEAP")
        self.assertEqual(friday_preview.zone(24.7)[0], "CHEAP")
        self.assertEqual(friday_preview.zone(75)[0], "FAIR VALUE")
        self.assertEqual(friday_preview.zone(120)[0], "EXPENSIVE")
        self.assertEqual(friday_preview.zone(400)[0], "VERY EXPENSIVE")
        self.assertEqual(friday_preview._rsi(list(range(1, 40))), 100.0)
        self.assertAlmostEqual(friday_preview._ema([2.0] * 30, 21), 2.0)
        self.assertIsNone(friday_preview._sma([1, 2], 3))

    def test_demo_week_renders_with_every_section(self):
        from friday import data, metrics
        dataset = data.load_demo()
        panel = metrics.compute_panel(dataset)
        derived = friday_preview.derive(panel, dataset, offline_extras(), FEED)
        self.assertEqual(sum(derived["tally"].values()), 7)
        self.assertEqual(set(derived["turnover"]), {"MSTR", "ASST", "STRC", "SATA"})
        self.assertEqual(set(derived["thresholds"]), {label for label, *_ in derived["checklist"]})
        from panels import themes
        for theme in themes.THEMES.values():
            for extra in (False, True):
                with self.subTest(theme=theme.key, extra=extra):
                    png, overflows = friday_preview.render_png(panel, derived, theme=theme, extra=extra)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)
        self.assertTrue(friday_preview.notes(panel, derived))
        markets = derived["markets"]
        self.assertIsNotNone(markets["dvol"])
        self.assertIsNotNone(markets["basis"])
        self.assertIsNotNone(markets["stablecoins"])
        self.assertTrue(any(line.startswith("DVOL = ") for line in friday_preview.notes(panel, derived, extra=True)))


if __name__ == "__main__":
    unittest.main()
