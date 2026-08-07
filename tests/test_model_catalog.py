import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agentic_consensus import config, db, model_catalog


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ModelCatalogTests(unittest.TestCase):
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
    def _model(index: int, **overrides):
        item = {
            "id": f"vendor/model-{index}",
            "name": f"Model {index}",
            "architecture": {"output_modalities": ["text"]},
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "context_length": 1000,
            "supported_parameters": ["structured_outputs"],
            "expiration_date": None,
        }
        item.update(overrides)
        return item

    def test_empty_catalog_contains_configured_defaults(self) -> None:
        payload = model_catalog.available_models()
        self.assertEqual(payload["saved_count"], 0)
        self.assertIsNone(payload["refreshed_at"])
        self.assertTrue(set(payload["defaults"].values()).issubset(
            {item["id"] for item in payload["models"]}
        ))
        self.assertTrue(all(item["configured_default"] for item in payload["models"]))

    def test_refresh_keeps_first_thirty_usable_text_models(self) -> None:
        raw = [
            self._model(100, architecture={"output_modalities": ["image"]}),
            self._model(101, expiration_date="2020-01-01"),
            *[self._model(index) for index in range(35)],
        ]
        response = _Response(json.dumps({"data": raw}).encode())
        with patch("urllib.request.urlopen", return_value=response):
            payload = model_catalog.refresh()
        self.assertEqual(payload["saved_count"], 30)
        self.assertEqual(payload["models"][0]["id"], "vendor/model-0")
        saved = db.get_model_catalog()
        self.assertEqual(saved["models"][-1]["popularity_rank"], 30)

    def test_refresh_honors_requested_count_and_validates_bounds(self) -> None:
        raw = [self._model(index) for index in range(10)]
        response = _Response(json.dumps({"data": raw}).encode())
        with patch("urllib.request.urlopen", return_value=response):
            payload = model_catalog.refresh(limit=4)
        self.assertEqual(payload["saved_count"], 4)
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            model_catalog.fetch_popular_models(limit=101)

    def test_failed_refresh_preserves_saved_catalog(self) -> None:
        db.replace_model_catalog([{
            "id": "vendor/saved", "name": "Saved", "provider": "vendor",
            "popularity_rank": 1, "supported_parameters": [],
        }], path=self.path)
        with patch.object(model_catalog, "fetch_popular_models", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                model_catalog.refresh(path=self.path)
        self.assertEqual(db.get_model_catalog(path=self.path)["models"][0]["id"], "vendor/saved")

    def test_selected_models_override_only_models_in_snapshot(self) -> None:
        db.replace_model_catalog([{
            "id": "vendor/saved", "name": "Saved", "provider": "vendor",
            "popularity_rank": 1, "supported_parameters": [],
        }])
        before = config.settings()
        snapshot = model_catalog.settings_with_models({"agent_a": "vendor/saved"})
        self.assertEqual(snapshot["roles"]["agent_a"]["model"], "openrouter:vendor/saved")
        self.assertEqual(snapshot["roles"]["agent_a"]["effort"], before["roles"]["agent_a"]["effort"])
        with self.assertRaisesRegex(ValueError, "not in the saved"):
            model_catalog.settings_with_models({"agent_a": "vendor/arbitrary"})

    def test_evaluator_config_freezes_once(self) -> None:
        experiment_id = db.create_experiment(
            "p", 2, config.settings(), ["v1"],
            [{"id": "C1", "text": "Clear"}], path=self.path,
        )
        db.start_experiment_variant(experiment_id, "v1", path=self.path)
        db.save_run("p", {
            "variant": "v1", "variant_version": 1, "verdict": "consensus",
            "round": 1, "max_rounds": 2, "usage": [], "timings": [],
            "final_answer": "answer",
        }, experiment_id=experiment_id, path=self.path)
        first = {"model": "openrouter:vendor/one", "effort": "low", "max_tokens": 1000}
        second = {"model": "openrouter:vendor/two", "effort": "high", "max_tokens": 2000}
        self.assertEqual(db.freeze_evaluation_config(experiment_id, first, path=self.path), first)
        self.assertEqual(db.freeze_evaluation_config(experiment_id, second, path=self.path), first)
        self.assertEqual(db.get_experiment(experiment_id, path=self.path)["evaluation_config"], first)


if __name__ == "__main__":
    unittest.main()
