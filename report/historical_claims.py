"""Reproducible preferred-claim estimates for the August 31 reconstruction.

See HISTORICAL_SOURCES.md for certificates, the share rollforward and limits.
These estimates are independent of financing cash flows. Ending-share dividend
accrual is not an exact record-holder payable or a paying-agent reconciliation.
"""
from decimal import Decimal


ECB_USD_PER_EUR = {"prior": Decimal("1.1699"), "current": Decimal("1.1643")}
STRATEGY_DEBT_CARRYFORWARD = 6_753_703_000
STRC_JUNE_30_SHARES = 104_894_705
STRC_REPURCHASES_TO_AUG_23 = (288_930, 912_143, 1_152_020, 1_388_720, 1_431_212)
STRC_AUG_24_30_REPURCHASES = 1_557_177
STRATEGY_OTHER_PREFERRED_SHARES = {
    "STRF": 12_839_689, "STRK": 14_020_744,
    "STRD": 14_024_221, "STRE": 7_750_000,
}


def strategy_claim_components(edition: str, *, usd_per_eur: Decimal | None = None) -> dict[str, dict]:
    """Base preference plus ordinary accrued dividends on ending shares.

    Sunday August 23 / 30: quarterly 30/360 days are 53 / 60; STRC's
    semi-monthly inclusive accrual days are 8 / 15. STRD is noncumulative;
    its next dividend had not been declared at either Sunday snapshot.
    """
    if edition not in ECB_USD_PER_EUR:
        raise ValueError("Expected prior or current historical snapshot")
    current = edition == "current"
    fx = ECB_USD_PER_EUR[edition] if usd_per_eur is None else usd_per_eur
    strc_shares = STRC_JUNE_30_SHARES - sum(STRC_REPURCHASES_TO_AUG_23)
    if current:
        strc_shares -= STRC_AUG_24_30_REPURCHASES
    counts = {**STRATEGY_OTHER_PREFERRED_SHARES, "STRC": strc_shares}
    quarter_days = Decimal(60 if current else 53)
    half_month_days = Decimal(15 if current else 8)
    accrued_per_share = {
        "STRF": Decimal(10) * quarter_days / 360,
        "STRK": Decimal(8) * quarter_days / 360,
        "STRE": Decimal(10) * quarter_days / 360,
        "STRC": Decimal(12) * half_month_days / 360,
        "STRD": Decimal(0),
    }
    result = {}
    for series, shares in counts.items():
        base = Decimal(shares) * 100
        accrued = Decimal(shares) * accrued_per_share[series]
        conversion = fx if series == "STRE" else Decimal(1)
        result[series] = {
            "shares": shares, "currency": "EUR" if series == "STRE" else "USD",
            "base_preference": base, "estimated_dividend_accrual": accrued,
            "usd_per_unit": conversion, "estimated_claims_usd": (base + accrued) * conversion,
        }
    return result


def strategy_preferred_claims(edition: str, *, at_current_fx: bool = False) -> float:
    fx = ECB_USD_PER_EUR["current"] if at_current_fx else None
    return float(sum(row["estimated_claims_usd"]
                     for row in strategy_claim_components(edition, usd_per_eur=fx).values()))


def strive_preferred_claims(edition: str, *, conservative: bool = True) -> float:
    """Friday after-payment claims; use the current contractual upper bound.

    All dividends through each Friday are recorded paid. On August 28 the
    unknown same-day issuance condition leaves a $100–$100.01 base preference;
    August 21 is $100 under either condition. Never infer gross SATA cash here.
    """
    if edition == "prior":
        return 827_081_500.0
    if edition != "current":
        raise ValueError("Expected prior or current historical snapshot")
    preference = Decimal("100.01") if conservative else Decimal(100)
    return float(Decimal(9_073_914) * preference)
