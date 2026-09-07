"""Strive's dated period baselines, with securities marked at the caller's price.

Source: 2026 Q2 Form 10-Q, financial-condition statement and Notes 3, 5, 6,
and 12. Its December 2025 comparatives already reflect the February 2026
1-for-20 reverse split. Dollar disclosures are rounded to thousands; BTC
holdings are approximate whole coins. Neither input is an EPS denominator.
"""

from decimal import Decimal
from math import isfinite

from .models import Snapshot


STRIVE_PERIOD_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1920406/"
    "000162828026054985/asst-20260630.htm"
)
STRIVE_PERIOD_BASELINE_DATES = {"QTD": "2026-06-30", "YTD": "2025-12-31"}
STRIVE_ORIGINAL_CERTIFICATE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1920406/"
    "000114036125041210/ny20056805x9_ex4-1.htm"
)
STRIVE_DAILY_CERTIFICATE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1920406/"
    "000162828026034802/certi1.htm"
)
# Dec 16–31 is half of the Dec 16–Jan 15 period under twelve 30-day months:
# Dec 16–30 contributes 15 nominal days; the 31st does not add another day.
# Ending shares approximate the ordinary accrual; first-dividend terms for
# the small December ATM issuance can differ from this aggregate estimate.
STRIVE_YEAR_END_DIVIDEND_ESTIMATE = float(
    Decimal(2_012_729) * 100 * Decimal("0.1225") * 15 / 360
)
STRIVE_PERIOD_BASELINE_NOTE = (
    "Strive baselines use split-adjusted Class A + B common shares and approximate "
    "reported BTC. June 30's 505,000 STRC shares are marked at the report price. "
    "Preferred claims use the explicitly reported $100 liquidation preference, "
    "zero ordinary accrual after June 30's paid daily dividend, and an estimated "
    "15/360 accrual at 12.25% on December 31's ending shares. Declared future "
    "dividends payable are not treated as fully accrued liquidation claims. "
    "NAV growth is an estimate using these rounded financial disclosures."
)


def strive_period_baselines(strc_price: float | None) -> dict[str, Snapshot]:
    """Return June 30 QTD and December 31 YTD baselines for constant-price NAV.

    Missing STRC prices leave June 30's security value unknown. December 31
    has a disclosed zero holding and therefore needs no security price.
    """
    if strc_price is not None and (not isfinite(strc_price) or strc_price < 0):
        raise ValueError("STRC price must be finite and non-negative")

    # Note 12 states $100 LP at both dates and no compounded arrears. The
    # company's payment history confirms the June 30 daily payment settled.
    # Year-end is between December 15 and January 15 payments. Only the
    # accrued portion belongs here, not the full declared dividend payable.
    return {
        "QTD": Snapshot(
            btc_holdings=19_864,
            effective_common_shares=72_164_809 + 9_780_018,
            cash=145_466_000,
            marketable_securities=(505_000 * strc_price if strc_price is not None else None),
            debt_principal=0,
            preferred_claims=7_829_502 * 100,
        ),
        "YTD": Snapshot(
            btc_holdings=7_627,
            effective_common_shares=34_936_745 + 9_776_540,
            cash=67_499_000,
            marketable_securities=0,
            debt_principal=0,
            preferred_claims=2_012_729 * 100 + STRIVE_YEAR_END_DIVIDEND_ESTIMATE,
        ),
    }
