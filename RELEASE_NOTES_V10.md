# Fantasy Command Center V10 beta

## What changed

- **Screenshot roster import in League HQ.** Upload a PNG, JPEG or WebP roster screenshot. OCR runs in the browser with bundled Tesseract assets; the screenshot is not uploaded to the application server or an AI service. Only recognized text is sent to the player matcher. Full-name matches are preselected for review; abbreviated, fuzzy and ambiguous matches require a choice. Import adds selected players without duplicating an existing roster entry. Add another screenshot for bench/IR pages, or correct names manually. File limit: 12 MB / 24 megapixels; roster limit: 30 players.
- **Who Should I Start? replaces Decision Lab.** A dedicated navy comparison page with player photos, a conditional start lean, Overview, Stats and Game log tabs. Side-by-side tables cover fantasy points, passing, rushing, receiving and kicking where available. Scoring, week and historical season selectors are separate. Changing the historical display season does not change the data basis for the current-week recommendation.
- **Clearer team priorities.** Manual/uploaded teams receive a ranked action list explaining empty starting slots, specific roster weaknesses, bench coverage, injury designations and potential positional targets. Existing model grades and add/drop comparisons remain below the priorities. Unknown availability stays explicitly unconfirmed.
- **Player photos on the ranking board.** Photos use Sleeper player IDs, with initials if no image is available. All positions shows top 25 per position; selecting a position shows up to 100 real entries. Kicker/QB/DST pools may contain fewer than 100; there are only 32 NFL defenses.
- **Cleaner header.** Removed Public site and the boards-full badge. The remaining summary gives the available historical season instead of a completeness count.
- **Workspace and feedback retained in League HQ.** The previous Decision Lab UI and trade workflow are removed. Existing server workspace endpoints and recovery keys continue to work. Local manual rosters remain saved in the browser.

## Data corrections and safeguards

- Fixed nflverse kicker aliases (`fg_made` / `pat_made`) so actual made kicks no longer appear as zero solely due to mismatched column names. Baseline kicker scoring is 3 per made FG and 1 per made PAT; custom distance bonuses and missed-kick penalties are not modeled in the comparison.
- Missing scoring fields remain unavailable instead of producing fabricated zero-point player descriptions.
- Expanded defense rankings deduplicate team abbreviations and bundled display names; exactly 32 real NFL defenses remain.
- Current-week recommendations account for reported Out/IR/Doubtful-type statuses, schedule availability and scheduled kickoff locks. Team aliases such as LAR/LA and WSH/WAS are normalized.
- A start lean uses the latest available regular-season game's recent-form sample (up to four games, with at least three scored games for a two-player form comparison), current reported injury status and the selected week's schedule. It is **not** expert consensus, a win probability or a full matchup-adjusted weekly projection. It does not model weather, opponent strength, new roles, custom league rules, or last-minute news. Older-season inputs are labeled. No actionable pick is forced for missing history, incompatible positions, missing schedules or a player whose game has already started.
- OCR cannot infer players outside the screenshot, prove team ownership, read custom league settings reliably or establish the free-agent pool. Review players, scoring and slots before grading.
- Opening comparison before the manual builder no longer leaves the builder empty. Async selection/import guards prevent stale comparison results and canceled OCR work from replacing current selections.

## Tested

- 32 Python regression tests and the existing self-test suite.
- Ruff lint and formatting; first-party JavaScript syntax; ESPN extension tests.
- Real browser OCR recognized all six names in a synthetic roster screenshot. Reviewed import, duplicate handling, roster persistence, team report, workspace/feedback, comparison-first navigation and phone layout checked in Edge.
- Real Josh Allen/Lamar Jackson historical comparison and current public schedule loaded. Position-view behavior tested with a deterministic 105-player fixture; production catalog/board checked separately.
- Screenshot recognition tested on a clear synthetic roster, not yet on every ESPN/Yahoo/Sleeper screenshot layout. Private ESPN/Yahoo account flows still need user testing.

## Deployment

Install `requirements.txt` (now including `tzdata` for Windows schedule timezones) and deploy the complete folder, including `static/ocr/`. OCR assets are bundled, versioned and licensed; source URLs and SHA-256 hashes are in `static/ocr/SOURCES.json`. Player portraits still load from Sleeper's CDN and gracefully fall back if blocked.

The existing Render configuration is unchanged. Server workspace persistence still requires a persistent `CACHE_DIR` disk; the free-service configuration does not provide one. No paid services were provisioned. No ESPN authentication or extension permissions changed in V10.

Sources: [Tesseract.js API](https://github.com/naptha/tesseract.js/blob/v5.1.1/docs/api.md), [nflverse player data](https://github.com/nflverse/nflverse-data/releases/tag/stats_player), [nflverse schedule](https://github.com/nflverse/nfldata/blob/master/data/games.csv), [Sleeper API](https://docs.sleeper.com/). Comparison layout was informed by the supplied screenshots and [FantasyPros comparison page](https://www.fantasypros.com/nfl/stats/josh-allen-qb-lamar-jackson.php); FantasyPros consensus percentages are not copied or presented as this app's output.
