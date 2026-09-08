"""Provider-independent scoring and roster simulations. No network or side effects."""

import math

ELIGIBLE = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DST": {"DST"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
    "REC_FLEX": {"WR", "TE"},
}
ALIASES = {
    "DEF": "DST",
    "D/ST": "DST",
    "SF": "SUPER_FLEX",
    "W/R/T": "FLEX",
    "Q/W/R/T": "SUPER_FLEX",
    "W/R": "WRRB_FLEX",
    "W/T": "REC_FLEX",
}
RESERVE = {"BN", "IR", "IR+", "RES", "NA"}
DEFAULT_RULES = {
    "pass_yd": 0.04,
    "pass_td": 4,
    "pass_int": -2,
    "rush_yd": 0.1,
    "rush_td": 6,
    "rec_yd": 0.1,
    "rec_td": 6,
    "rec": 1,
    "fum_lost": -2,
    "pass_2pt": 2,
    "rush_2pt": 2,
    "rec_2pt": 2,
    "st_td": 6,
    "fgm": 3,
    "xpm": 1,
}
STAT_FIELDS = {
    "pass_yd": ("passing_yards",),
    "pass_td": ("passing_tds",),
    "pass_int": ("passing_interceptions",),
    "rush_yd": ("rushing_yards",),
    "rush_td": ("rushing_tds",),
    "rec_yd": ("receiving_yards",),
    "rec_td": ("receiving_tds",),
    "rec": ("receptions",),
    "fum_lost": ("rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"),
    "pass_2pt": ("passing_2pt_conversions",),
    "rush_2pt": ("rushing_2pt_conversions",),
    "rec_2pt": ("receiving_2pt_conversions",),
    "st_td": ("special_teams_tds",),
    "fgm": ("field_goals_made",),
    "xpm": ("extra_points_made",),
    "bonus_rec_te": ("receptions",),
}
# Defensive scoring belongs to the defensive feed, never an offensive stat line.
DEF_RULES = {
    "sack",
    "int",
    "fum_rec",
    "safe",
    "def_td",
    "blk_kick",
    "pts_allow_0",
    "pts_allow_1_6",
    "pts_allow_7_13",
    "pts_allow_14_20",
    "pts_allow_21_27",
    "pts_allow_28_34",
    "pts_allow_35p",
    "def_st_td",
    "def_st_ff",
    "def_st_fum_rec",
}


