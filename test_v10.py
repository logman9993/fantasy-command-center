"""V10 regressions: roster capture, ranking depth and honest start guidance."""

import unittest
from unittest.mock import patch

import app
from v10_api import attach_photos, match_roster_text


def player(pid, name, pos="QB", team="BUF"):
    return {
        "id": pid,
        "name": name,
        "position": pos,
        "team": team,
        "value": 75,
        "injury_status": "",
        "prior_ppg": 15,
    }


class CaptureTests(unittest.TestCase):
    def test_full_names_dedupe_but_initials_need_review(self):
        players = [
            player("1", "Josh Allen"),
            player("2", "Jordan Allen"),
            player("3", "Lamar Jackson", team="BAL"),
        ]
        result = match_roster_text("QB Josh Allen BUF\nJosh Allen 22.3\nJ. Allen\nLamar Jackson BAL", players)
        self.assertEqual({p["id"] for p in result["matches"]}, {"1", "3"})
        self.assertEqual(len(result["review"]), 1)
        self.assertEqual(len(result["review"][0]["choices"]), 2)

    def test_noise_does_not_invent_players(self):
        result = match_roster_text(
            "Roster 9/16\nWeek 1\nProjected Points 122\nSubmit lineup", [player("1", "Josh Allen")]
        )
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["review"], [])

    def test_photos_use_identity_not_search_rank(self):
        result = attach_photos(
            {"QB": [{"name": "Josh Allen"}]},
            {"4984": {"full_name": "Josh Allen", "position": "QB"}},
            app.norm_name,
            app.player_name,
        )
        self.assertTrue(result["QB"][0]["photo"].endswith("/4984.jpg"))

    def test_kicker_schema_aliases(self):
        self.assertEqual(app.fantasy_points({"position": "K", "fg_made": 3, "pat_made": 2}, "PPR"), 11)
        self.assertEqual(
            app.fantasy_points({"position": "K", "fg_made": 3, "pat_made": 2}, {"fgm": 3, "xpm": 1}), 11
        )

    def test_dst_expansion_never_duplicates_teams(self):
        app.rankings.cache_clear()
        with (
            patch.object(app, "FANTASYPROS_KEY", ""),
            patch.object(app, "sleeper_players", return_value={}),
            patch.object(app, "load_year_stats", return_value=[]),
            patch.object(
                app,
                "fallback",
                return_value={"rankings": {"DST": [{"name": "Buffalo Bills", "team": "BUF"}]}},
            ),
        ):
            rows = app.rankings("PPR", 100)["DST"]
            self.assertEqual(len(rows), 32)
            self.assertEqual(len({p["team"] for p in rows}), 32)
        app.rankings.cache_clear()

    def test_top_100_without_changing_default_25(self):
        app.rankings.cache_clear()
        players = {
            str(i): {
                "full_name": f"Receiver {i}",
                "position": "WR",
                "team": "BUF",
                "active": True,
                "search_rank": i + 1,
            }
            for i in range(105)
        }
        with (
            patch.object(app, "FANTASYPROS_KEY", ""),
            patch.object(app, "sleeper_players", return_value=players),
            patch.object(app, "load_year_stats", return_value=[]),
            patch.object(app, "fallback", return_value={"rankings": {}}),
        ):
            self.assertEqual(len(app.rankings("PPR")["WR"]), 25)
            self.assertEqual(len(app.rankings("PPR", 100)["WR"]), 100)
        app.rankings.cache_clear()


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.players = [player("1", "Josh Allen"), player("2", "Lamar Jackson", team="BAL")]
        self.rows = [
            {
                "player_display_name": name,
                "position": "QB",
                "season_type": "REG",
                "week": w,
                "passing_yards": yards,
                "passing_tds": 2,
                "carries": 5,
            }
            for name, yards in [("Josh Allen", 300), ("Lamar Jackson", 200)]
            for w in range(1, 5)
        ]
        self.schedules = [
            {
                "season": str(app.SEASON),
                "week": "1",
                "game_type": "REG",
                "home_team": "BUF",
                "away_team": "BAL",
                "gameday": "2099-09-09",
                "gametime": "13:00",
            }
        ]
        self.patches = [
            patch.object(app, "manual_player_catalog", side_effect=lambda scoring: self.players),
            patch.object(app, "latest_stats_season", return_value=2025),
            patch.object(app, "load_player_weekly_stats", side_effect=lambda season: self.rows),
            patch.object(app, "cached_csv", side_effect=lambda *args: (self.schedules, "fixture")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def compare(self, season=2025):
        return self.client.get(f"/api/v10/compare?a=1&b=2&scoring=PPR&week=1&season={season}")

    def test_start_lean_explained_and_historical_year_independent(self):
        d = self.compare().json
        self.assertEqual(d["recommendation"]["player_id"], "1")
        self.assertEqual(d["recommendation"]["label"], "Provisional start lean")
        self.assertEqual(self.compare(2024).json["recommendation"]["player_id"], "1")
        self.assertIn("Not expert consensus", d["recommendation"]["basis"])

    def test_unavailable_player_is_not_recommended(self):
        self.players[0]["injury_status"] = "Out"
        self.assertEqual(self.compare().json["recommendation"]["player_id"], "2")

    def test_missing_schedule_or_started_games_abstain(self):
        self.schedules.clear()
        self.assertIsNone(self.compare().json["recommendation"]["player_id"])
        self.schedules.append(
            {
                "season": str(app.SEASON),
                "week": "1",
                "home_team": "BUF",
                "away_team": "BAL",
                "gameday": "2000-09-01",
                "gametime": "13:00",
            }
        )
        self.assertIsNone(self.compare().json["recommendation"]["player_id"])

    def test_invalid_request_and_missing_games(self):
        self.assertEqual(self.client.get("/api/v10/compare?a=1&b=1").status_code, 400)
        self.assertEqual(self.client.post("/api/v10/roster-match", json=["bad"]).status_code, 400)
        self.rows.clear()
        self.assertIsNone(self.compare().json["recommendation"]["player_id"])
        self.assertIsNone(self.compare().json["players"][0]["ppg"])

    def test_mixed_positions_do_not_get_availability_pick(self):
        self.players[1]["position"] = "K"
        self.players[1]["injury_status"] = "Out"
        self.assertIsNone(self.compare().json["recommendation"]["player_id"])

    def test_schedule_aliases_and_one_locked_player(self):
        self.players[0]["team"] = "LAR"
        self.schedules[0]["home_team"] = "LA"
        self.assertTrue(self.compare().json["players"][0]["matchup"]["scheduled"])
        self.schedules[0]["away_team"] = "IND"
        self.schedules[0]["gameday"] = "2000-09-01"
        self.schedules.append(
            {
                "season": str(app.SEASON),
                "week": "1",
                "home_team": "BAL",
                "away_team": "BUF",
                "gameday": "2099-09-01",
                "gametime": "13:00",
            }
        )
        self.assertIsNone(self.compare().json["recommendation"]["player_id"])

    def test_roster_specific_priorities(self):
        values = {p["id"]: p for p in self.players}
        with (
            patch.object(app, "league_value_map", return_value=values),
            patch.object(app, "sleeper_trending", return_value=[]),
        ):
            d = self.client.post(
                "/api/v10/team-report",
                json={
                    "roster": ["1"],
                    "slots": {"QB": 2, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0},
                },
            )
            self.assertEqual(d.status_code, 200)
            self.assertIn("Fill your empty", d.json["priorities"][0]["title"])
            self.assertIn("Josh Allen", str(d.json["priorities"]))


if __name__ == "__main__":
    unittest.main()
