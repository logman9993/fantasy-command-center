# Fantasy Command Center V6.1 — Deployment Edition

**Public deployment instructions:** see [`DEPLOYMENT.md`](DEPLOYMENT.md).

This package is ready to place directly in a GitHub repository and deploy through Render.

---

# Fantasy Command Center

A locally hosted, mobile-friendly NFL fantasy football dashboard.

## What it does
- Top players by QB / RB / WR / TE / K / DST
- PPR / Half-PPR / Standard scoring selector
- Sleeper trending players / sleeper discovery
- Injury-risk monitor
- Top defenses
- Top scoring offenses
- Sleeper league + roster import endpoint/UI
- Designed for later roster grading, positional weakness, trade targets, waiver suggestions, start/sit, and matchup analysis

## Fastest Windows setup
1. Install Python 3.11+ if it isn't already installed.
2. Double-click `run.bat`.
3. Windows Firewall may ask whether Python can use Private networks. Allow Private networks.
4. On the PC, open `http://localhost:5050`.
5. Find the PC's LAN IP:
   - Open Command Prompt
   - run `ipconfig`
   - find `IPv4 Address`, e.g. `192.168.1.42`
6. Make sure the phone is on the same Wi-Fi.
7. On the phone open `http://192.168.1.42:5050` (replace with your PC's IP).
8. On iPhone: Share -> Add to Home Screen for an app-like launcher.

## Live FantasyPros data
The UI works immediately with starter rankings. Sleeper trending and roster endpoints are live automatically.

For live FantasyPros consensus rankings:
1. Obtain a FantasyPros API key.
2. In Command Prompt, before starting:
   `set FANTASYPROS_API_KEY=YOUR_KEY`
3. Run `run.bat`.

You can make that permanent with Windows Environment Variables if desired.

## Sleeper roster import
Open "My Team", enter your Sleeper username, select a league, and the app imports your roster.

## Architecture
- Flask local web server
- Vanilla responsive front-end
- JSON API endpoints
- Daily local cache for Sleeper player IDs
- 15-minute cache for Sleeper trending
- 30-minute cache for FantasyPros rankings

## Next logical build
Add a roster analyzer using:
- league-specific scoring settings
- starting lineup requirements
- ECR vs roster positional value
- ADP/value gaps
- bench depth
- injury concentration
- bye-week collisions
- stack/correlation
- waiver replacement value
- trade targets


## V3 additions

### Sleeper explanations
Every sleeper now includes:
- breakout thesis
- potential fantasy upside
- recommended draft/waiver acquisition window
- positional rank when the player is present on the main board
- Sleeper add momentum

### Injury history
Draft Injury Risk now adds the two most recent official injury-report episodes available in the nflverse injury dataset:
- injury type
- season/week range
- number of weeks appearing on the injury report
- number of those weeks officially listed `Out`

Important: nflverse injury-history coverage currently ends after the 2024 season. Current team and injury designation still come from Sleeper.

### Offense and defense analytics
Team rankings are now composite rankings based on prior-season nflverse team statistics.

Offense:
- total yards + NFL rank
- offensive touchdowns + NFL rank
- offensive EPA + NFL rank
- turnovers + NFL rank

Defense:
- opponent yards allowed + NFL rank
- opponent offensive TDs allowed + NFL rank
- sacks forced + NFL rank
- takeaways + NFL rank

The app explains the ranking directly on each team card instead of returning an unexplained Top 10.


## V4 changes
- Rankings expanded from Top 20 to Top 25 per position.
- Sleeper targets expanded to Top 25.
- Draft-relevant injury risk expanded to Top 25.
- Defense tab no longer renders blank when the historical team-stat source lacks opponent-level defensive aggregates.
- Defense cards now fall back to the bundled DST board instead of returning an empty list.


## V5 fixes
- Starter mode no longer depends on the old ~10-player bundled list.
- Without a FantasyPros API key, QB/RB/WR/TE/K are populated to Top 25 from prior-season nflverse production.
- DST Top 25 is generated from the defensive team model.
- Defense stats now use weekly team summaries because weekly data exposes `opponent_team`.
- Defensive cards include yards allowed, yards/game, touchdowns allowed, sacks, takeaways and EPA allowed, plus NFL rank for each metric.
- Defense tab has a guaranteed non-empty fallback if the weekly source cannot be downloaded.


# V6 reliability pass

V6 is a source-pipeline rebuild rather than a heading/display patch.

## Ranking board
Each position targets 25 records using this priority:
1. FantasyPros ECR when an API key is configured.
2. A five-year nflverse production model restricted to players who are currently active and rostered in Sleeper.
3. Sleeper current-player search/depth ranking to fill any missing slots.
4. Bundled starter data only as the last fallback.

The Data Health tab shows the actual count and source for each position.

## Player analysis
Tapping a ranked player now includes:
- prior-year fantasy PPG
- current-year five-season production projection
- prior-year KPIs
- positional rank for supported KPIs
- five-year PPG history
- a written model interpretation covering trend, standout metrics, consistency and uncertainty

The fantasy scoring implementation was updated to nflverse's current `passing_interceptions` field.

## Sleepers
The board targets 25 current rostered players outside the main Top-25 positional boards.
Each has:
- breakout thesis
- potential upside
- draft/waiver acquisition window
- Sleeper trend/search context
- historical model context where a match exists

## Injury risk
The injury board is restricted to players on the main draft board.
It includes:
- current Sleeper injury designation
- last two matching official injury-report episodes
- weeks on the report
- weeks officially listed Out
- a written risk interpretation

Historical nflverse injury data currently ends after 2024.

## Team offense / defense
Primary source: 2025 nflverse week-level team summaries. Weekly data is intentionally used because it contains `opponent_team`.

Offensive composite:
- estimated points
- total yards
- EPA
- touchdowns
- turnovers / ball security

Defensive composite:
- estimated points allowed
- yards allowed
- EPA allowed
- sacks
- takeaways

Every displayed metric includes its rank against the full league, plus a written explanation of the composite rank.

If GitHub release assets are blocked, V6 attempts ESPN team-stat endpoints before using the bundled fallback.

## Diagnostics
Open the Data Health tab or:
`http://<PC-IP>:5050/api/diagnostics`

## Offline code self-test
From the project folder:
`python self_test.py`

This validates the updated interception scoring and the 32-team offense/defense aggregation without internet.


## V6.2 Cloud performance hotfix

The public dashboard now uses progressive loading:

- Initial page: rankings + sleepers only.
- Player five-year analysis: loaded when a player is tapped.
- Injury history: loaded when the Injury Risk tab is opened.
- Team offense/defense statistics: loaded when the Teams tab is opened.
- Player row matching uses an in-memory index instead of repeatedly scanning every season file.
- Injury histories are indexed once rather than reparsing every CSV for every player.
- ESPN team fallback requests run concurrently.
- Render uses one Gunicorn worker with multiple threads to reduce duplicated cache memory on the free instance.

This specifically prevents Render's first `/api/dashboard` request from doing all expensive work before the browser can display anything.


## V7 interactive UI

V7 keeps the V6.2 progressive-loading architecture and adds a fantasy-app style presentation layer:

- desktop sidebar + mobile bottom navigation
- draft-room hero and live data status
- player search
- position filters
- position-coded player identities
- local browser watchlist
- compare up to three ranked players
- lazy five-year player-analysis cards
- visual sleeper momentum bars
- visual injury-risk bars
- offense/defense league-rank bars
- responsive player and team cards
- improved Sleeper roster presentation
- richer Data Health cards

The interface intentionally borrows common fantasy-product interaction patterns without copying any third-party brand or visual identity.


## V7.1 — ESPN Cache + News Radar

### ESPN cache
ESPN team-stat fallback now uses a stale-safe disk cache:
- current-season ESPN data: 6-hour refresh
- completed-season ESPN data: 30-day refresh
- current-season stale fallback: up to 7 days
- historical stale fallback: up to 180 days

If an ESPN refresh fails, the last successful cache is served instead of returning an empty team panel.

### News Radar
A new lazy-loaded News Radar tab aggregates recent NFL/fantasy articles from:
- ESPN
- NFL.com
- CBS Sports
- FantasyPros
- Yahoo Sports

Primary direct feeds are used where available. Source-restricted Google News RSS is used as a discovery fallback for sites without a convenient public RSS endpoint.

News behavior:
- cached for 30 minutes
- last successful feed can be served for up to 24 hours if refresh providers fail
- up to 60 deduplicated stories
- filters by publisher
- direct external article links
- ranking uses freshness + fantasy-football keyword relevance
- ranking is not presented as publisher view-count/popularity data

The News tab loads on demand so it does not slow the initial Render dashboard request.


## V8 — League HQ + sports-product redesign

### Interface
V8 replaces the neon/gradient dashboard style with a denser editorial sports interface:
- ink/navy navigation
- warm off-white surfaces
- burnt-orange accent
- flatter cards and tighter spacing
- roster/table views that prioritize information density
- starters grouped separately from the bench
- league and waiver context kept on the same League HQ screen

### Sleeper League HQ
Connect a Sleeper username and choose one of that user's 2026 leagues. The connection is read-only and requires no Sleeper password.

League HQ retrieves:
- league scoring settings and roster positions
- all league rosters and users
- the connected manager's roster
- current NFL week and matchup when available
- recent team transactions
- current Sleeper player metadata
- the actual unrostered/free-agent pool

It then calculates:
- overall roster grade relative to that league
- league rank
- QB/RB/WR/TE/K/DST position grades
- starter strength
- bench depth
- roster diagnosis
- top available pickups
- lowest-value bench players
- suggested add/drop pairs

Player value uses prior-season fantasy production, current Command Center board rank, Sleeper market/search rank and current injury designation. Pickup recommendations also include the connected team's weakest positions and Sleeper add momentum.

### Provider roadmap
- Sleeper: live now
- Yahoo: official Fantasy Sports API is available through Yahoo OAuth and is the recommended future integration path
- ESPN: future adapter should use a secure authenticated integration for private leagues; V8 does not request or store ESPN passwords
