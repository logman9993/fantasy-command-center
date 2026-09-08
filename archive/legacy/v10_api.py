"""Screenshot-name matching, player comparisons and actionable team reports."""

import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from flask import jsonify, request

from v9_engine import ELIGIBLE, optimize


def attach_photos(rankings, players, norm_name, player_name):
    identities = {(norm_name(player_name(p)), p.get("position")): str(pid) for pid, p in players.items()}
    result = {}
    for pos, rows in rankings.items():
        result[pos] = []
        for row in rows:
            pid = identities.get((norm_name(row["name"]), pos))
            result[pos].append(
                {
                    **row,
                    "id": pid,
                    "photo": f"https://sleepercdn.com/content/nfl/players/{pid}.jpg"
                    if pid and pid.isdigit()
                    else "",
                }
            )
    return result


def tokens(text):
    text = re.sub(r"[^a-z0-9 ]", "", text.lower().replace("-", " ").replace("’", "'"))
    return [word for word in text.split() if word not in {"jr", "sr", "ii", "iii", "iv"}]


def match_roster_text(text, catalog):
    """Conservative identity matching: ambiguous initials are never auto-selected."""
    matches = {}
    uncertain = []
    for line in text.splitlines()[:250]:
        words = tokens(line)
        if not words:
            continue
        candidates = []
        for player in catalog:
            name = tokens(player["name"])
            if len(name) < 2:
                # Team defenses must contain an explicit DST/DEF marker.
                exact = (
                    player["position"] == "DST"
                    and player["team"].lower() in words
                    and any(w in words for w in ["dst", "def", "defense"])
                )
            else:
                exact = any(words[i : i + len(name)] == name for i in range(len(words) - len(name) + 1))
            abbreviated = len(name) >= 2 and any(
                words[i] == name[0][0] and words[i + 1 : i + len(name)] == name[1:]
                for i in range(len(words) - len(name) + 1)
            )
            if exact or abbreviated:
                candidates.append((1 if exact else 0.92, player))
        # If no full/initial match, offer a small set of likely OCR corrections.
        if not candidates and len(words) >= 2:
            for player in catalog:
                name = tokens(player["name"])
                if len(name) < 2:
                    continue
                score = max(
                    (
                        SequenceMatcher(None, " ".join(name), " ".join(words[i : i + len(name)])).ratio()
                        for i in range(max(0, len(words) - len(name) + 1))
                    ),
                    default=0,
                )
                if score >= 0.86:
                    candidates.append((score, player))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            continue
        best = candidates[0][0]
        choices = [p for score, p in candidates if score >= best - 0.04][:5]
        if len(choices) == 1 and best == 1:
            p = choices[0]
            matches[p["id"]] = {**p, "recognized_line": line[:180], "match": "full name"}
        else:
            uncertain.append(
                {"line": line[:180], "choices": choices, "reason": "Review abbreviated or imperfect text"}
            )
    return {
        "matches": list(matches.values()),
        "review": uncertain[:40],
        "note": "Review every selection. Only visible, recognized players can be imported; missing bench/IR players need another screenshot or manual entry.",
    }


def has_points(row, position):
    fields = {
        "QB": ["passing_yards", "passing_tds"],
        "RB": ["rushing_yards", "carries", "receiving_yards"],
        "WR": ["receiving_yards", "targets"],
        "TE": ["receiving_yards", "targets"],
        "K": ["field_goals_made", "fg_made", "extra_points_made", "pat_made"],
    }.get(position, [])
    return any(row.get(field) not in (None, "", "NA") for field in fields)


