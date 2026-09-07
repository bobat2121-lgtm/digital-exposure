# Prototype validation

Validated locally September 7, 2026 with Python 3.12, Streamlit 1.63.0 and Pillow 12.3.0.

## Completed checks

- All 117 tests pass. Coverage includes the financial calculations, source-based
  period baselines, missing/nonpositive inputs, consistent market marks, quote
  refresh success/failure, the offline filing rehearsal, and all report layouts.
- The redesigned Post view follows the requested order, uses restrained type
  sizes and small colored growth figures, removes formulas, and retains VWAP,
  preferred transaction and average-repurchase disclosures.
- Total BTC held tracks the ending snapshot in HTML, both PNG layouts and
  accessible preview text. Zero and unknown holdings remain distinct. The
  bottom panel has more padding and row spacing, retaining the 1800 × 1125 size.
- Strive's live API YTD yield reproduces as 40.81516346%; the report's basic-share
  result reconciles to 45.55897656%. The source audit documents the different
  share bases and the unresolved historical RSU count in the issuer data.
- Current and historical reports contain actual QTD/YTD growth. Illustrative
  inputs never inherit real-company baselines. Strive's baseline dividends were
  reconciled to accrued claims; full future GAAP payables are not added.
- Streamlit AppTest checks the two view modes and both bottom explanation/source
  expanders, along with price refresh and recovery. Browser inspection verified
  the current card, methodology expansion and all period results. The full card
  and collapsed explanation controls fit the observed 842 × 698 viewport.
- Browser PNG bytes match the saved current Post PNG. Measured renderer bounds
  checks pass for all editions, long disclosures, and missing values.

## Data timing

The saved quotes were retrieved September 7 at 16:34:47 ET: BTC $79,207.14,
MSTR $142.80, ASST $27.14, STRC $97.75 and EUR/USD 1.1625. Equity observations
retain September 4 closing times. Verified ending balances remain Strategy
August 30 and Strive August 28; financing activity is August 24–30. QTD begins
June 30 and YTD December 31, 2025. All NAV growth is at constant prices with
explicitly estimated claims. See PERIOD_GROWTH.md for values and provenance.

## Export fingerprints

- `monday-capital-report-current-prices-post.png` — 1800 × 1125
  SHA-256: `ec28222dc59ccb41f81496b7f9cd4e0e8b63dde6b5120f021c2dd6273e3c0374`
- `monday-capital-report-current-prices-detailed.png` — 1800 × 1988
  SHA-256: `3ec4d52863956521290376fef7124a32742f43c4034d88063b9c7e89135198f9`
- `monday-capital-report-2026-08-31-post.png` — 1800 × 1125
  SHA-256: `35d42a7766e793a7b36b1f75f7989b5c23f18f3a06044fbfd5555b82e679bf20`
- `monday-capital-report-2026-08-31-detailed.png` — 1800 × 1988
  SHA-256: `eb7119757511c9bb65a062f050d84dc836abf6b609e03f6623c89115d744e930`
- `monday-capital-report-post.png` — 1800 × 1125
  SHA-256: `4fc899c43f85e748891b6b6a8d462891a7971f0656e84dbcf973b2c02f1321bd`
- `monday-capital-report-illustrative.png` — 1800 × 1710
  SHA-256: `81df33d500afcd9ad8b2886010cd9454218aeee6705bb4383bceb4bbee4b9bfc`
- `monday-capital-report-current-prices-x-demo.png` — 1800 × 1125
  SHA-256: `d8984e0b6d2f209e591bfddc2487836d22b2f9323aba395659e3b0672f888f56`

The app is left in Current prices / Post view. Source files remain local;
no GitHub push, public deployment or live filing monitor was created in this
redesign. The offline filing rehearsal is documented in LIVE_UPDATES.md.
