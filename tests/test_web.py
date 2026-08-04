import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agentic_consensus import config, db, web
from agentic_consensus.variants.registry import VARIANTS
from agentic_consensus.web_templates import (
    EXPERIMENT_DETAIL_HTML,
    EXPERIMENTS_HTML,
    NEW_EXPERIMENT_HTML,
)


class ExperimentWebTests(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.env = patch.dict(os.environ, {"CONSENSUS_DB_PATH": self.path})
        self.env.start()
        db.init_db()

    def tearDown(self) -> None:
        self.env.stop()
        os.remove(self.path)

    @staticmethod
    def _events(stream) -> list[dict]:
        return [json.loads(item.removeprefix("data: ").strip()) for item in stream]

    def test_experiment_stream_continues_after_one_variant_fails(self) -> None:
        snapshot = {
            "max_rounds": 4,
            "stall_patience": 2,
            "roles": {
                "moderator": {"model": "test:moderator", "max_tokens": 8, "effort": "low"},
                "agent_a": {"model": "test:author", "max_tokens": 16, "effort": "low"},
                "agent_b": {"model": "test:reviewer", "max_tokens": 8, "effort": "low"},
            },
        }

        def fake_execute(problem, rounds, variant_id, emit, **kwargs):
            if variant_id == "v2-posthoc-reviewer":
                raise RuntimeError("provider secret detail")
            emit({"type": "node", "node": "agent_a", "duration_ms": 5})
            state = {
                "variant": variant_id,
                "variant_version": 1,
                "verdict": "consensus",
                "round": 1,
                "max_rounds": rounds,
                "usage": [
                    {
                        "node": "agent_a",
                        "total_tokens": 3,
                        "cost": 0.001,
                    }
                ],
                "timings": [{"node": "agent_a", "duration_ms": 5}],
                "final_answer": f"final from {variant_id}",
            }
            run_id = db.save_run(
                problem, state, experiment_id=kwargs["experiment_id"]
            )
            return state, run_id

        with patch.object(web.config, "settings", return_value=snapshot), patch.object(
            web, "_execute_variant", side_effect=fake_execute
        ):
            events = self._events(web._experiment_events("same problem", 2))

        experiment_id = next(
            event["experiment_id"]
            for event in events
            if event["type"] == "experiment_created"
        )
        detail = db.get_experiment(experiment_id)
        self.assertEqual(detail["status"], "partial")
        self.assertEqual(detail["evaluation_status"], "not_evaluated")
        self.assertEqual(detail["config"]["max_rounds"], 2)
        self.assertNotIn("api_key", json.dumps(detail["config"]).lower())
        completed = {
            event["variant"]
            for event in events
            if event["type"] == "variant_completed"
        }
        self.assertEqual(
            completed,
            {"v1-moderated-criteria", "v3-adversarial-reviewer"},
        )
        self.assertEqual(events[-1]["type"], "experiment_completed")
        self.assertEqual(events[-1]["status"], "partial")

    def test_retry_rejects_a_slot_that_has_not_failed(self) -> None:
        experiment_id = db.create_experiment(
            "problem", 2, config.settings(), list(VARIANTS)
        )
        response = web.retry_experiment_variant(
            experiment_id, "v1-moderated-criteria"
        )
        self.assertEqual(response.status_code, 409)

    def test_experiment_pages_and_read_apis_are_routable(self) -> None:
        experiment_id = db.create_experiment(
            "problem", 2, config.settings(), list(VARIANTS)
        )
        self.assertIn("New Experiment", web.new_experiment_page())
        self.assertIn("Experiments", web.experiments_page())
        self.assertIn("Experiment comparison", web.experiment_detail_page(experiment_id))
        listed = json.loads(web.api_list_experiments().body)
        self.assertEqual(listed[0]["id"], experiment_id)
        detail_response = web.api_get_experiment(experiment_id)
        self.assertEqual(detail_response.status_code, 200)
        detail = json.loads(detail_response.body)
        self.assertEqual(detail["evaluation_status"], "not_evaluated")
        self.assertEqual(web.api_get_experiment(999999).status_code, 404)

    def test_experiment_templates_expose_launch_list_and_comparison(self) -> None:
        self.assertIn("Run V1, V2 &amp; V3", NEW_EXPERIMENT_HTML)
        self.assertIn("One problem per row", EXPERIMENTS_HTML)
        self.assertIn("Evaluation:</b> Not evaluated", EXPERIMENT_DETAIL_HTML)
        self.assertIn("Open full replay", EXPERIMENT_DETAIL_HTML)
        self.assertIn("@media (max-width: 900px)", EXPERIMENT_DETAIL_HTML)


class ConfigSnapshotTests(unittest.TestCase):
    def test_saved_settings_override_is_scoped_and_restored(self) -> None:
        original = config.model_spec("agent_a")
        snapshot = config.settings()
        snapshot["roles"]["agent_a"]["model"] = "openai:saved-model"
        snapshot["max_rounds"] = 7
        with config.use_settings(snapshot):
            self.assertEqual(config.model_spec("agent_a"), "openai:saved-model")
            self.assertEqual(config.max_rounds(), 7)
        self.assertEqual(config.model_spec("agent_a"), original)


if __name__ == "__main__":
    unittest.main()
