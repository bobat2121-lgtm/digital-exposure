# Current prices

Every page opening or browser reload requests stock, Bitcoin, STRC and EUR/USD
quotes from the existing sources. One complete snapshot serves both the report
and its PNG for that session. Ordinary reruns and SEC-feed updates reuse it.
A failed refresh retains the last complete snapshot and its original timestamps,
with a brief notice. Public visits do not save to Git or change the bundled data.
`python refresh_prices.py` remains available to maintain the bundled fallback.
The header shows retrieval time; each quote retains its source timestamp.
Closed-market stocks can remain at their last regular-session close.

**Balances remain explicitly dated.** As verified September 7, the latest weekly
balance disclosures remain Strategy August 30 and Strive August 28. The current
view revalues those snapshots; it does not invent September 6 balances or roll
dividend liabilities forward. Financing, shares, BTC quantities, cash, debt,
and native-currency preferred claims remain tied to the existing source audit.
The card labels capital activity **August 24–30**. Its share and BTC changes
compare the same reported snapshots as the August 31 reconstruction.

**What changes with prices:** current stock prices update Price/basic NAV;
the shared current BTC reference revalues both companies. Strive's disclosed
505,000 STRC shares are marked at the latest STRC quote. Strategy's dated euro
preferred claims are translated at the latest EUR/USD quote. For constant-price
weekly NAV/share, both weeks use the same current BTC, securities and FX marks.
The old Monday's amplification and Preferred/BTC comparison still use that
edition's own prices and are labeled **vs Aug 24**. **Reported-week NAV/share**
refers to the August 24–30 activity period, restated at today's market marks.
The saved historical edition remains unchanged.

**Comparison with company dashboards:** this report retains effective basic
common shares and estimated liquidation claims. Strive defaults to diluted
shares; Strategy uses fully diluted shares and preferred notional. Different
share bases, liability definitions, balance dates and asynchronous market
marks can therefore leave differences even after updating prices. See the
[Strategy definitions](https://www.strategy.com/notes) and
[Strive dashboard](https://www.strive.com/treasury). Do not replace the report's
basic multiple with an issuer number from another timestamp.

BTC quotes come from the [Strategy public feed](https://api.strategy.com/btc/bitcoinKpis).
Stock, STRC and EUR/USD marks come from Yahoo Finance chart metadata. The quote
audit lists the exact source URLs and timestamps; retrieval time is not
substituted for the time of the underlying market quote.
