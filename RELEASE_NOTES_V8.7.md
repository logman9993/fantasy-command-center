# Fantasy Command Center 8.7

Continues the supplied V8.6 update on top of GitHub commit `a8c0e6a`.

## Included

- V8.6 manual roster builder and evidence-based player, sleeper and injury descriptions.
- Yahoo OAuth, team discovery, and read-only roster/free-agent import into the model grader.
- Player and team historical season selectors. Latest is an automatic option; choosing 2024 pins that selection without changing current player rankings or the projection model.
- In-memory caches expire after 15 minutes. Current-season production files refresh hourly; historical files retain the existing longer disk cache.
- Automatic NFL season selection unless NFL_SEASON is explicitly configured.

For an existing Render service, remove a previously configured NFL_SEASON override to enable automatic season rollover.
- Manual roster duplicates are removed, missing starters count as zero, roster slot settings persist, and model estimates are not displayed as real league ranks.
- Confirmed empty free-agent pools stay empty. Add/drop value comparisons use the same model scale for both players.
- Existing ESPN extension and ESPN private sync logic are preserved.

## Yahoo activation and limits

Set the four variables in YAHOO_SETUP.md after Yahoo approves API access. No credentials are included in this release. Official references: [Yahoo portal](https://sports.yahoo.com/developer/), [API documentation](https://sports.yahoo.com/developer/docs/).

Yahoo imports your roster, supported starting slots and up to 100 Yahoo-ranked free agents, excluding players on waivers. Names must match the player catalog exactly at the same position; an unmatched roster stops grading instead of silently dropping players. Unmatched free agents are excluded and counted.

Yahoo and manual grades use a standard PPR/Half/Standard model, not exact custom scoring or a measured ranking against all league rosters. Yahoo shows model-selected starters, not the lineup submitted on Yahoo. Unsupported Yahoo slots fail with an explanation. OAuth and import parsing have automated fixture coverage; live approved-account testing is still required.

## Validation

- `python self_test.py`: original offline checks.
- `python test_updates.py`: real Flask regression tests for input validation, duplicate/incomplete rosters, empty free-agent pools, cache expiry, historical selection, Yahoo ownership and parsing, and OAuth state rejection.
- Browser smoke test: historical API requests, selection persistence, saved manual roster/slots, Yahoo team buttons, desktop/mobile layout and JavaScript errors.
- Live source probe on September 5, 2026: 2026 player file unavailable (404); 2025 file available and selected as latest.

## ESPN decision still pending

No ESPN linking change has been made. The reviewable proposal is opt-in local auto-sync through the existing extension, refreshing only while the browser and an authenticated ESPN fantasy page are available. Start with page-visit refresh and a 30–60 minute timer; show last successful sync and allow disabling it. The page context continues to make authenticated requests; only fantasy data is sent to Command Center. Do not promise sync with the browser closed. Broader background permissions or server-held credentials require a separate design. See ESPN_LINKING_OPTIONS.md for alternatives.
