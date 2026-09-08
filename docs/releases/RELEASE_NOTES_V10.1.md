# Fantasy Command Center V10.1 — performance & review remediation

## Included

- Initial dashboard is Top 25 only; position views lazy-load up to 100.
- Browser stale-while-revalidate cache paints the last good board immediately, then refreshes in the background.
- FantasyPros positional ranking calls run concurrently.
- External read-only GETs use 3 retries with backoff and Retry-After support.
- Render Key Value/Redis is the preferred shared cache; atomic local-disk cache remains the fallback.
- JSON/CSS/JS responses use compression where supported.
- Public ranking/news endpoints emit bounded public Cache-Control; personal/provider endpoints are no-store.
- Public API surface has rate limiting; ESPN analyze is specifically limited to 20/minute.
- ESPN extension v0.2.6 sends its stable packaged extension ID; no ESPN cookies/passwords are sent to Render.
- Yahoo OAuth cookies are encrypted, HttpOnly, Secure on production, SameSite=Lax, and path-scoped.
- Missing cryptography support hard-fails if Yahoo secrets are configured.
- Root application entrypoint is thin; reusable scoring, cache, HTTP, security, v9 and v10 API logic moved under `fcc/`.
- Version-specific tests/tools moved to `archive/legacy/`; current tests live under `tests/` by concern.
- GitHub Actions runs self-test, pytest, Ruff and JavaScript syntax checks before Render's checks-pass deploy trigger.
- Old release/testing markdown moved under `docs/`.
- Player initials no longer remain visible behind successful photos; initials are failure fallback only.

## Render

The Blueprint provisions `fantasy-command-center-cache` as Render Key Value and injects its connection string as `REDIS_URL`. The web service remains on the free plan by default so deploying this package does not silently create a paid web service.

For faster production response, move the web service to a paid compute plan after validating V10.1.

## ESPN extension ID

Packaged extension ID: `ghcidgjabdbhbkjjchbnaoccpiihkjjj`

Set `ESPN_EXTENSION_ID` to that value if the Blueprint value is not applied automatically.
