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

    def test_application_settings_upsert_and_clear(self) -> None:
        db.replace_app_settings(
            {"OPENROUTER_API_KEY": "saved-secret", "LANGSMITH_TRACING": "true"},
            path=self.path,
        )
        self.assertEqual(
            db.get_app_settings(path=self.path),
            {"OPENROUTER_API_KEY": "saved-secret", "LANGSMITH_TRACING": "true"},
        )
        db.replace_app_settings(
            {"OPENROUTER_API_KEY": "", "LANGSMITH_TRACING": "false"},
            path=self.path,
        )
        self.assertEqual(
            db.get_app_settings(path=self.path), {"LANGSMITH_TRACING": "false"}
        )

    def test_save_and_get_round_trip(self) -> None:
        state = self._state()
        snapshot = {"roles": {"agent_a": {"model": "openrouter:vendor/model"}}}
        run_id = db.save_run(
            "the problem", state, config_snapshot=snapshot, path=self.path
        )

        row = db.get_run(run_id, path=self.path)
        self.assertIsNotNone(row)
        self.assertEqual(row["problem"], "the problem")
        self.assertEqual(row["verdict"], "consensus")
        self.assertEqual(row["rounds"], 1)
        self.assertEqual(row["max_rounds"], 4)
        self.assertEqual(row["last_score"], 9)
        self.assertEqual(row["total_cost"], 0.001)
        self.assertEqual(row["duration_ms"], 100)
        self.assertEqual(row["variant"], "v1-posthoc-reviewer")
        self.assertEqual(row["variant_version"], 1)
        self.assertEqual(row["total_tokens"], 3)
        self.assertEqual(row["state"]["proposals"], state["proposals"])
        self.assertEqual(row["state"]["reviews"], state["reviews"])
        self.assertEqual(row["state"]["usage"], state["usage"])
        self.assertEqual(row["state"]["timings"], state["timings"])
        self.assertEqual(row["config"], snapshot)

    def test_save_requires_verdict(self) -> None:
        with self.assertRaises(ValueError):
            db.save_run("p", {"no_verdict_here": True}, path=self.path)

    def test_provider_errors_are_sanitized_for_display(self) -> None:
        message = db.sanitize_error("Authorization: Bearer-secret sk-abcdefghijk")
        self.assertNotIn("Bearer-secret", message)
        self.assertNotIn("sk-abcdefghijk", message)
        self.assertIn("[redacted]", message)

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

    def test_v3_review_without_score_is_saved(self) -> None:
        state = self._state(
            variant="v3-adversarial-reviewer",
            reviews=[
                {
                    "missing_requirements": [],
                    "violated_acceptance_criteria": [],
                    "edge_cases": [],
                    "ambiguities": [],
                    "risks": [],
                    "summary": "No blocking defects.",
                    "approved": True,
                    "required_changes": [],
                }
            ],
        )
        run_id = db.save_run("p", state, path=self.path)
        row = db.get_run(run_id, path=self.path)

        self.assertEqual(row["variant"], "v3-adversarial-reviewer")
        self.assertIsNone(row["last_score"])

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
            self.assertEqual(row["variant"], "v1-posthoc-reviewer")
            self.assertEqual(row["variant_version"], 1)
            self.assertEqual(row["total_tokens"], 18)
            self.assertEqual(row["duration_ms"], 50)
            self.assertIsNone(row["experiment_id"])
        finally:
            os.remove(legacy_path)

    def test_creates_experiment_slots_and_links_completed_runs(self) -> None:
        variants = [
            "v1-posthoc-reviewer",
            "v2-moderated-reviewer",
            "v3-adversarial-reviewer",
        ]
        snapshot = {
            "max_rounds": 4,
            "stall_patience": 2,
            "roles": {"agent_a": {"model": "safe:model", "effort": "high"}},
        }
        experiment_id = db.create_experiment(
            "compare me", 4, snapshot, variants, path=self.path
        )

        detail = db.get_experiment(experiment_id, path=self.path)
        self.assertEqual(detail["status"], "running")
        self.assertEqual(detail["evaluation_status"], "not_evaluated")
        self.assertEqual(detail["config"], snapshot)
        self.assertEqual(
            {item["variant"] for item in detail["variants"]}, set(variants)
        )
        self.assertTrue(
            all(item["status"] == "pending" for item in detail["variants"])
        )

        for variant in variants:
            self.assertTrue(
                db.start_experiment_variant(experiment_id, variant, path=self.path)
            )
            state = self._state(variant=variant)
            db.save_run(
                "compare me", state, experiment_id=experiment_id, path=self.path
            )

        detail = db.get_experiment(experiment_id, path=self.path)
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["total_cost"], 0.003)
        self.assertTrue(all(item["id"] for item in detail["variants"]))
        self.assertTrue(
            all(item["final_answer"] == "final" for item in detail["variants"])
        )
        self.assertTrue(all(item["model_calls"] == 1 for item in detail["variants"]))

    def test_experiment_partial_failure_and_retry(self) -> None:
        variants = ["v1-posthoc-reviewer", "v2-moderated-reviewer"]
        experiment_id = db.create_experiment(
            "compare me", 4, {"roles": {}}, variants, path=self.path
        )
        first, second = variants
        db.start_experiment_variant(experiment_id, first, path=self.path)
        db.save_run(
            "compare me",
            self._state(variant=first),
            experiment_id=experiment_id,
            path=self.path,
        )
        db.start_experiment_variant(experiment_id, second, path=self.path)
        status = db.fail_experiment_variant(
            experiment_id, second, "  provider\n failed  ", path=self.path
        )

        self.assertEqual(status, "partial")
        failed = next(
            item
            for item in db.get_experiment(experiment_id, path=self.path)["variants"]
            if item["variant"] == second
        )
        self.assertEqual(failed["error_message"], "provider failed")
        self.assertFalse(
            db.start_experiment_variant(experiment_id, second, path=self.path)
        )
        self.assertTrue(
            db.start_experiment_variant(
                experiment_id, second, retry=True, path=self.path
            )
        )
        db.save_run(
            "compare me",
            self._state(variant=second),
            experiment_id=experiment_id,
            path=self.path,
        )
        self.assertEqual(
            db.get_experiment(experiment_id, path=self.path)["status"], "completed"
        )

    def test_all_failed_experiment_and_compact_list(self) -> None:
        variants = ["v1-posthoc-reviewer", "v2-moderated-reviewer"]
        experiment_id = db.create_experiment(
            "compare me", 4, {"roles": {}}, variants, path=self.path
        )
        for variant in variants:
            db.start_experiment_variant(experiment_id, variant, path=self.path)
            db.fail_experiment_variant(
                experiment_id, variant, "failed", path=self.path
            )

        rows = db.list_experiments(path=self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], experiment_id)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["evaluation_status"], "not_evaluated")
        self.assertIsNone(rows[0]["total_cost"])
        self.assertNotIn("config_json", rows[0])
        self.assertTrue(all(item["id"] is None for item in rows[0]["variants"]))


if __name__ == "__main__":
    unittest.main()
