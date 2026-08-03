import os
import json
import sqlite3
import tempfile
import unittest

from agentic_consensus import db


class HistoryDbTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)  # let init_db create it fresh
        db.init_db(self.path)

    def tearDown(self) -> None:
        os.remove(self.path)

    def _state(self, **overrides) -> dict:
        state = {
            "restated_problem": "restated",
            "round": 1,
            "max_rounds": 4,
            "proposals": ["proposal 1"],
            "reviews": [{"approved": True, "score": 9, "critique": "ok", "required_changes": []}],
            "usage": [{"node": "intake", "role": "moderator", "model": "m", "input_tokens": 1,
                       "output_tokens": 2, "total_tokens": 3, "cost": 0.001,
                       "cost_source": "provider_reported"}],
            "timings": [{"node": "intake", "duration_ms": 100}],
            "verdict": "consensus",
            "final_answer": "final",
        }
        state.update(overrides)
        return state

    def test_init_db_is_idempotent(self) -> None:
        db.init_db(self.path)  # second call must not raise or wipe anything
        run_id = db.save_run("p", self._state(), path=self.path)
        db.init_db(self.path)
        self.assertEqual(db.get_run(run_id, path=self.path)["id"], run_id)

    def test_save_and_get_round_trip(self) -> None:
        state = self._state()
        run_id = db.save_run("the problem", state, path=self.path)

        row = db.get_run(run_id, path=self.path)
        self.assertIsNotNone(row)
        self.assertEqual(row["problem"], "the problem")
        self.assertEqual(row["verdict"], "consensus")
        self.assertEqual(row["rounds"], 1)
        self.assertEqual(row["max_rounds"], 4)
        self.assertEqual(row["last_score"], 9)
        self.assertEqual(row["total_cost"], 0.001)
        self.assertEqual(row["duration_ms"], 100)
        self.assertEqual(row["variant"], "v1-moderated-criteria")
        self.assertEqual(row["variant_version"], 1)
        self.assertEqual(row["total_tokens"], 3)
        self.assertEqual(row["state"]["proposals"], state["proposals"])
        self.assertEqual(row["state"]["reviews"], state["reviews"])
        self.assertEqual(row["state"]["usage"], state["usage"])
        self.assertEqual(row["state"]["timings"], state["timings"])

    def test_save_requires_verdict(self) -> None:
        with self.assertRaises(ValueError):
            db.save_run("p", {"no_verdict_here": True}, path=self.path)

    def test_list_runs_excludes_state_and_orders_by_recency(self) -> None:
        first = db.save_run("first", self._state(), path=self.path)
        second = db.save_run("second", self._state(), path=self.path)

        rows = db.list_runs(path=self.path)
        self.assertEqual([r["id"] for r in rows], [second, first])
        self.assertNotIn("state_json", rows[0])
        self.assertNotIn("state", rows[0])

    def test_get_run_unknown_id_returns_none(self) -> None:
        self.assertIsNone(db.get_run(999999, path=self.path))

    def test_last_score_is_null_without_reviews(self) -> None:
        run_id = db.save_run("p", self._state(reviews=[]), path=self.path)
        self.assertIsNone(db.get_run(run_id, path=self.path)["last_score"])

    def test_total_cost_is_null_when_provider_did_not_report_it(self) -> None:
        state = self._state(
            usage=[
                {"node": "intake", "cost": 0.001},
                {"node": "agent_a", "cost": None},
            ]
        )
        run_id = db.save_run("p", state, path=self.path)
        self.assertIsNone(db.get_run(run_id, path=self.path)["total_cost"])

    def test_migrates_legacy_row_to_v1_and_backfills_summaries(self) -> None:
        fd, legacy_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        state = {
            "usage": [{"total_tokens": 7}, {"total_tokens": 11}],
            "timings": [{"duration_ms": 20}, {"duration_ms": 30}],
        }
        try:
            with sqlite3.connect(legacy_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        problem TEXT NOT NULL,
                        restated_problem TEXT,
                        verdict TEXT NOT NULL,
                        rounds INTEGER,
                        max_rounds INTEGER,
                        last_score INTEGER,
                        state_json TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO runs (created_at, problem, verdict, state_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "2026-01-01T00:00:00+00:00",
                        "legacy",
                        "consensus",
                        json.dumps(state),
                    ),
                )

            db.init_db(legacy_path)
            row = db.list_runs(path=legacy_path)[0]
            self.assertEqual(row["variant"], "v1-moderated-criteria")
            self.assertEqual(row["variant_version"], 1)
            self.assertEqual(row["total_tokens"], 18)
            self.assertEqual(row["duration_ms"], 50)
        finally:
            os.remove(legacy_path)


if __name__ == "__main__":
    unittest.main()