def finite(value, default=0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (ValueError, TypeError):
        return default


def scoring_rules(mode="PPR", custom=None):
    if custom is None:
        rules = dict(DEFAULT_RULES)
        rules["rec"] = {"PPR": 1, "HALF": 0.5, "STD": 0}.get(mode, 1)
        return rules, []
    if not isinstance(custom, dict):
        raise ValueError("Scoring rules must be an object.")
    rules = {}
    unsupported = []
    for key, value in custom.items():
        number = finite(value, None)
        if number is None or abs(number) > 1000:
            raise ValueError(f"Invalid scoring coefficient: {key}")
        if key in STAT_FIELDS:
            rules[key] = number
        elif key not in DEF_RULES and number != 0:
            unsupported.append(key)
    return rules, sorted(unsupported)


def score_stats(row, rules):
    row = dict(row)
    for canonical, alias in (("field_goals_made", "fg_made"), ("extra_points_made", "pat_made")):
        if row.get(canonical) in (None, "", "NA") and row.get(alias) not in (None, "", "NA"):
            row[canonical] = row[alias]
    total = 0
    for key, coefficient in rules.items():
        if key == "bonus_rec_te" and row.get("position") != "TE":
            continue
        total += sum(finite(row.get(field)) for field in STAT_FIELDS.get(key, ())) * coefficient
    return round(total, 4)


def slots_from(raw):
    counts = {}
    if isinstance(raw, dict):
        pairs = raw.items()
    elif isinstance(raw, list):
        pairs = ((slot, 1) for slot in raw)
    else:
        raise ValueError("Starting slots must be a list or object.")
    for slot, count in pairs:
        slot = ALIASES.get(str(slot).upper(), str(slot).upper())
        if slot in RESERVE:
            continue
        if slot not in ELIGIBLE:
            raise ValueError(f"Unsupported starting slot: {slot}")
        amount = finite(count, None)
        if amount is None or amount != int(amount) or not 0 <= amount <= 8:
            raise ValueError(f"Invalid number of {slot} slots.")
        counts[slot] = counts.get(slot, 0) + int(amount)
    if sum(counts.values()) > 24:
        raise ValueError("At most 24 starting slots are supported.")
    return counts


def position(player):
    return ALIASES.get(player.get("position"), player.get("position"))


def optimize(ids, values, slots, metric="value", locked=None, unavailable=None):
    """Maximum-weight matching, including overlapping flex eligibility.

    locked maps a zero-based slot index to a player ID. Negative values are
    allowed, but leaving a slot empty is better than a negative forecast.
    """
    counts = slots_from(slots)
    labels = [s for s, n in counts.items() for _ in range(n)]
    ids = list(dict.fromkeys(str(i) for i in ids))
    locked = locked or {}
    excluded = {str(i) for i in (unavailable or [])}
    selected = {}
    for index, pid in locked.items():
        index = int(index)
        pid = str(pid)
        if index < 0 or index >= len(labels) or pid not in ids or pid not in values:
            raise ValueError("A locked player or slot is missing from the roster.")
        if position(values[pid]) not in ELIGIBLE[labels[index]] or pid in selected.values():
            raise ValueError("Invalid locked lineup assignment.")
        selected[index] = pid
    pool = [pid for pid in ids if pid in values and pid not in selected.values() and pid not in excluded]
    open_slots = [i for i in range(len(labels)) if i not in selected]
    # Residual graph: source -> players -> eligible slots -> sink.
    size = 2 + len(pool) + len(open_slots)
    sink = size - 1
    graph = [[] for _ in range(size)]

    def edge(a, b, cost):
        graph[a].append([b, len(graph[b]), 1, cost])
        graph[b].append([a, len(graph[a]) - 1, 0, -cost])

    for p, pid in enumerate(pool):
        edge(0, 1 + p, 0)
        for j, i in enumerate(open_slots):
            if position(values[pid]) in ELIGIBLE[labels[i]]:
                edge(1 + p, 1 + len(pool) + j, -finite(values[pid].get(metric)))
    for j in range(len(open_slots)):
        edge(1 + len(pool) + j, sink, 0)
    for _ in open_slots:
        dist = [float("inf")] * size
        dist[0] = 0
        previous = {}
        for _ in range(size - 1):
            changed = False
            for u in range(size):
                for k, (v, _, cap, cost) in enumerate(graph[u]):
                    if cap and dist[u] + cost < dist[v] - 1e-9:
                        dist[v] = dist[u] + cost
                        previous[v] = (u, k)
                        changed = True
            if not changed:
                break
        if sink not in previous or dist[sink] > 0:
            break
        v = sink
        while v:
            u, k = previous[v]
            e = graph[u][k]
            e[2] -= 1
            graph[v][e[1]][2] += 1
            v = u
    for p, pid in enumerate(pool):
        for v, _, cap, _ in graph[1 + p]:
            j = v - (1 + len(pool))
            if 0 <= j < len(open_slots) and cap == 0:
                selected[open_slots[j]] = pid
    lineup = [
        {
            "slot": label,
            "slot_index": i,
            "player": values[selected[i]] if i in selected else None,
            "locked": i in {int(x) for x in locked},
        }
        for i, label in enumerate(labels)
    ]
    return {
        "lineup": lineup,
        "total": round(sum(finite(values[pid].get(metric)) for pid in selected.values()), 2),
        "bench": [values[pid] for pid in ids if pid in values and pid not in selected.values()],
        "unfilled": len(labels) - len(selected),
    }


def compare_trade(roster, opponent, give, receive, values, slots, metric="value"):
    a = set(map(str, roster))
    b = set(map(str, opponent))
    g = set(map(str, give))
    r = set(map(str, receive))
    if a & b or not g or not r or not g <= a or not r <= b:
        raise ValueError("Trade players must belong to the indicated distinct rosters.")
    if any(pid not in values for pid in a | b):
        raise ValueError("A trade roster contains an unknown player.")
    if len(g) != len(r):
        raise ValueError(
            "This beta supports equal-size trades. Resolve extra pickups/drops before comparing an uneven trade."
        )
    before = optimize(a, values, slots, metric)
    after = optimize((a - g) | r, values, slots, metric)
    theirs = optimize(b, values, slots, metric)
    their_after = optimize((b - r) | g, values, slots, metric)
    return {
        "you": {"before": before, "after": after, "delta": round(after["total"] - before["total"], 2)},
        "opponent": {
            "before": theirs,
            "after": their_after,
            "delta": round(their_after["total"] - theirs["total"], 2),
        },
        "metric": metric,
        "note": "Lineup impact, not a prediction that the other manager will accept. No trade was submitted.",
    }


def waiver_moves(roster, available, values, slots, metric="value", protected=None):
    roster = list(dict.fromkeys(map(str, roster)))
    protected = set(map(str, protected or []))
    if not protected <= set(roster):
        raise ValueError("Protected players must be on your roster.")
    before = optimize(roster, values, slots, metric)
    moves = []
    for add in list(dict.fromkeys(map(str, available)))[:250]:
        if add in roster or add not in values:
            continue
        choices = []
        # Never assume there is a spare roster spot; evaluate explicit swaps.
        for drop in roster:
            if drop in protected:
                continue
            after = optimize([p for p in roster if p != drop] + [add], values, slots, metric)
            delta = round(after["total"] - before["total"], 2)
            if delta > 0 and after["unfilled"] <= before["unfilled"]:
                choices.append((delta, drop, after))
        if choices:
            delta, drop, after = max(choices, key=lambda x: x[0])
            moves.append({"add": values[add], "drop": values[drop], "delta": delta, "after": after})
    return {
        "before": before,
        "moves": sorted(moves, key=lambda x: x["delta"], reverse=True)[:10],
        "metric": metric,
        "note": "Each suggestion is an independent alternative, not a sequence of claims. Verify availability and kickoff locks before acting.",
    }
