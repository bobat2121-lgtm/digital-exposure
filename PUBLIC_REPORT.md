# Public report design

The approved public page uses the **Imprint dot** title: Georgia Bold for
“Digital Credit,” Lato Regular for “The” and “Report,” and a small orange endpoint.
The fixed title artwork gives the PNG export the same design on the Linux host.
See [brand asset notes](assets/BRAND-TITLE.md) for reproduction details.

The responsive report has two aligned company panels on desktop and stacks them
on phones. Every page opening or browser reload refreshes the existing price
sources once for that session. The report keeps its dated balance and activity
periods, and the concise 279-word calculation overview. There are no public
edition selectors, view tabs, quote refresh controls, or VWAP pull controls.
The former Sources & input audit section is removed. A separate read-only
Latest SEC filings section provides the monitor's publication status.

Market Activity groups common capital, preferred capital, and effective common
shares. Strategy's average sale price is net issuance proceeds divided by shares
sold: $602.8 million / 4,531,421 = $133.03 after fees. Strive's common capital keeps
its prior-week VWAP estimate label; preferred activity retains its sale or
repurchase disclosure and average repurchase price.

The download is a small tertiary button at the bottom. It produces the
1800 × 1125 image with the approved title, BTC price and one quote-update
timestamp. It is the only public entry point to the fixed post layout.

Financial values and snapshot dates remain unchanged by this design rollout.
Legacy historical and illustrative exports remain available through the local
export script, and were regenerated with the new branding.

UI validation: 26 application, current-report, common-sale-price, post-export,
detailed-export, legacy-demo and preferred-disclosure tests passed. The current
download was rendered and visually inspected at 1800 × 1125.

Reported Bitcoin Bought and Bitcoin Sold use separate gross quantities. A
sales-only week changes the activity label to Bitcoin Sold; a week with both
shows both. Confirmed zero remains zero; missing activity stays undisclosed.
No sale is inferred from falling holdings. Fractions retain satoshi precision.

Price refreshes use one complete validated snapshot for both the web report and
the PNG. Normal reruns, downloads and SEC updates do not trigger another fetch.
On a provider failure, the latest complete in-memory or bundled snapshot remains
visible with its original timestamps and a short fallback notice. Public visits
do not write the repository or alter the balance dates.
