# Digital Credit Report deployment

The public report is live at
[digital-credit-report.streamlit.app](https://digital-credit-report.streamlit.app/).
It was deployed from this repository to Streamlit Community Cloud and verified
in the browser on September 7, 2026. The deployment settings below reproduce
the running app.

## Deployment settings

| Field | Value |
| --- | --- |
| Repository | `bobat2121-lgtm/digital-exposure` |
| Branch | `main` |
| Main file path | `app.py` |
| App URL / subdomain | `digital-credit-report` |
| Python version | `3.12` |
| App access | Public |

At [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create
app**, then **Deploy from repo**. Enter the settings above; use **Advanced
settings** to select Python 3.12. Save and deploy, then watch the build logs.
The custom subdomain field determines the `streamlit.app` address. See the
[official deployment steps](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

The deploying Streamlit account must be connected to GitHub and have admin
permission on the repository. Private repositories require the corresponding
GitHub authorization. See
[GitHub account connection](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account).

## Live Worker deployment

Discord integration was deployed September 7, 2026 as Worker version
`3c509f9e-1111-44f6-b4ce-a162cdf05286`. It adds a separate notification Durable
Object through migration `v2`, preserving the existing SEC data and schedule.
The webhook is a Cloudflare secret. A separate `STREAMLIT_ACK_TOKEN` is shared
with the live app's encrypted secret settings for its receipt callback.

The live setup test received Discord message confirmation on its first
attempt. A repeated setup-test request retained the same message ID and
attempt count; historical filing receipts returned HTTP 409 and an
unauthenticated receipt returned HTTP 401. No historical weekly alert was sent.
See [LIVE_UPDATES.md](LIVE_UPDATES.md#discord-notification) for the exact trigger
and active-Streamlit-session requirement.

Before deployment, the 61-test Worker suite passed; a further cleanup-failure
regression was added and all 27 notification tests passed. TypeScript and the
deployment dry-run passed. The Python client passed 34 filing, acknowledgement,
and existing Streamlit app tests. These tests use local/mock filings; future
Monday release-to-notification latency still requires a real new filing pair.

### Original SEC poller deployment

The SEC poller is deployed at
[capital-report.alatimore06370.workers.dev](https://capital-report.alatimore06370.workers.dev/)
with version `8c4fcbcb-3ffd-4658-81bd-d9bf828bf2d4`. Production SEC-identification
and administrator secrets are configured in Cloudflare. The report reads the
public origin from `data/sec-monitor.json`; `SEC_MONITOR_URL` can override it.
No Worker administration credential is required in Streamlit; the dedicated
acknowledgement secret above can only confirm displayed filing receipts.

At **2026-09-07T21:38:50Z**, the live smoke check passed: public API schema 1,
unauthenticated admin rejection (HTTP 401), real SEC retrieval for both issuers
(two documents each), both historical parser replays accepted for review, and
duplicate handling on repeat. The next Monday polling window starts
**2026-09-14T10:45:00Z / 06:45 EDT**.

Use [status](https://capital-report.alatimore06370.workers.dev/api/status) for
current readiness, schedule, last successful checks and errors, and
[filings](https://capital-report.alatimore06370.workers.dev/api/filings) for
timestamped observations. See [LIVE_UPDATES.md](LIVE_UPDATES.md) and
[the Worker runbook](worker-capital-report/README.md) for operational details.
The report's 15-second monitor fragment shows new filing facts while the
financial card retains verified dated inputs pending complete reconciliation.

## Runtime and repository contents

The application entrypoint, `requirements.txt`, and `.streamlit/config.toml`
are in the repository root. `report/`, `assets/`, the audit Markdown files,
and the saved `data/` snapshots are required at runtime and must be committed.
Community Cloud starts the application from the repository root; see
[file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization).

The tested local interpreter is Python 3.12.14. The dependency file pins
Streamlit, Pillow, exchange_calendars, and the IANA timezone data used for
New York time. Logos and licensed Lato fonts are bundled, so exports do not
depend on Windows fonts or external font services. Paths use `pathlib`.
No additional system packages are required by the current application.

Predeployment checks passed on September 7, 2026: Python compilation, installed
dependency consistency, configuration parsing, timezone lookup, and both
bundled fonts. A fresh dependency resolution for CPython 3.12 on Linux x86-64
resolved all 41 packages as binary wheels compatible with manylinux 2.28 or
older. The deployed application also started successfully and rendered both
company logos, saved market marks, total BTC and QTD/YTD results. Its live SEC
monitor showed successful MSTR and ASST checks with no source errors.

The shared Streamlit config leaves the bind address to the hosting platform.
The Windows `launch.ps1` helper explicitly binds local development to
`127.0.0.1`. Keep CORS and XSRF protection enabled. See
[Streamlit configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml).

## Data and credentials

The saved report, historical replay, audit evidence, and images contain public
company and market information. The report can render without market-data
credentials. Manual quote and historical VWAP refreshes call public endpoints;
those providers may reject or limit requests from a cloud host. A failed
refresh preserves the last complete saved snapshot.

Runtime changes to JSON caches on Community Cloud are not a durable source of
record and may be replaced on restart or redeploy. The committed snapshots
remain the reproducible fallback. Refreshing prices changes market marks;
it does not advance the underlying balance or capital-activity dates.

Keep credentials out of Git. `.streamlit/secrets.toml`, `.env` files, Worker
`.dev.vars`, and `.wrangler/` are ignored. Put any deployment-specific secrets
in Community Cloud's **Advanced settings → Secrets**, or the deployed app's
settings. Cloudflare administration and polling credentials belong in the
Worker's secret store; they should never be sent to a browser.

## Verify the deployment

1. Open the deployed public URL in a new browser session and confirm the report
   loads, including both logos and the QTD/YTD panel.
2. Confirm the quoted prices and balance dates match the selected saved edition.
3. Switch between Post view, Detailed view, historical replay, and the sample.
4. Download the post PNG and open both methodology/audit expanders.
5. Check the Community Cloud logs for missing imports, assets, or runtime errors.

Updates pushed to the deployed branch are picked up by Community Cloud. Keep
the SEC poller deployment and its health checks separate from the Streamlit
application's page-load checks: a live report page alone does not prove that
new filings have been detected or applied.
