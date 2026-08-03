import json
import unittest
from unittest.mock import patch

from agentic_consensus.variants.registry import (
    DEFAULT_VARIANT,
    VARIANTS,
    get_variant,
)
from agentic_consensus.variants.v2_posthoc_reviewer import nodes
from agentic_consensus.variants.v2_posthoc_reviewer.graph import build_graph
from agentic_consensus.variants.v2_posthoc_reviewer.state import PostHocReview
from agentic_consensus.transcript import render_json, render_markdown


class _Message:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }
        self.response_metadata = {}


class _Author:
    def __init__(self) -> None:
        self.answers = iter(["first proposal", "revised proposal"])
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return _Message(next(self.answers))


class _Reviewer:
    def __init__(self) -> None:
        self.reviews = iter(
            [
                PostHocReview(
                    criteria=["States the decision", "Explains the trade-off"],
                    approved=False,
                    score=5,
                    critique="The trade-off is missing.",
                    required_changes=["Explain the trade-off."],
                ),
                PostHocReview(
                    criteria=["States the decision", "Quantifies the trade-off"],
                    approved=True,
                    score=9,
                    critique="All criteria are satisfied.",
                    required_changes=[],
                ),
            ]
        )
        self.calls = 0

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        return {
            "parsed": next(self.reviews),
            "raw": _Message(),
            "parsing_error": None,
        }


class VariantRegistryTests(unittest.TestCase):
    def test_registry_exposes_named_variants(self) -> None:
        self.assertEqual(DEFAULT_VARIANT, "v1-moderated-criteria")
        self.assertEqual(
            set(VARIANTS),
            {"v1-moderated-criteria", "v2-posthoc-reviewer"},
        )
        self.assertEqual(get_variant(None).id, DEFAULT_VARIANT)
        self.assertEqual(
            set(get_variant(DEFAULT_VARIANT).build_graph().get_graph().nodes),
            {"__start__", "intake", "agent_a", "agent_b", "finalize", "__end__"},
        )

    def test_unknown_variant_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown variant"):
            get_variant("missing")


class PostHocGraphTests(unittest.TestCase):
    def test_rejects_revises_regenerates_criteria_and_approves(self) -> None:
        author = _Author()
        reviewer = _Reviewer()
        with (
            patch.object(nodes, "agent_a_llm", return_value=author),
            patch.object(nodes, "agent_b_llm", return_value=reviewer),
            patch.dict("os.environ", {"LANGSMITH_TRACING": "false"}),
        ):
            result = build_graph().invoke(
                {"problem": "Make a decision", "max_rounds": 3}
            )

        self.assertEqual(result["variant"], "v2-posthoc-reviewer")
        self.assertEqual(result["verdict"], "consensus")
        self.assertEqual(result["final_answer"], "revised proposal")
        self.assertEqual(result["proposals"], ["first proposal", "revised proposal"])
        self.assertEqual(len(result["criteria_history"]), 2)
        self.assertNotEqual(result["criteria_history"][0], result["criteria_history"][1])
        self.assertEqual(len(result["usage"]), 4)
        self.assertEqual(author.calls, 2)
        self.assertEqual(reviewer.calls, 2)
        transcript = json.loads(render_json(result))
        self.assertEqual(transcript["variant"], "v2-posthoc-reviewer")
        self.assertNotIn("moderator", transcript["models"])
        self.assertEqual(
            transcript["rounds_detail"][0]["review"]["criteria"],
            result["criteria_history"][0],
        )
        markdown = render_markdown(result)
        self.assertIn("Agent B's post-hoc criteria", markdown)
        self.assertNotIn("| Moderator |", markdown)


if __name__ == "__main__":
    unittest.main()
