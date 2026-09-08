from app import (
    aggregate_nflverse_team_rows,
    analysis_text,
    fantasy_points,
    manual_select_lineup,
    team_analysis_cards,
    yahoo_entities,
)


def test_interception_field():
    row = {
        "position": "QB",
        "passing_yards": "250",
        "passing_tds": "2",
        "passing_interceptions": "2",
        "games": "1",
    }
    assert abs(fantasy_points(row, "PPR") - 14.0) < 0.001


def synthetic_team_rows():
    teams = [f"T{i:02d}" for i in range(32)]
    rows = []
    for week in range(1, 18):
        for i, t in enumerate(teams):
            rows.append(
                {
                    "season_type": "REG",
                    "team": t,
                    "opponent_team": teams[(i + 1) % 32],
                    "passing_yards": str(180 + i * 2),
                    "rushing_yards": str(90 + i),
                    "passing_tds": str(1 + (i % 3)),
                    "rushing_tds": str(i % 2),
                    "special_teams_tds": "0",
                    "passing_epa": str(5 + i * 0.3),
                    "rushing_epa": str(1 + i * 0.1),
                    "passing_interceptions": str(i % 2),
                    "rushing_fumbles_lost": "0",
                    "receiving_fumbles_lost": "0",
                    "sack_fumbles_lost": "0",
                    "sacks_suffered": str(1 + (i % 4)),
                    "field_goals_made": "2",
                    "extra_points_made": "2",
                    "passing_2pt_conversions": "0",
                    "rushing_2pt_conversions": "0",
                    "receiving_2pt_conversions": "0",
                }
            )
    return rows


def test_team_model():
    off, defs = aggregate_nflverse_team_rows(synthetic_team_rows())
    assert len(off) == 32 and len(defs) == 32
    oc, dc = team_analysis_cards(off, defs, "test")
    assert len(oc) == 10 and len(dc) == 10
    assert len(dc[0]["stats"]) >= 6


def test_yahoo_parser():
    sample = {
        "fantasy_content": {
            "users": {
                "0": {
                    "user": [
                        {},
                        {
                            "games": {
                                "0": {
                                    "game": [
                                        {},
                                        {
                                            "teams": {
                                                "0": {
                                                    "team": [
                                                        {"team_key": "461.l.1000.t.2"},
                                                        {"name": "Test Team"},
                                                    ]
                                                }
                                            }
                                        },
                                    ]
                                }
                            }
                        },
                    ]
                }
            }
        }
    }
    teams = yahoo_entities(sample, "team")
    assert teams and teams[0]["team_key"] == "461.l.1000.t.2"
    assert teams[0]["name"] == "Test Team"


def test_manual_lineup():
    vals = {
        "q": {"id": "q", "position": "QB", "value": 80},
        "r1": {"id": "r1", "position": "RB", "value": 85},
        "r2": {"id": "r2", "position": "RB", "value": 75},
        "r3": {"id": "r3", "position": "RB", "value": 70},
        "w1": {"id": "w1", "position": "WR", "value": 88},
        "w2": {"id": "w2", "position": "WR", "value": 77},
        "w3": {"id": "w3", "position": "WR", "value": 72},
        "t": {"id": "t", "position": "TE", "value": 73},
    }
    starters, bench = manual_select_lineup(
        list(vals), vals, {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 0, "DST": 0}
    )
    assert len(starters) == 7
    assert any(x["id"] == "w3" for x in starters)


def test_analyst_text():
    kpis = [
        {"label": "Targets", "value": "130", "rank": 3, "pool": 60, "raw": 130},
        {"label": "Target Share", "value": "28.0%", "rank": 4, "pool": 60, "raw": 28},
    ]
    hist = [{"season": 2024, "ppg": 14.0}, {"season": 2025, "ppg": 17.0}]
    text = analysis_text("Example WR", "WR", 2025, 17.0, 18.2, kpis, hist)
    assert "Example WR" in text and "Targets" in text and "target share" in text.lower()


if __name__ == "__main__":
    test_interception_field()
    test_team_model()
    test_yahoo_parser()
    test_manual_lineup()
    test_analyst_text()
    print("SELF TEST PASS")
