"""Read-only Yahoo import. Network/token handling stays in app.py.

Normalizes official Yahoo resources into the existing model estimator. It does
not pretend to calculate a league-relative grade without every league roster.
"""

import re

TEAM_KEY = re.compile(r"^\d+\.l\.\d+\.t\.\d+$")
SLOTS = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "W/R/T": "FLEX",
    "Q/W/R/T": "SUPER_FLEX",
    "W/R": "WRRB_FLEX",
    "W/T": "REC_FLEX",
    "K": "K",
    "DEF": "DST",
}


def import_team(team_key, token, api, entities, merge, values_for, analyze):
    if not TEAM_KEY.fullmatch(team_key):
        raise ValueError("Invalid Yahoo team key.")
    owned = entities(api("/users;use_login=1/games;game_keys=nfl/teams", token), "team")
    selected = next((t for t in owned if t.get("team_key") == team_key), None)
    if selected is None:
        raise PermissionError("Choose a team from your connected Yahoo account.")
    league_key = team_key.rsplit(".t.", 1)[0]
    leagues = entities(api(f"/league/{league_key}/settings", token), "league")
    if not leagues:
        raise ValueError("Yahoo did not return league settings.")
    league = leagues[0]
    settings = merge(league.get("settings", {}))
    slots = {v: 0 for v in SLOTS.values()}
    raw_slots = settings.get("roster_positions", [])
    if isinstance(raw_slots, dict):
        raw_slots = list(raw_slots.values())
    for entry in raw_slots:
        if not isinstance(entry, dict):
            continue
        slot = merge(entry.get("roster_position", entry))
        position = slot.get("position")
        count = int(slot.get("count") or 0)
        if position in ("BN", "IR", "IR+", "NA") or count == 0:
            continue
        if position not in SLOTS:
            raise ValueError(
                f"Yahoo roster slot {position} is not supported by this model yet. Use Manual Team with compatible slots."
            )
        slots[SLOTS[position]] += count
    if not any(slots.values()):
        raise ValueError("Yahoo starting slots could not be read. No default lineup was assumed.")
    scoring = "STD"
    modifiers = merge(settings.get("stat_modifiers", {})).get("stats", [])
    if isinstance(modifiers, dict):
        modifiers = list(modifiers.values())
    # Yahoo NFL stat 11 is receptions. The model uses a standard scoring preset;
    # custom scoring is explicitly disclosed rather than claimed as exact.
    for entry in modifiers:
        if not isinstance(entry, dict):
            continue
        stat = merge(entry.get("stat", entry))
        if str(stat.get("stat_id")) == "11":
            rec = float(stat.get("value") or 0)
            scoring = "PPR" if rec >= 1 else "HALF" if rec > 0 else "STD"
    values = values_for(scoring)
    index = {}

    def norm(name):
        return "".join(c for c in name.lower() if c.isalnum())

    for pid, p in values.items():
        index.setdefault((norm(p["name"]), p["position"]), []).append(pid)
    aliases = {"JAC": "JAX", "WAS": "WSH", "LA": "LAR"}

    def match(player):
        pos = player.get("display_position") or player.get("primary_position") or ""
        if pos == "DEF":
            team = player.get("editorial_team_abbr", "").upper()
            team = aliases.get(team, team)
            return team if team in values else None
        name = player.get("name", {})
        name = name.get("full", "") if isinstance(name, dict) else str(name)
        matches = index.get((norm(name), pos), [])
        return matches[0] if len(matches) == 1 else None

    roster = entities(api(f"/team/{team_key}/roster/players", token), "player")
    if not roster:
        raise ValueError("Yahoo roster is empty or has not been drafted.")
    ids, missing = [], []
    for player in roster:
        pid = match(player)
        if pid:
            ids.append(pid)
        else:
            name = player.get("name", {})
            missing.append(name.get("full", "Unknown") if isinstance(name, dict) else str(name))
    if missing:
        raise ValueError(
            "Cannot grade an incomplete import. Players not matched: "
            + ", ".join(missing)
            + ". Use Manual Team or refresh the player catalog."
        )
    # Fetch a bounded, ranked candidate pool. Yahoo allows 25 players per page.
    # FA excludes players already rostered and players still on waivers.
    available, seen, unmatched = [], set(), 0
    for start in range(0, 100, 25):
        players = entities(
            api(f"/league/{league_key}/players;status=FA;sort=OR;start={start};count=25", token), "player"
        )
        if not players:
            break
        for player in players:
            pid = match(player)
            if pid and pid not in ids and pid not in seen:
                seen.add(pid)
                available.append(pid)
            elif not pid:
                unmatched += 1
        if len(players) < 25:
            break
    result = analyze(
        {
            "roster": ids,
            "available": available,
            "availability_confirmed": True,
            "scoring": scoring,
            "slots": slots,
            "league_size": league.get("num_teams") or 12,
            "team_name": selected.get("name") or "Yahoo Team",
            "league_name": league.get("name") or "Yahoo League",
        }
    )
    result["provider"] = "Yahoo"
    result["league"].update(league_id=league_key, season=league.get("season"), status="imported")
    result["team"]["roster_id"] = team_key
    result["availability_mode"] = "yahoo_free_agents"
    result["methodology"] = (
        f"Yahoo roster and starting slots imported. Model estimate using {scoring} baseline scoring, not an exact custom-scoring or league-relative grade. "
        "Lineup shows model-selected starters, not your submitted Yahoo lineup. "
        "Suggestions use up to 100 Yahoo-ranked free agents; waiver-locked players are excluded. Availability may change after import. "
        f"{unmatched} unmatched free-agent entries excluded. Refresh by loading the team again."
    )
    return result
