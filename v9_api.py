"""V9 decision tools and opt-in private tester workspaces."""

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from flask import jsonify, request

from v9_engine import compare_trade, optimize, scoring_rules, slots_from, waiver_moves


@contextmanager
def database(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS workspaces (token TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL)"
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def register_v9(app, core):
    app.config.setdefault("WORKSPACE_DB", str(Path(core["CACHE_DIR"]) / "workspaces.sqlite3"))

    def owner():
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Open a workspace with its 64-character private recovery key first.")
        return hashlib.sha256(token.encode()).hexdigest()

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Request exceeds the 4 MB limit."), 413

    @app.get("/api/v9/profile")
    def v9_profile():
        try:
            name = request.args.get("name", "").strip()[:100]
            pos = request.args.get("position", "").upper()
            season = int(request.args.get("season") or core["latest_stats_season"]())
            if not name or pos not in core["ALL_POSITIONS"] or not 1999 <= season <= core["SEASON"]:
                raise ValueError("Choose a player, position and valid season.")
            rows = core["load_player_weekly_stats"](season)
            matches = [
                r
                for r in rows
                if core["norm_name"](r.get("player_display_name") or r.get("player_name"))
                == core["norm_name"](name)
                and (r.get("position") or r.get("position_group")) == pos
                and r.get("season_type", "REG") == "REG"
            ]
            scoring = request.args.get("scoring", "PPR")
            weeks = [
                {
                    "week": int(r["week"]),
                    "points": round(core["fantasy_points"](r, scoring), 2),
                    "targets": r.get("targets"),
                    "carries": r.get("carries"),
                    "receptions": r.get("receptions"),
                }
                for r in matches
                if str(r.get("week", "")).isdigit()
            ]
            weeks.sort(key=lambda r: r["week"])
            return jsonify(
                name=name,
                season=season,
                weeks=weeks,
                source="nflverse regular-season player statistics",
                source_url=core["nflverse_player_week_urls"](season)[0],
                retrieved_at=time.time(),
                note="Historical results, not weekly projections. Missing weeks are not zero-point games.",
            )
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Player history unavailable")
            return jsonify(error="Historical data is temporarily unavailable. Please retry."), 503

    @app.post("/api/v9/decisions")
    def v9_decisions():
        try:
            data = body()
            mode = data.get("scoring", "PPR")
            rules, unsupported = scoring_rules(mode, data.get("scoring_rules"))
            if unsupported:
                raise ValueError("Unsupported scoring rules: " + ", ".join(unsupported))
            slots = slots_from(data.get("slots", {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}))
            if not slots:
                raise ValueError("Choose at least one starting slot.")
            groups = {}
            for key, limit in [
                ("roster", 30),
                ("available", 100),
                ("opponent", 30),
                ("give", 10),
                ("receive", 10),
                ("protected", 30),
            ]:
                raw = data.get(key, [])
                if (
                    not isinstance(raw, list)
                    or len(raw) > limit
                    or any(not isinstance(p, (str, int)) for p in raw)
                ):
                    raise ValueError(f"{key} must be a player ID list with at most {limit} entries.")
                groups[key] = list(dict.fromkeys(map(str, raw)))
            if not groups["roster"]:
                raise ValueError("Add your roster before comparing decisions.")
            values = core["league_value_map"](
                mode, json.dumps(rules, sort_keys=True) if data.get("scoring_rules") is not None else ""
            )
            if any(pid not in values for group in groups.values() for pid in group):
                raise ValueError("An unknown player was selected. Reload the catalog.")
            if set(groups["roster"]) & set(groups["available"]):
                raise ValueError("A rostered player cannot also be available.")
            result = {
                "lineup": optimize(groups["roster"], values, slots),
                "waivers": waiver_moves(
                    groups["roster"], groups["available"], values, slots, protected=groups["protected"]
                ),
                "scoring_rules": rules,
                "slots": slots,
                "generated_at": time.time(),
                "basis_season": core["PRIOR_SEASON"],
                "horizon": "Roster value",
                "evidence": "Model index: 58% prior-season production percentile, 27% Sleeper search rank, 15% board rank, minus status penalties. This is not projected fantasy points or a weekly forecast. K/DST estimates are limited. Availability is supplied by you.",
            }
            if groups["give"] or groups["receive"]:
                result["trade"] = compare_trade(
                    groups["roster"], groups["opponent"], groups["give"], groups["receive"], values, slots
                )
            return jsonify(result)
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Decision model unavailable")
            return jsonify(error="Player data is temporarily unavailable. Please retry."), 503

    @app.route("/api/v9/workspace", methods=["GET", "PUT", "DELETE"])
    def v9_workspace():
        try:
            key = owner()
            with database(app.config["WORKSPACE_DB"]) as db:
                if request.method == "GET":
                    row = db.execute("SELECT state, updated FROM workspaces WHERE token=?", (key,)).fetchone()
                    return jsonify(state=json.loads(row[0]) if row else None, updated=row[1] if row else None)
                if request.method == "DELETE":
                    db.execute("DELETE FROM workspaces WHERE token=?", (key,))
                    db.execute("DELETE FROM feedback WHERE owner=?", (key,))
                    return jsonify(deleted=True)
                data = body()
                encoded = json.dumps(data)
                if len(encoded) > 100000:
                    raise ValueError("Workspace exceeds 100 KB.")
                # No provider credentials belong in a workspace.
                allowed = {"team", "watch", "protected", "opponent", "version"}
                if set(data) - allowed:
                    raise ValueError("Unrecognized workspace fields.")
                db.execute(
                    "INSERT INTO workspaces VALUES (?, ?, ?) ON CONFLICT(token) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                    (key, encoded, time.time()),
                )
            return jsonify(saved=True)
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400

    @app.post("/api/v9/feedback")
    def v9_feedback():
        try:
            key = owner()
            data = body()
            message = str(data.get("message", "")).strip()
            if not 5 <= len(message) <= 2000:
                raise ValueError("Describe the issue in 5–2000 characters.")
            record = json.dumps(
                {"message": message, "snapshot": data.get("snapshot"), "version": "10.0-beta"}
            )
            if len(record) > 100000:
                raise ValueError("Feedback snapshot exceeds 100 KB.")
            ident = secrets.token_hex(8)
            with database(app.config["WORKSPACE_DB"]) as db:
                db.execute("INSERT INTO feedback VALUES (?, ?, ?, ?)", (ident, key, record, time.time()))
            return jsonify(id=ident)
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
