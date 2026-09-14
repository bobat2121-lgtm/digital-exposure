# September 14 Monday report recovery

The SEC feed advanced to September 13 (Strategy) and September 11 (Strive),
but the saved NAV supplements stopped at September 7/4. The live report
therefore replaced complete cards with missing NAV and comparison values.
Strive's September 14 VWAP file and the prior market comparison marks were
also missing.

This release reconciles the September 14 filing pair and advances the saved
checkpoint. Strategy's independently dated issuer share table confirms
420,497,000 basic shares; this is not inferred from zero ATM sales. Preferred
claims apply the disclosed 1,420,467 STRC repurchases and the existing
certificate/accrual method. Strive's issuer data confirms zero debt, its share
count and paid daily dividends through September 11. The SATA claim uses the
conservative $100.01 certificate branch; its separate capital proxy still uses
the existing $100 assumption. Estimates remain marked with approximately signs.

The complete 1,560 regular-session ASST minute bars from September 8–11 produce
a $27.212062236938696 HLC3 VWAP estimate. Multiplying by 34,206 net new common
shares produces an approximately $0.9m capital estimate, before fees. This is
not reported issuance proceeds.

`data/reconciliation-2026-09-14.json` preserves the issuer URLs, filing hashes,
share-count evidence, ten-session price windows, native-currency claims,
dividend assumptions and comparison-price timestamps. Debt and preferred
claims retain the explicitly documented estimates and limitations from the
existing methodology. No undisclosed input is replaced by zero.

Monday now checks data completeness before publishing either the HTML or PNG.
If a newer edition lacks NAV, VWAP, comparison marks or period baselines,
the last complete edition remains visible with its balance dates and a notice.
The checkpoint makes this work on a fresh session as well. The SEC feed itself
continues to show newer records. This safeguard does not automatically
reconcile future supplemental financial data.

The shared supplemental data also restores Friday's current financial inputs;
Friday's existing newest-filing projection is unchanged. Historical tests use
fixed September 8 fixtures so future checkpoint updates do not rewrite those
test scenarios.

Validation covers the actual September 14 capital, NAV and comparison values,
web/PNG completeness, an empty live feed, a newer incomplete pair, missing
VWAP and missing prior comparison prices. The downloadable panel is 1800 × 1125.
