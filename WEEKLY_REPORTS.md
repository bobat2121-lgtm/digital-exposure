# Monday and Friday reports

The existing Streamlit app now hosts both approved reports:

- Monday: `/?report=monday` — Digital Credit in the original light palette.
- Friday: `/?report=friday` — Bitcoin & Digital Credit in the inverse dark palette.

Only the selected tab renders charts or polls. Returning to a tab restores its
completed snapshot, timeframe and expander preferences. Opening a tab for the
first time in a browser session, reloading the browser, or pressing **Refresh
data** requests fresh readings. Friday has no source selector, synthetic preview
option or periodic auto-refresh. Chart windows are fixed; zooming is disabled.
Monday retains its read-only 15-second SEC checks while selected.

Friday refreshes run in the background. Current readings remain placeholders
until that request finishes; validated cached histories can appear immediately.
History is cached in the host's temporary storage, outside the checkout. A new
host instance rebuilds that cache on its first request. Quotes and indicators
retain their source observation dates; a successful collection is not a claim
that every source published a new observation.

## Balance-sheet scope

Friday currently uses reviewed August 24/31 SEC disclosures, selected by the
completed Friday cutoff. Holdings, cash, debt, common shares and preferred
claims are held fixed for the weekly price comparison. These are dated real
inputs, including documented estimates, and do **not** automatically advance
from the Monday Worker. Future balance changes require reviewed records or a
cutoff-aware feed integration. Directly using Monday's newest filing pair could
introduce disclosures made after the Friday being measured.

Monday continues to consume the deployed Worker and date-specific supplements.
This release does not change Worker code, schedules or notifications. No new
repository, Worker or required API secret is needed for these report tabs.

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