def register_v10(app, core):
    def catalog(scoring="PPR"):
        result = core["manual_player_catalog"](scoring)
        return [{**p, "photo": photo(p["id"], p["position"])} for p in result]

    def photo(pid, position):
        return (
            f"https://sleepercdn.com/content/nfl/players/{pid}.jpg"
            if str(pid).isdigit() and position != "DST"
            else ""
        )

    def schedule(week):
        try:
            rows, _ = core["cached_csv"](
                "v10_schedule",
                300,
                ["https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"],
                ["season", "week", "home_team", "away_team"],
            )
            return [
                r
                for r in rows
                if str(r.get("season")) == str(core["SEASON"])
                and str(r.get("week")) == str(week)
                and r.get("game_type", "REG") == "REG"
            ]
        except Exception:
            return []

    def matchup(team, rows):
        team = {"WSH": "WAS", "LAR": "LA"}.get(team, team)
        game = next((r for r in rows if team in (r.get("home_team"), r.get("away_team"))), None)
        if not game:
            return {
                "opponent": None,
                "label": "No matchup found" if rows else "Schedule unavailable",
                "locked": False,
                "scheduled": False,
            }
        away = game["away_team"] == team
        kickoff = None
        try:
            kickoff = (
                datetime.fromisoformat(game["gameday"] + "T" + game["gametime"])
                .replace(tzinfo=ZoneInfo("America/New_York"))
                .astimezone(timezone.utc)
            )
        except (KeyError, ValueError):
            pass
        opponent = game["home_team"] if away else game["away_team"]
        return {
            "opponent": opponent,
            "label": f"{'@' if away else 'vs'} {opponent} · {game.get('gameday', '')} {game.get('gametime', '')} ET",
            "locked": bool(kickoff and kickoff <= datetime.now(timezone.utc)),
            "scheduled": True,
            "kickoff": kickoff.isoformat() if kickoff else None,
        }

    def profile(player, season, scoring):
        rows = core["load_player_weekly_stats"](season)
        selected = [
            r
            for r in rows
            if core["norm_name"](r.get("player_display_name") or r.get("player_name"))
            == core["norm_name"](player["name"])
            and (r.get("position") or r.get("position_group"))
            in ({"K", "PK"} if player["position"] == "K" else {player["position"]})
            and r.get("season_type", "REG") == "REG"
        ]
        weeks = []
        fields = [
            "completions",
            "attempts",
            "passing_yards",
            "passing_tds",
            "passing_interceptions",
            "carries",
            "rushing_yards",
            "rushing_tds",
            "targets",
            "receptions",
            "receiving_yards",
            "receiving_tds",
            "sacks_suffered",
            "field_goals_made",
            "extra_points_made",
        ]
        for row in selected:
            row = dict(row)
            for canonical, alias in [("field_goals_made", "fg_made"), ("extra_points_made", "pat_made")]:
                if row.get(canonical) in (None, "", "NA"):
                    row[canonical] = row.get(alias)
            if not str(row.get("week", "")).isdigit():
                continue
            weeks.append(
                {
                    "week": int(row["week"]),
                    "points": round(core["fantasy_points"](row, scoring), 2)
                    if has_points(row, player["position"])
                    else None,
                    **{field: core["num"](row, field, None) for field in fields},
                }
            )
        weeks.sort(key=lambda r: r["week"])
        totals = {
            field: round(sum(r[field] for r in weeks if r[field] is not None), 2)
            if any(r[field] is not None for r in weeks)
            else None
            for field in fields
        }
        points = [r["points"] for r in weeks if r["points"] is not None]
        totals["completion_pct"] = (
            round(100 * totals["completions"] / totals["attempts"], 1)
            if totals["attempts"] and totals["completions"] is not None
            else None
        )
        totals["yards_per_attempt"] = (
            round(totals["passing_yards"] / totals["attempts"], 2)
            if totals["attempts"] and totals["passing_yards"] is not None
            else None
        )
        totals["yards_per_carry"] = (
            round(totals["rushing_yards"] / totals["carries"], 2)
            if totals["carries"] and totals["rushing_yards"] is not None
            else None
        )
        return {
            **player,
            "season": season,
            "weeks": weeks,
            "totals": totals,
            "games": len(weeks),
            "points": round(sum(points), 2) if points else None,
            "ppg": round(statistics.mean(points), 2) if points else None,
            "recent_ppg": round(statistics.mean(points[-4:]), 2) if points else None,
            "recent_games": min(4, len(points)),
            "source_url": core["nflverse_player_week_urls"](season)[0],
        }

    def start_advice(players, forms, week):
        # The selected historical display year must never alter a current-week lean.
        reasons = []
        eligible = []
        for p, form in zip(players, forms):
            status = str(p.get("injury_status") or "").lower()
            if status in {"out", "ir", "doubtful", "suspended", "pup", "physically unable to perform"}:
                reasons.append(
                    f"{p['name']} is listed {status}; do not rely on them without an updated designation."
                )
            elif p["matchup"]["locked"]:
                reasons.append(f"{p['name']}'s scheduled game has started; check your league's lineup lock.")
            elif not p["matchup"]["scheduled"]:
                reasons.append(f"{p['name']}: a playable matchup could not be verified for week {week}.")
            else:
                eligible.append((p, form))
        chosen = None
        label = "No start recommendation"
        positions = {p["position"] for p in players}
        if len(positions) > 1 and not positions <= {"RB", "WR", "TE"}:
            reasons.append(
                "Choose the same position or two RB/WR/TE flex options for a meaningful start comparison."
            )
        elif any(p["matchup"]["locked"] for p in players):
            label = "Check your lineup lock"
        elif len(eligible) == 1:
            chosen = eligible[0][0]["id"]
            label = "Availability-based start lean"
        elif len(eligible) == 2:
            a, b = eligible
            # Cross-position choices must be valid flex competitors, not a QB vs a kicker.
            if a[0]["position"] != b[0]["position"] and not {a[0]["position"], b[0]["position"]} <= {
                "RB",
                "WR",
                "TE",
            }:
                reasons.append(
                    "Choose the same position or two RB/WR/TE flex options for a meaningful start comparison."
                )
            elif (
                a[1]["recent_ppg"] is not None
                and b[1]["recent_ppg"] is not None
                and a[1]["recent_games"] >= 3
                and b[1]["recent_games"] >= 3
            ):
                diff = a[1]["recent_ppg"] - b[1]["recent_ppg"]
                if abs(diff) >= 1:
                    chosen = a[0]["id"] if diff > 0 else b[0]["id"]
                    label = "Provisional start lean"
                else:
                    label = "Too close to call"
                for p, f in eligible:
                    reasons.append(
                        f"{p['name']}: {f['recent_ppg']} actual PPG over the last {f['recent_games']} available games in {f['season']}."
                    )
            else:
                reasons.append("Not enough scored game history to make a defensible comparison.")
        for p in players:
            if str(p.get("injury_status") or "").lower() == "questionable":
                reasons.append(f"{p['name']} is questionable. Check the inactive list before kickoff.")
        return {
            "player_id": chosen,
            "label": label,
            "reasons": reasons,
            "basis": "Historical recent form plus current reported status and schedule. Not expert consensus, a win probability, or a matchup-adjusted weekly projection. Confirm current role and news before locking your lineup.",
        }

    @app.get("/api/v10/catalog")
    def v10_catalog():
        try:
            scoring = request.args.get("scoring", "PPR")
            if scoring not in core["SCORING"]:
                raise ValueError("Unknown scoring format.")
            state = core["sleeper_state"]()
            return jsonify(
                items=catalog(scoring),
                season=core["SEASON"],
                week=max(1, min(18, int(state.get("week") or 1))),
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("V10 catalog unavailable")
            return jsonify(error="Player catalog unavailable. Retry shortly."), 503

    @app.post("/api/v10/roster-match")
    def roster_match():
        data = request.get_json(silent=True)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("text"), str)
            or not 1 <= len(data["text"]) <= 20000
        ):
            return jsonify(error="Provide 1–20,000 characters of recognized roster text."), 400
        try:
            return jsonify(match_roster_text(data["text"], catalog()))
        except Exception:
            app.logger.exception("Roster matching failed")
            return jsonify(error="Player matching unavailable. Your current roster was not changed."), 503

    @app.get("/api/v10/compare")
    def compare():
        try:
            scoring = request.args.get("scoring", "PPR")
            if scoring not in core["SCORING"]:
                raise ValueError("Unknown scoring format.")
            ids = [request.args.get("a"), request.args.get("b")]
            if not all(ids) or ids[0] == ids[1]:
                raise ValueError("Choose two different players.")
            lookup = {p["id"]: p for p in catalog(scoring)}
            if any(pid not in lookup for pid in ids):
                raise ValueError("Choose both players from the catalog.")
            latest = core["latest_stats_season"]()
            season = int(request.args.get("season") or latest or core["PRIOR_SEASON"])
            week = int(request.args.get("week") or core["sleeper_state"]().get("week") or 1)
            if not 1 <= week <= 18 or season not in core["stat_season_choices"]():
                raise ValueError("Choose a valid regular-season week and history season.")
            selected = [lookup[pid] for pid in ids]
            games = schedule(week)
            with ThreadPoolExecutor(max_workers=2) as pool:
                history = list(pool.map(lambda p: profile(p, season, scoring), selected))
                forms = (
                    history
                    if season == latest
                    else list(pool.map(lambda p: profile(p, latest, scoring), selected))
                )
            for p in history:
                p["matchup"] = matchup(p["team"], games)
            return jsonify(
                players=history,
                recommendation=start_advice(history, forms, week),
                week=week,
                season=core["SEASON"],
                stats_season=season,
                latest_stats_season=latest,
                scoring=scoring,
                checked_at=time.time(),
            )
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Comparison data unavailable")
            return jsonify(error="Comparison data is temporarily unavailable. Please retry."), 503

    @app.post("/api/v10/team-report")
    def team_report():
        try:
            data = request.get_json(silent=True)
            result = core["manual_team_analysis"](data)
            values = core["league_value_map"](data.get("scoring", "PPR"))
            ids = [str(pid) for pid in data["roster"] if str(pid) in values]
            slots = {
                pos: result["league"]["roster_positions"].count(pos)
                for pos in set(result["league"]["roster_positions"])
            }
            lineup = optimize(ids, values, slots)
            priorities = []
            missing = [s["slot"] for s in lineup["lineup"] if not s["player"]]
            if missing:
                priorities.append(
                    {
                        "title": "Fill your empty starting slots",
                        "why": f"Your best eligible lineup leaves {', '.join(missing)} empty.",
                        "action": "Add the missing screenshot pages or roster players first; if the roster is complete, target eligible free agents before considering luxury bench depth.",
                    }
                )
            for pos, grade in sorted(
                result["team"]["position_grades"].items(), key=lambda item: item[1]["score"]
            )[:2]:
                starters = [
                    s["player"] for s in lineup["lineup"] if s["player"] and s["player"]["position"] == pos
                ]
                bench = [p for p in lineup["bench"] if p["position"] in ELIGIBLE.get(pos, {pos})]
                names = ", ".join(p["name"] for p in starters) or "No eligible starter"
                targets = [p for p in result.get("pickups", []) if p.get("position") == pos][:3]
                target_note = (
                    (" Potential " + pos + " targets: " + ", ".join(p["name"] for p in targets) + ".")
                    if targets
                    else (" No " + pos + " upgrade is in the supplied candidate pool.")
                )
                priorities.append(
                    {
                        "title": f"{'Upgrade' if grade['score'] < 70 else 'Review depth at'} {pos}",
                        "why": f"{names}. Unit model score: {grade['score']}/100; {len(bench)} eligible bench option(s).",
                        "action": f"Compare available {pos} options against your weakest usable starter. {'Keep a healthy backup or investigate a trade before dropping depth.' if not bench else 'Use the before/after lineup impact below to decide whether a pickup actually improves the team.'}"
                        + target_note,
                    }
                )
            injured = [values[pid] for pid in ids if values[pid].get("injury_status")]
            if injured:
                priorities.insert(
                    0,
                    {
                        "title": "Plan around your injury designations",
                        "why": "; ".join(f"{p['name']}: {p['injury_status']}" for p in injured),
                        "action": "Confirm the current inactive list and keep an eligible replacement. A designation alone is not a reason to drop a player.",
                    },
                )
            priorities.append(
                {
                    "title": "Make availability explicit",
                    "why": f"You marked {len(data.get('available', []))} players available.",
                    "action": "Use only the players genuinely available in your league for actionable swaps. Unconfirmed names below are scouting targets, not verified waiver claims.",
                }
            )
            result["priorities"] = priorities
            result["report_note"] = (
                "Roster-specific model guidance, not a weekly points forecast. Empty slots, bench depth and reported injuries drive the priorities. Screenshot imports do not establish league scoring, opponent rosters or waiver availability."
            )
            return jsonify(result)
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Team report unavailable")
            return jsonify(error="Team report unavailable. Please retry."), 503
