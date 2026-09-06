"""Regression tests for scoring, overlapping slots, decisions and data isolation."""

import itertools
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from v9_engine import ELIGIBLE, compare_trade, optimize, score_stats, scoring_rules, slots_from, waiver_moves


def player(pid, pos, value):
    return {"id": pid, "name": pid, "position": pos, "team": "BUF", "value": value, "prior_ppg": 10}


class EngineTests(unittest.TestCase):
    def test_six_point_passing_and_te_premium(self):
        rules, unsupported = scoring_rules(custom={"pass_td": 6, "rec": 1, "bonus_rec_te": 0.5})
        self.assertFalse(unsupported)
        self.assertEqual(score_stats({"position": "QB", "passing_tds": 2}, rules), 12)
        self.assertEqual(score_stats({"position": "TE", "receptions": 4}, rules), 6)
        self.assertEqual(score_stats({"position": "WR", "receptions": 4}, rules), 4)
        self.assertEqual(scoring_rules(custom={"unsupported": 1})[1], ["unsupported"])
        with self.assertRaises(ValueError):
            scoring_rules(custom={"rec": float("nan")})

    def test_slot_normalization_no_invented_starters(self):
        self.assertEqual(
            slots_from(["QB", "SUPER_FLEX", "FLEX", "DEF", "BN", "IR"]),
            {"QB": 1, "SUPER_FLEX": 1, "FLEX": 1, "DST": 1},
        )
        self.assertEqual(
            app.espn_slot_counts(
                {"settings": {"rosterSettings": {"lineupSlotCounts": {"0": 1, "7": 1, "23": 2, "20": 6}}}}
            ),
            {"QB": 1, "SUPER_FLEX": 1, "FLEX": 2},
        )
        with self.assertRaises(ValueError):
            slots_from({"QB": 1.5})
        with self.assertRaises(ValueError):
            app.espn_slot_counts({})

    def test_matching_agrees_with_exhaustive_search(self):
        rng = random.Random(83)
        slots = {"FLEX": 1, "SUPER_FLEX": 1, "RB": 1, "WR": 1}
        labels = list(slots)
        for _ in range(30):
            values = {
                str(i): player(str(i), rng.choice(["QB", "WR", "RB", "TE"]), rng.randint(1, 100))
                for i in range(6)
            }
            best = 0
            for candidate in itertools.product([None, *values], repeat=4):
                used = [p for p in candidate if p is not None]
                if len(used) != len(set(used)):
                    continue
                if any(
                    pid is not None and values[pid]["position"] not in ELIGIBLE[label]
                    for pid, label in zip(candidate, labels)
                ):
                    continue
                best = max(best, sum(values[pid]["value"] for pid in used))
            result = optimize(values, values, slots)
            self.assertEqual(result["total"], best)

    def test_protection_and_trade_ownership(self):
        values = {"a": player("a", "WR", 30), "b": player("b", "WR", 90), "c": player("c", "QB", 80)}
        self.assertEqual(waiver_moves(["a"], ["b"], values, {"WR": 1}, protected=["a"])["moves"], [])
        move = waiver_moves(["a"], ["b"], values, {"WR": 1})["moves"][0]
        self.assertEqual(move["delta"], 60)
        result = compare_trade(["a"], ["b"], ["a"], ["b"], values, {"WR": 1})
        self.assertEqual(result["you"]["delta"], 60)
        self.assertEqual(result["opponent"]["delta"], -60)
        with self.assertRaises(ValueError):
            compare_trade(["a"], ["b"], ["c"], ["b"], values, {"WR": 1})

    def test_missing_games_and_negation(self):
        self.assertEqual(app.games({}), 0)
        positive = app.news_signal([{"title": "Player expected to start", "summary": ""}])
        negative = app.news_signal([{"title": "Player not expected to start", "summary": ""}])
        self.assertNotEqual(positive, negative)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = app.app.config["WORKSPACE_DB"]
        app.app.config["WORKSPACE_DB"] = str(Path(self.temp.name) / "test.sqlite3")
        self.client = app.app.test_client()
        self.network = patch.object(
            app.requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network")
        )
        self.network.start()

    def tearDown(self):
        self.network.stop()
        app.app.config["WORKSPACE_DB"] = self.previous_db
        self.temp.cleanup()

    def test_workspace_isolation_feedback_and_delete(self):
        a = {"Authorization": "Bearer " + "a" * 64}
        b = {"Authorization": "Bearer " + "b" * 64}
        self.assertEqual(self.client.put("/api/v9/workspace", json={}).status_code, 400)
        state = {"team": {"roster": ["a"]}, "watch": [], "version": 9}
        self.assertEqual(self.client.put("/api/v9/workspace", json=state, headers=a).status_code, 200)
        self.assertEqual(self.client.get("/api/v9/workspace", headers=a).json["state"], state)
        self.assertIsNone(self.client.get("/api/v9/workspace", headers=b).json["state"])
        feedback = self.client.post(
            "/api/v9/feedback", headers=a, json={"message": "Test feedback", "snapshot": {"roster": ["a"]}}
        )
        self.assertEqual(feedback.status_code, 200)
        self.assertEqual(
            self.client.put("/api/v9/workspace", headers=a, json={"espn_cookie": "secret"}).status_code, 400
        )
        self.client.delete("/api/v9/workspace", headers=a)
        self.assertIsNone(self.client.get("/api/v9/workspace", headers=a).json["state"])

    def test_decision_validation_and_before_after(self):
        values = {"a": player("a", "WR", 30), "b": player("b", "WR", 90)}
        with patch.object(app, "league_value_map", return_value=values):
            result = self.client.post(
                "/api/v9/decisions", json={"roster": ["a"], "available": ["b"], "slots": {"WR": 1}}
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["waivers"]["moves"][0]["delta"], 60)
            for body in (
                [1],
                {"roster": "oops"},
                {"roster": ["missing"]},
                {"roster": ["a"], "available": ["a"]},
                {"roster": ["a"], "slots": {"QB": float("nan")}},
            ):
                self.assertEqual(self.client.post("/api/v9/decisions", json=body).status_code, 400)

    def test_profile_preserves_missing_weeks(self):
        rows = [
            {
                "player_display_name": "Example",
                "position": "WR",
                "season_type": "REG",
                "week": 2,
                "receptions": 3,
                "receiving_yards": 40,
            },
            {
                "player_display_name": "Example",
                "position": "WR",
                "season_type": "POST",
                "week": 19,
                "receptions": 5,
            },
        ]
        with patch.object(app, "load_player_weekly_stats", return_value=rows):
            result = self.client.get("/api/v9/profile?name=Example&position=WR&season=2024")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(result.json["weeks"]), 1)
            self.assertEqual(result.json["weeks"][0]["points"], 7)
            self.assertEqual(result.json["weeks"][0]["week"], 2)


if __name__ == "__main__":
    unittest.main()
