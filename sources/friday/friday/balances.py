"""Vetted issuer inputs available before the Friday reporting cutoff.

Publication dates come from SEC acceptance records, not our retrieval date or
the financial observation date. These are deliberately finite snapshots: new
Monday disclosures require review before entering this Friday model. Amounts
marked estimated are model assumptions, not newly discovered issuer facts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

MSTR_AUG24 = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526361845/mstr-20260824.htm"
MSTR_AUG31 = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm"
MSTR_FWP = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526363557/d431748dfwp.htm"
MSTR_Q2 = "https://www.sec.gov/Archives/edgar/data/1050446/000105044626000044/mstr-20260630.htm"
ASST_AUG24 = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026058518/asst-20260824.htm"
ASST_AUG31 = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm"
ASST_Q2 = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026054985/asst-20260630.htm"
SATA_CERT = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026034802/certi1.htm"
ECB_FX = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2026-08-21&endPeriod=2026-08-28&format=csvdata"

_REPURCHASE_SOURCES = [
    "https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt152e68ca79c6c3e2/6a66cd282ed54801f094c62c/form-8-k_07-27-2026.pdf",
    "https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt4e80364948bf437c/6a6ff89f0da6737125578aab/form-8-k_08-03-2026.pdf",
    "https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt5753b925d6f68e09/6a794ef9dcb43781cc2cf7c3/form-8-k_08-10-2026.pdf",
    "https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt71aa29aaea82420c/6a8208cbc260234bb6b39071/form-8-k_08-17-2026.pdf",
    MSTR_AUG24,
]
_CERTIFICATES = [
    "https://www.sec.gov/Archives/edgar/data/1050446/000119312525062523/d943742dex31.htm",
    "https://www.sec.gov/Archives/edgar/data/1050446/000119312526270366/d144149dex31.htm",
    "https://www.sec.gov/Archives/edgar/data/1050446/000119312525280178/d205736dex31.htm",
    "https://www.sec.gov/Archives/edgar/data/1050446/000119312525020868/d791994dex31.htm",
    "https://www.sec.gov/Archives/edgar/data/1050446/000119312525138477/d941529dex31.htm",
]


def _mstr_claims(current: bool) -> tuple[float, dict]:
    """Reproduce the Monday report's explicitly estimated preferred claims.

    Starting issued shares are from the June 30 10-Q. Deduct disclosed STRC
    repurchases; assume no unreported changes in the other series. Ordinary
    cumulative dividend accrual uses ending share counts, not a paying-agent
    ledger. This approximation is retained and labeled, rather than silently
    switching to market capitalization or stated principal only.
    """
    repurchased = [288_930, 912_143, 1_152_020, 1_388_720, 1_431_212]
    if current:
        repurchased.append(1_557_177)
    counts = {"STRF": 12_839_689, "STRC": 104_894_705 - sum(repurchased), "STRE": 7_750_000,
              "STRK": 14_020_744, "STRD": 14_024_221}
    quarterly_days, halfmonth_days = (60, 15) if current else (53, 8)
    fx = 1.1643 if current else 1.1699
    per_share = {"STRF": 100 + 10 * quarterly_days / 360,
                 "STRC": 100 + 12 * halfmonth_days / 360,
                 "STRE": (100 + 10 * quarterly_days / 360) * fx,
                 "STRK": 100 + 8 * quarterly_days / 360, "STRD": 100}
    components = {ticker: counts[ticker] * per_share[ticker] for ticker in counts}
    return sum(components.values()), {
        "shares_by_series": counts, "estimated_claims_usd_by_series": components,
        "eur_usd": fx, "fx_at": "2026-08-28" if current else "2026-08-21",
        "cumulative_quarterly_days_30_360": quarterly_days,
        "strc_halfmonth_days_30_360": halfmonth_days,
    }


def _mstr(current: bool) -> dict:
    source = MSTR_AUG31 if current else MSTR_AUG24
    # SEC index acceptance times are Eastern daylight time on these dates.
    disclosed = "2026-08-31T12:00:15+00:00" if current else "2026-08-24T20:01:45+00:00"
    claims, components = _mstr_claims(current)
    share_note = (
        "Estimated basic shares: approximately 415.9 million in the August 24 SEC-filed investor briefing"
        + (", plus 4,531,421 MSTR ATM shares disclosed August 31" if current else "")
        + "; no unreported employee issuance, conversions or other share changes assumed."
    )
    notes = [
        share_note,
        "Debt principal of $6,753,703,000 is carried from June 30 ($6,713,659,000 convertible plus $40,044,000 secured); subsequent amortization is unmeasured.",
        "Liquidity is disclosed USD Reserve plus USD Cash, including reserve securities once; other operating assets and liabilities are outside this net-treasury estimate.",
        "Preferred claims are reconstructed from June 30 counts less disclosed STRC repurchases; unchanged other series, $100/€100 base preference, ordinary cumulative dividend accrual and dated ECB EUR/USD are assumptions.",
        "Ending-share dividend accrual approximates contractual claims; it is not the paying-agent ledger. STRD had no next-quarter declared dividend at the Sunday balance date. All claims and FX remain frozen through the Friday comparison.",
    ]
    sources = [source, MSTR_FWP, MSTR_Q2, *_REPURCHASE_SOURCES, *_CERTIFICATES, ECB_FX]
    return {
        "btc_held": 845_050 if current else 840_447,
        "cash_usd": 6_710_000_000 if current else 6_690_000_000,
        "securities_usd": 0, "debt_usd": 6_753_703_000,
        "preferred_usd": claims, "shares": 415_900_000 + (4_531_421 if current else 0),
        "baseline_at": "2026-08-30" if current else "2026-08-23",
        "disclosed_at": disclosed, "retrieved_on": "2026-09-08",
        "source": source, "sources": list(dict.fromkeys(sources)),
        "share_basis": "basic", "estimated": True, "reconstructed": True,
        "estimated_fields": ["shares", "debt_usd", "preferred_usd"],
        "notes": notes, "preferred_components": components,
        "provenance": {
            "btc_held,cash_usd": {"source": source, "available_by": disclosed, "kind": "reported"},
            "shares": {"source": MSTR_FWP, "additional_source": MSTR_AUG31 if current else None,
                       "available_by": disclosed, "kind": "estimate", "method": share_note},
            "debt_usd": {"source": MSTR_Q2, "as_of": "2026-06-30", "kind": "carryforward estimate"},
            "preferred_usd": {"sources": [MSTR_Q2, *_REPURCHASE_SOURCES, *([MSTR_AUG31] if current else []), *_CERTIFICATES, ECB_FX],
                              "kind": "contractual-claim estimate", "method": notes[3] + " " + notes[4]},
        },
    }


def _asst(current: bool) -> dict:
    source = ASST_AUG31 if current else ASST_AUG24
    disclosed = "2026-08-31T11:59:24+00:00" if current else "2026-08-24T11:59:34+00:00"
    pref_shares = 9_073_914 if current else 8_270_815
    # Aug21's preceding close and 10-session mean were below $100. On Aug28
    # the preceding close was $100.01; daily issuance detail is not disclosed,
    # so assume the higher issuance-day branch rather than assert an exact LP.
    pref_base = 100.01 if current else 100.0
    notes = [
        "Basic shares are the filing's effective Class A plus Class B shares, including sold shares pending next-business-day issuance; options, awards and warrants are excluded.",
        "Debt is carried at June 30's reported zero balance; no subsequent undisclosed borrowing is assumed.",
        f"SATA claims use {pref_shares:,} disclosed shares at an estimated ${pref_base:.2f} liquidation preference. Daily dividends through the balance Friday are assumed paid as scheduled; no later payment outcome is used.",
        "For August 28 the $100.01 preference assumes issuance that day, since daily issuance timing is unavailable; it is the conservative branch of the certificate using the preceding close versus a $100 floor and $99.831 preceding-ten-session average.",
        "Cash and STRC fair value are separate amounts disclosed in the contemporaneous 8-K; later dashboard revisions do not supply these inputs.",
    ]
    if not current:
        notes[3] = "August 21 preference uses the $100 floor: the preceding close was $99.91 and preceding-ten-session average $99.466."
    return {
        "btc_held": 23_156 if current else 21_356,
        "cash_usd": 183_500_000 if current else 171_900_000,
        "securities_usd": 49_152_000 if current else 48_571_000,
        "debt_usd": 0, "preferred_usd": pref_shares * pref_base,
        "shares": 93_262_570 if current else 89_683_423,
        "baseline_at": "2026-08-28" if current else "2026-08-21",
        "disclosed_at": disclosed, "retrieved_on": "2026-09-08", "source": source,
        "sources": [source, ASST_Q2, SATA_CERT, "https://query1.finance.yahoo.com/v8/finance/chart/SATA?period1=1785974400&period2=1788048000&interval=1d"],
        "share_basis": "basic", "estimated": True, "reconstructed": True,
        "estimated_fields": ["debt_usd", "preferred_usd"], "notes": notes,
        "preferred_components": {"shares": pref_shares, "estimated_base_per_share": pref_base, "estimated_dividend_accrual": 0},
        "provenance": {
            "btc_held,cash_usd,securities_usd,shares,preferred_shares": {"source": source, "available_by": disclosed, "kind": "reported"},
            "debt_usd": {"source": ASST_Q2, "as_of": "2026-06-30", "kind": "carryforward estimate"},
            "preferred_usd": {"source": SATA_CERT, "kind": "contractual-claim estimate", "method": notes[2] + " " + notes[3]},
        },
    }


_SNAPSHOTS = {"MSTR": [_mstr(False), _mstr(True)], "ASST": [_asst(False), _asst(True)]}


def company_balances(cutoff: datetime) -> dict[str, dict]:
    """Return the newest vetted baseline published by an aware cutoff instant.

    An older cutoff does not receive a later filing's comparison table. Empty
    issuer records make metrics unavailable rather than fabricate a balance.
    Each result is independent, so consumer edits cannot change future reads.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must include a timezone")
    result = {}
    for ticker, snapshots in _SNAPSHOTS.items():
        eligible = [row for row in snapshots if datetime.fromisoformat(row["disclosed_at"]) <= cutoff]
        result[ticker] = deepcopy(eligible[-1]) if eligible else {}
    return result
