# Fantasy Command Center V9 beta

V9 adds a Decision Lab and fixes scoring, lineup, data-quality and connection bugs. Players remains the landing page; My Week is deferred.

## Included

- Manual team setup with Superflex and validated starting-slot counts.
- Maximum-value lineup assignment across overlapping FLEX/Superflex slots, with no duplicated players or invented starters.
- Decision Lab: standard reception scoring, configurable passing touchdowns and TE reception premium; full scoring coefficients shown with results.
- Explicit available-player pool, protected drops and before/after starting-lineup comparisons. Alternatives are independent, not consecutive waiver claims.
- Equal-size trade comparisons showing both managers' optimized lineups and value changes.
- Historical weekly player results, targets and carries, including two-player comparison. Missing weeks remain absent.
- Ranking filters for your manual roster, marked available players and watchlist. Original ranks remain visible after filtering.
- Private recovery-key workspaces for roster, watchlist, scoring, protected players and opponent roster. Save/load works across browsers connected to the same server.
- Feedback submission with the last Decision Lab input/result snapshot. No provider authentication is included by the application.
- Responsive Decision Lab, mobile navigation, keyboard focus states and data-season labels.

## Bug fixes

- Six-point passing touchdowns no longer silently become four-point touchdowns in supported custom offensive scoring.
- Sleeper league offensive coefficients are used when supported. Unsupported rules trigger an explicit standard-scoring estimate rather than breaking the existing connection.
- ESPN FLEX, Superflex and combination slots are counted; unknown starting slots fail clearly. Yahoo combination slots are supported.
- Connected league add/drop deltas now compare complete starting lineups instead of subtracting an unboosted drop score from a market-boosted pickup score.
- Missing games-played data no longer assumes 17 games. Missing KPI fields remain missing.
- Negated/speculative news sentences no longer produce positive keyword signals.
- ESPN no longer requires an unrelated API-root preflight. Requests have timeouts and roster-stage error context.
- ESPN snapshots only open when explicitly syncing and expire after ten minutes. Ordinary visits no longer replay a week-old snapshot.
- Saved Sleeper settings no longer navigate away from the ranking board on startup.
- Removed a hardcoded Sleeper season and guarded against stale board responses after scoring changes.
- Closed SQLite connections correctly; added JSON size limits and request validation.
- Reformatted Python, removed bare except clauses and unused imports, and added repeatable lint, regression and JavaScript checks.

## Model limits and deployment requirements

This is a V9 **beta**, not the entire long-term roadmap. Decision Lab compares model roster value, not weekly projected points. The model still uses prior-season production, search/market rank, board rank and status penalties. Rookie values, K/DST, custom scoring beyond supported offensive fields, news attribution and real-time kickoff locks remain limited. Weekly forecasting, FAAB recommendations and uneven trades are not implemented. Availability in manual mode is supplied by the tester. ESPN and Yahoo import grades still disclose baseline-scoring limitations.

ESPN authentication, extension permissions and host permissions are unchanged. Private ESPN success requires account testing. Yahoo requires the existing approved OAuth credentials and an account test. Sleeper is read-only.

Workspaces and feedback are stored in `CACHE_DIR/workspaces.sqlite3`. The recovery key acts as a password; its SHA-256 digest is stored by the server, and the browser keeps the key in session storage. There is no email/password recovery or multi-user sharing. Last explicit save wins. Use HTTPS and a persistent disk with restricted server access and backups. The supplied Render free-service configuration has **no persistent disk**, so server-side saves can disappear on restart/redeploy; local browser roster storage continues to work. No paid infrastructure was provisioned.

## Validation

- 19 Python regression tests, including exhaustive comparison of small lineup assignments, custom scoring, workspace isolation, malformed inputs, history, Yahoo parsing and manual move regressions.
- Existing self-test suite using real Flask.
- Ruff lint and formatting checks.
- JavaScript syntax and extension behavior checks.
- Desktop/mobile browser flows with synthetic player/provider responses; real local workspace/feedback API saves and loads.
- Real cached/provider data check: 879 catalog entries and 16 Josh Allen regular-season game rows for 2024. Latest available results resolved to 2025 on September 5, 2026; the UI must not invent 2026 results.

Run `python -m unittest discover -v`, `python self_test.py`, `ruff check .`, `ruff format --check .`, `node check_js.cjs`, and `node test_extension.cjs`. CI repeats these checks. Browser smoke test instructions are in `TESTING_V9.md`.

ESPN slot mapping was checked against the upstream [espn-api constants](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/constant.py). Historical game data comes from [nflverse](https://github.com/nflverse/nflverse-data/releases/tag/stats_player).
