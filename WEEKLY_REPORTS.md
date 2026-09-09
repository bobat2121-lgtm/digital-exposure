# Monday and Friday reports

The existing Streamlit app now hosts both approved reports:

- Monday: `/?report=monday` — Digital Credit in the original light palette.
- Friday: `/?report=friday` — Bitcoin & Digital Credit in the inverse dark palette.

Only the selected tab renders charts or polls. Returning to a tab restores its
completed snapshot, timeframe and expander preferences. Opening a tab for the
first time in a browser session, reloading the browser, or pressing **Refresh
data** requests fresh readings. Friday has no source selector, synthetic preview
option or periodic market-data auto-refresh. Chart windows are fixed; zooming is
disabled. Both reports check the shared read-only SEC feed every 15 seconds
while selected. Unchanged filings never reload Friday's charts or market feeds.

Friday refreshes run in the background. Current readings remain placeholders
until that request finishes; validated cached histories can appear immediately.
History is cached in the host's temporary storage, outside the checkout. A new
host instance rebuilds that cache on its first request. Quotes and indicators
retain their source observation dates; a successful collection is not a claim
that every source published a new observation.

## Balance-sheet scope

Friday now resolves the same latest validated filing pair and date-specific NAV
supplements as Monday. BTC holdings, Strategy USD Reserve plus USD Cash,
Strive cash/securities, debt, basic shares and preferred claims all come from
that shared financial model. Disclosures may update the Friday panel even when
published after the displayed price week, as explicitly requested. The web page
and PNG show the balance dates alongside the separate Friday price week.

Both weekly BTC marks use those same latest inputs. NAV/share WoW remains a
price-only comparison. A new filing pair with missing shares, debt or preferred
claims shows unavailable NAV rather than carrying old values into a new edition.
An incomplete pair remains pending under Monday's existing validation rules.
NAV marks (STRC and FX) refresh with the full market request; balance-only checks
retain them. Feed failures retain a whole dated edition with a visible notice.

The deployed Worker and date-specific supplements remain authoritative. This
connection updates everything Monday can validate; it does not invent facts
that an 8-K omits or add an independent debt parser. Worker code, schedules and
notifications are unchanged. No new repository, Worker or API secret is needed.

## Downloads

Each download captures the displayed prepared data without requesting providers:

| Report | PNG dimensions | Snapshot |
| --- | --- | --- |
| Monday | 1800 × 1125 | Its displayed report and quote bundle |
| Friday | 1800 × 1600 | Friday financial cards plus displayed latest indicator charts |

Navigation, refresh buttons and timeframe controls are excluded. Friday downloads
remain disabled during a pending or failed refresh. The latest Fear & Greed
level and marker, SMA legends and bands are retained. Fonts are bundled for Linux.

## Deployment

Streamlit Community Cloud runs root `app.py` on the existing `main` branch.
The root `report/`, `data/` and `assets/` remain Monday's source of truth;
Friday's package and assets live in `sources/friday/`. Dependencies are pinned
in root `requirements.txt`. Production retains its hosting bind configuration.

Run the offline checks with `python -m unittest discover -s tests -q`.
