# Public deployment security

This repository and the report are intentionally public. Source code, formulas,
report snapshots and brand assets can be viewed or copied. Repository visibility
does not grant permission to push code, administer Cloudflare or send Discord
notifications.

- Keep the Discord webhook, SEC identification value and administration token
  in Cloudflare secrets. The public Streamlit app needs no notification token.
- Never commit credentials. `.streamlit/secrets.toml`, `.env*`, `.dev.vars*`,
  `.wrangler/` and logs are ignored. If a credential enters Git history, revoke
  or rotate it; deleting the current file is insufficient.
- Public report controls are read-only. Price and VWAP refresh scripts run in
  the owner's environment; reviewed snapshots reach production through Git.
- The public filing API only reads stored SEC observations. Administration and
  setup-test endpoints require the separate administrator credential.
- The collapsed PNG download is a convenience, not access control. Any visitor
  may download the same public report. No private data belongs in that export.
- Keep dependencies updated and review changes before merging to `main`, which
  automatically updates Streamlit. Protect the GitHub and Cloudflare accounts
  with multifactor authentication. Avoid granting deployment secrets to
  untrusted pull-request code.

On September 7, 2026, a targeted scan of reachable local Git history and the
deployment files found only dummy test credentials matching known secret
patterns. No production credentials were identified. This was a targeted
review, not a penetration test or a guarantee that every vulnerability is absent.

GitHub automatically scans public repositories for supported secret types:
[secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).
Use [Streamlit's secret settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
for any future private data connections. The repository can be private while
the app remains public if source visibility is undesirable:
[sharing a Streamlit app](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app).
