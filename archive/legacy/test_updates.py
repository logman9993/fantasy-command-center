"""Offline regression tests using real Flask and synthetic provider responses."""

import unittest
from unittest.mock import patch

import app
from yahoo_adapter import import_team


def value(pid, pos="WR", score=80):
    return {
        "id": pid,
        "name": pid,
        "position": pos,
        "team": "BUF",
        "value": score,
        "prior_ppg": 10,
        "board_rank": None,
        "injury_status": "",
    }


class Updates(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.block = patch.object(
            app.requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network")
        )
        self.block.start()

    def tearDown(self):
        self.block.stop()

    def test_real_flask_and_validation(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for season in ("oops", "1999", "9999"):
            self.assertEqual(
                self.client.get(
                    "/api/player-analysis",
                    query_string={"name": "Player", "position": "WR", "season": season},
                ).status_code,
                400,
            )
            self.assertEqual(
                self.client.get("/api/team-power", query_string={"season": season}).status_code, 400
            )
        for payload in ([1], {"roster": "x"}, {"slots": []}):
            self.assertEqual(self.client.post("/api/manual-team-analysis", json=payload).status_code, 400)

    def test_manual_duplicates_and_empty_slots(self):
        values = {"a": value("a"), "b": value("b", score=60)}
        with (
            patch.object(app, "league_value_map", return_value=values),
            patch.object(app, "sleeper_trending", return_value=[]),
        ):
            full = app.manual_team_analysis(
                {
                    "roster": ["a", "b"],
                    "slots": {"WR": 2, "QB": 0, "RB": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0},
                }
            )
            partial = app.manual_team_analysis(
                {
                    "roster": ["a", "a"],
                    "slots": {"WR": 2, "QB": 0, "RB": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0},
                }
            )
            self.assertEqual(len(partial["team"]["starters"]), 1)
            self.assertEqual(partial["unfilled_slots"], 1)
            self.assertLess(partial["team"]["grade"]["score"], full["team"]["grade"]["score"])
            self.assertEqual(partial["grade_basis"], "model_estimate")

    def test_confirmed_empty_free_agent_pool_stays_empty(self):
        with (
            patch.object(app, "league_value_map", return_value={"a": value("a"), "b": value("b")}),
            patch.object(app, "sleeper_trending", return_value=[]),
        ):
            data = app.manual_team_analysis(
                {"roster": ["a"], "available": [], "availability_confirmed": True}
            )
            self.assertEqual(data["pickups"], [])
            self.assertEqual(data["swaps"], [])

    def test_swaps_recompute_grade_and_ignore_momentum_only_upgrade(self):
        vals = {
            "a": value("a", score=80),
            "b": value("b", score=50),
            "c": value("c", score=70),
            "d": value("d", score=49),
        }
        payload = {
            "roster": ["a", "b"],
            "available": ["c", "d"],
            "slots": {"QB": 0, "RB": 0, "WR": 1, "TE": 0, "FLEX": 0, "K": 0, "DST": 0},
        }
        with (
            patch.object(app, "league_value_map", return_value=vals),
            patch.object(app, "sleeper_trending", return_value=[{"player_id": "d", "count": 100000}]),
        ):
            data = app.manual_team_analysis(payload)
            self.assertTrue(data["swaps"])
            self.assertTrue(all(s["add"]["id"] != "d" for s in data["swaps"]))
            move = data["swaps"][0]
            after = app.manual_team_analysis(dict(payload, roster=["a", move["add"]["id"]]))
            self.assertAlmostEqual(
                move["delta"], after["team"]["grade"]["score"] - data["team"]["grade"]["score"]
            )

    def test_latest_rolls_forward_and_skips_empty_samples(self):
        app.latest_stats_season.cache_clear()

        def rows(year):
            return [{"passing_yards": "0"}] if year == app.SEASON else [{"passing_yards": "100"}]

        with (
            patch.object(app, "load_year_stats", side_effect=rows),
            patch.object(app.time, "time", return_value=1800),
        ):
            self.assertEqual(app.latest_stats_season(), app.PRIOR_SEASON)
        with (
            patch.object(app, "load_year_stats", return_value=[{"passing_yards": "100"}]),
            patch.object(app.time, "time", return_value=3600),
        ):
            self.assertEqual(app.latest_stats_season(), app.SEASON)
        app.latest_stats_season.cache_clear()

    def test_selected_stats_do_not_change_projection(self):
        def rows(year):
            return [
                {
                    "player_display_name": "Example",
                    "position": "WR",
                    "receiving_yards": str((year - 2020) * 100),
                    "receptions": "30",
                    "games": "10",
                }
            ]

        app.player_analysis_one.cache_clear()
        with (
            patch.object(app, "load_year_stats", side_effect=rows),
            patch.object(app, "latest_stats_season", return_value=2025),
        ):
            old = app.player_analysis_one("Example", "WR", "PPR", 2024)
            newer = app.player_analysis_one("Example", "WR", "PPR", 2025)
            self.assertEqual(old["actual_season"], 2024)
            self.assertNotEqual(old["actual_ppg"], newer["actual_ppg"])
            self.assertEqual(old["projected_ppg"], newer["projected_ppg"])

    def test_missing_selected_team_year_never_substitutes(self):
        with (
            patch.object(app, "load_team_weekly_stats", return_value=[]),
            patch.object(app, "team_power", side_effect=AssertionError("Wrong-year fallback")),
        ):
            data = self.client.get("/api/team-power?season=2024").json
            self.assertEqual(data["actual_season"], 2024)
            self.assertEqual(data["offenses"], [])

    def test_nested_yahoo_metadata(self):
        raw = {
            "teams": {
                "0": {"team": [[{"team_key": "461.l.1.t.1"}, {"name": "My Team"}], {"roster": {}}]},
                "count": 1,
            }
        }
        teams = app.yahoo_entities(raw, "team")
        self.assertEqual(teams[0]["team_key"], "461.l.1.t.1")

    def yahoo_api(self, path, token):
        if path.startswith("/users"):
            return {"team": [[{"team_key": "461.l.1.t.1"}, {"name": "My Team"}]]}
        if path.endswith("/settings"):
            return {
                "league": [
                    [{"league_key": "461.l.1"}, {"season": "2025"}, {"num_teams": 12}],
                    {
                        "settings": [
                            {
                                "roster_positions": [{"roster_position": {"position": "WR", "count": 1}}],
                                "stat_modifiers": {"stats": [{"stat": {"stat_id": "11", "value": 1}}]},
                            }
                        ]
                    },
                ]
            }
        if "/roster/" in path:
            return {
                "player": [[{"player_key": "461.p.1"}, {"name": {"full": "a"}}, {"display_position": "WR"}]]
            }
        if ";status=FA;" in path:
            return {"players": {"count": 0}}
        raise AssertionError(path)

    def test_yahoo_import_matches_roster_and_preserves_empty_pool(self):
        vals = {"a": value("a"), "b": value("b")}
        with (
            patch.object(app, "league_value_map", return_value=vals),
            patch.object(app, "sleeper_trending", return_value=[]),
        ):
            result = import_team(
                "461.l.1.t.1",
                {},
                self.yahoo_api,
                app.yahoo_entities,
                app.yahoo_merge_dict_list,
                app.league_value_map,
                app.manual_team_analysis,
            )
        self.assertEqual(result["provider"], "Yahoo")
        self.assertEqual(result["league"]["scoring"], "PPR")
        self.assertEqual(result["pickups"], [])
        self.assertEqual(result["team"]["starters"][0]["name"], "a")

    def test_yahoo_rejects_unowned_and_unmatched_rosters(self):
        with self.assertRaises(PermissionError):
            import_team(
                "461.l.1.t.2",
                {},
                self.yahoo_api,
                app.yahoo_entities,
                app.yahoo_merge_dict_list,
                lambda _: {},
                lambda _: {},
            )
        with self.assertRaisesRegex(ValueError, "incomplete import"):
            import_team(
                "461.l.1.t.1",
                {},
                self.yahoo_api,
                app.yahoo_entities,
                app.yahoo_merge_dict_list,
                lambda _: {},
                lambda _: {},
            )

    def test_yahoo_requires_csrf_state(self):
        with (
            patch.object(app, "yahoo_configured", return_value=True),
            patch.object(app, "yahoo_exchange_code", side_effect=AssertionError("Exchange without state")),
        ):
            response = self.client.get("/auth/yahoo/callback?code=secret")
            self.assertIn("state+check+failed", response.location)


if __name__ == "__main__":
    unittest.main()
