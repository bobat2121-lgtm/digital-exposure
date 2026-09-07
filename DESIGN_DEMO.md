# Post redesign

The balanced redesign is now the main **Post view**. The previous large colored
X demo has been replaced. The downloadable image is still 1800 × 1125.
The public report is live at
[digital-credit-report.streamlit.app](https://digital-credit-report.streamlit.app/).

Row order: NAV/share and price/basic NAV; new Bitcoin bought alongside total BTC held; common capital;
preferred capital; effective common shares; BTC/common share; NAV/common share;
net BTC amplification; preferred/BTC; QTD/YTD basic-share growth.
The bottom panel has additional inner padding and 32px between growth rows,
while preserving the 1800 × 1125 export size. The capital-period heading has
extra clearance below the Bitcoin row.

Primary row values use 28–29px type, labels about 23px, and growth figures 22px.
The top NAV/share is 38px. Green/red appear on growth figures, with explicit
signs; there are no large colored comparison blocks. Financing flows and
amplification stay neutral.

Formulas have moved to **How the numbers are calculated**, below the card.
**Sources & input audit** contains the filing and period-baseline detail. Both
sections are available in Post and Detailed views. VWAP estimates, preferred
sales/repurchases, and the average repurchase price remain identified on the
card. Link to the [public Streamlit report](https://digital-credit-report.streamlit.app/)
in an X post so readers can open the calculation explanations without adding
formulas to the image.

The active [SEC monitor](https://capital-report.alatimore06370.workers.dev/api/status)
also appears in **Sources & input audit**, with a 15-second page refresh of new
filings and parsed facts. It stays below the compact image. Financial cards
retain their verified figures until the new filing and all required NAV inputs
are fully reconciled; the live filing feed does not silently advance the
card's balance dates. See LIVE_UPDATES.md for the Monday polling schedule.

QTD/YTD cells now contain actual reconstructed growth using June 30 and December
31 baselines, with the same common-share basis as the main report. NAV growth
uses constant asset prices and dated accrued preferred claims. Full inputs,
source links, estimates and computed results are in PERIOD_GROWTH.md. Strive's
separate assumed-diluted 40.8% YTD KPI is reconciled in STRIVE_YIELD_AUDIT.md. The
illustrative example does not borrow real-company period baselines.

The legacy `--layout x-demo` export flag produces this same design with a
preview label; the app itself has only Post and Detailed view modes.
