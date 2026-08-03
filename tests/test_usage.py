import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agentic_consensus.nodes import _usage


class UsageExtractionTests(unittest.TestCase):
    def test_extracts_openrouter_cost_and_detailed_tokens(self) -> None:
        message = SimpleNamespace(
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 35,
                "total_tokens": 155,
                "input_token_details": {"cache_read": 80, "cache_creation": 10},
                "output_token_details": {"reasoning": 20},
            },
            response_metadata={
                "id": "gen-test",
                "token_usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 35,
                    "total_tokens": 155,
                    "cost": 0.00125,
                    "cost_details": {"upstream_inference_cost": 0.001},
                    "prompt_tokens_details": {
                        "cached_tokens": 80,
                        "cache_write_tokens": 10,
                    },
                    "completion_tokens_details": {"reasoning_tokens": 20},
                },
            },
        )

        with patch.dict(
            os.environ,
            {"AGENT_B_MODEL": "openrouter:openai/test-model"},
            clear=False,
        ):
            usage = _usage("agent_b", "agent_b", message)

        self.assertEqual(usage.provider, "openrouter")
        self.assertEqual(usage.generation_id, "gen-test")
        self.assertEqual(usage.reasoning_tokens, 20)
        self.assertEqual(usage.cached_input_tokens, 80)
        self.assertEqual(usage.cache_write_tokens, 10)
        self.assertEqual(usage.cost, 0.00125)
        self.assertEqual(usage.upstream_inference_cost, 0.001)
        self.assertEqual(usage.cost_source, "provider_reported")

    def test_marks_cost_unavailable_without_provider_report(self) -> None:
        message = SimpleNamespace(
            usage_metadata={
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
            },
            response_metadata={},
        )

        with patch.dict(
            os.environ,
            {"MODERATOR_MODEL": "anthropic:claude-test"},
            clear=False,
        ):
            usage = _usage("intake", "moderator", message)

        self.assertEqual(usage.provider, "anthropic")
        self.assertIsNone(usage.cost)
        self.assertIsNone(usage.upstream_inference_cost)
        self.assertEqual(usage.cost_source, "unavailable")

    def test_falls_back_to_raw_openrouter_token_details(self) -> None:
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            response_metadata={
                "token_usage": {
                    "prompt_tokens_details": {
                        "cached_tokens": 7,
                        "cache_write_tokens": 2,
                    },
                    "completion_tokens_details": {"reasoning_tokens": 4},
                }
            },
        )

        with patch.dict(
            os.environ,
            {"AGENT_A_MODEL": "openrouter:test/model"},
            clear=False,
        ):
            usage = _usage("agent_a", "agent_a", message)

        self.assertEqual(usage.reasoning_tokens, 4)
        self.assertEqual(usage.cached_input_tokens, 7)
        self.assertEqual(usage.cache_write_tokens, 2)


if __name__ == "__main__":
    unittest.main()
