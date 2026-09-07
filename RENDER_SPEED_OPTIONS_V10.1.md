# Render speed options

The deployment file currently targets Render's Free web service. The application has two different speed problems: the first visit after the service sleeps has startup latency, while repeat visits can be made faster by reusing the board already seen in this browser. This release addresses the second problem and removes an extra `/health` request before every board load.

## Included in this hotfix

- The board stores the last successful public ranking response per scoring mode in browser storage and renders it immediately on the next visit while the server refreshes it.
- Static JavaScript and CSS responses receive a one-hour browser cache policy.
- The board no longer performs a separate health-check request before asking for dashboard data.
- Private league responses remain network-only; they are never placed in the public board snapshot.

## Deployment choices

| Choice | Approximate infrastructure cost | What it improves | Tradeoff |
| --- | ---: | --- | --- |
| Keep Free + this code | $0 | Returning visits feel immediate; no migration | Render can sleep after inactivity, so the first request still has wake-up latency. Local disk cache can disappear after sleep/restart/redeploy. |
| Render Starter + 1 GB persistent disk | about $7.25/month before tax/overages | Always-on service plus durable source caches and SQLite when `CACHE_DIR=/var/data` is configured | One service instance; still needs the code/indexing work below for consistently fast cold data. |
| Render Standard + 1 GB disk | about $25.25/month before tax/overages | More CPU and memory for concurrent comparisons, OCR matching, and 10–20 testers | Costs more and does not fix an upstream feed that is slow or unavailable. |
| Background refresh + indexed history | depends on worker/database choice | Moves CSV parsing and feed downloads out of user requests; gives stable warm response times | Larger V10.2 architecture change; add after measuring real request timings. |

## Recommended path for this group

1. Deploy this hotfix on the current service and record cold, warm, and 10-user-concurrent timings for `/api/dashboard`, `/api/v10/compare`, and `/api/v10/team-report`.
2. If cold starts are the main complaint, move the web service to Starter and mount a persistent disk at `/var/data`; set `CACHE_DIR=/var/data` in Render. Do not change the worker count until memory is measured because the rankings and historical rows are held in Python memory.
3. If warm requests still exceed about two seconds, pre-index player histories once per season and refresh public rankings in a scheduled job. The comparison and team-report routes can then read compact per-player records instead of parsing the full weekly dataset during a request.

Render references: [Free web services](https://render.com/docs/free), [persistent disks](https://render.com/docs/disks), and [Render's hosting cost comparison](https://render.com/articles/render-vs-railway).
