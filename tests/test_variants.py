import json
import unittest
from unittest.mock import patch

from agentic_consensus.variants.registry import (
    DEFAULT_VARIANT,
    VARIANTS,
    get_variant,
)
from agentic_consensus.variants.v1_posthoc_reviewer import nodes as v1_nodes
from agentic_consensus.variants.v1_posthoc_reviewer.graph import build_graph
from agentic_consensus.variants.v1_posthoc_reviewer.state import PostHocReview
from agentic_consensus.variants.v2_moderated_reviewer.state import Criteria
from agentic_consensus.variants.v3_adversarial_reviewer import nodes as v3_nodes
from agentic_consensus.variants.v3_adversarial_reviewer.graph import (
    build_graph as build_v3_graph,
)
from agentic_consensus.variants.v3_adversarial_reviewer.state import (
    AdversarialReview,
    Defect,
)
from agentic_consensus.transcript import render_html, render_json, render_markdown


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
        self.messages = []

    def invoke(self, messages):
        self.calls += 1
        self.messages.append(messages)
        return _Message(next(self.answers))


class _Reviewer:
    def __init__(self) -> None:
        self.reviews = iter(
            [
                PostHocReview(
                    criteria=[
                        "States the decision",
                        "Explains the trade-off",
                        "Avoids unsupported claims",
                    ],
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
        self.assertEqual(DEFAULT_VARIANT, "v1-posthoc-reviewer")
        self.assertEqual(
            list(VARIANTS),
            [
                "v1-posthoc-reviewer",
                "v2-moderated-reviewer",
                "v3-adversarial-reviewer",
            ],
        )
        self.assertEqual(
            VARIANTS["v1-posthoc-reviewer"].label, "V1 — Post-hoc reviewer"
        )
        self.assertEqual(
            VARIANTS["v2-moderated-reviewer"].label, "V2 — Moderated reviewer"
        )
        self.assertEqual(get_variant(None).id, DEFAULT_VARIANT)
        self.assertEqual(
            set(get_variant(DEFAULT_VARIANT).build_graph().get_graph().nodes),
            {"__start__", "agent_a", "agent_b", "__end__"},
        )
        self.assertEqual(
            set(get_variant("v3-adversarial-reviewer").build_graph().get_graph().nodes),
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
            patch.object(v1_nodes, "agent_a_llm", return_value=author),
            patch.object(v1_nodes, "agent_b_llm", return_value=reviewer),
            patch.dict("os.environ", {"LANGSMITH_TRACING": "false"}),
        ):
            result = build_graph().invoke(
                {"problem": "Make a decision", "max_rounds": 3}
            )

        self.assertEqual(result["variant"], "v1-posthoc-reviewer")
        self.assertEqual(result["verdict"], "consensus")
        self.assertEqual(result["final_answer"], "revised proposal")
        self.assertEqual(result["proposals"], ["first proposal", "revised proposal"])
        self.assertEqual(len(result["criteria_history"]), 2)
        self.assertNotEqual(result["criteria_history"][0], result["criteria_history"][1])
        self.assertEqual(len(result["usage"]), 4)
        self.assertEqual(author.calls, 2)
        self.assertEqual(reviewer.calls, 2)
        transcript = json.loads(render_json(result))
        self.assertEqual(transcript["variant"], "v1-posthoc-reviewer")
        self.assertNotIn("moderator", transcript["models"])
        self.assertEqual(
            transcript["rounds_detail"][0]["review"]["criteria"],
            result["criteria_history"][0],
        )
        markdown = render_markdown(result)
        self.assertIn("Agent B's post-hoc criteria", markdown)
        self.assertNotIn("| Moderator |", markdown)


class _AdversarialReviewer:
    def __init__(self) -> None:
        self.reviews = iter(
            [
                AdversarialReview(
                    missing_requirements=[
                        Defect(
                            description="The required trade-off is absent.",
                            severity="blocking",
                            evidence=(
                                "The problem asks for a trade-off; the proposal only "
                                "states a decision."
                            ),
                            required_correction="Explain the trade-off and its consequences.",
                        )
                    ],
                    risks=[
                        Defect(
                            description="The recommendation may age poorly.",
                            severity="non_blocking",
                            evidence="The proposal does not include a review date.",
                            required_correction="Optionally add a review date.",
                        )
                    ],
                    summary="One substantiated blocking defect remains.",
                ),
                AdversarialReview(
                    ambiguities=[
                        Defect(
                            description="A secondary term could be defined more precisely.",
                            severity="non_blocking",
                            evidence="The term is understandable but not formally defined.",
                            required_correction="Optionally define the term.",
                        )
                    ],
                    risks=[
                        Defect(
                            description="An extreme external change could alter the decision.",
                            severity="speculative",
                            evidence="No such change is present in the supplied problem.",
                            required_correction="",
                        )
                    ],
                    summary="No substantiated blocking defects remain.",
                ),
            ]
        )
        self.calls = 0
        self.messages = []

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        self.messages.append(messages)
        return {
            "parsed": next(self.reviews),
            "raw": _Message(),
            "parsing_error": None,
        }


class _IntakeModerator:
    def __init__(self, owner) -> None:
        self.owner = owner

    def invoke(self, messages):
        self.owner.intake_calls += 1
        return {
            "parsed": Criteria(
                restated_problem="Make and explain a decision.",
                criteria=[
                    "States the decision",
                    "Explains the trade-off",
                    "Avoids unsupported claims",
                ],
            ),
            "raw": _Message(),
            "parsing_error": None,
        }


class _Moderator:
    def __init__(self) -> None:
        self.intake_calls = 0
        self.finalize_calls = 0

    def with_structured_output(self, *args, **kwargs):
        return _IntakeModerator(self)

    def invoke(self, messages):
        self.finalize_calls += 1
        return _Message("moderated final answer")


class AdversarialGraphTests(unittest.TestCase):
    def test_blocking_defect_revises_then_non_blocking_findings_approve(self) -> None:
        author = _Author()
        reviewer = _AdversarialReviewer()
        moderator = _Moderator()
        with (
            patch.object(v3_nodes, "agent_a_llm", return_value=author),
            patch.object(v3_nodes, "agent_b_llm", return_value=reviewer),
            patch.object(v3_nodes, "moderator_llm", return_value=moderator),
            patch.dict("os.environ", {"LANGSMITH_TRACING": "false"}),
        ):
            result = build_v3_graph().invoke(
                {"problem": "Make and explain a decision", "max_rounds": 3}
            )

        self.assertEqual(result["variant"], "v3-adversarial-reviewer")
        self.assertEqual(result["verdict"], "consensus")
        self.assertEqual(result["final_answer"], "moderated final answer")
        self.assertEqual(result["criteria"], [
            "States the decision",
            "Explains the trade-off",
            "Avoids unsupported claims",
        ])
        self.assertNotIn("criteria_history", result)
        self.assertEqual(len(result["usage"]), 6)
        self.assertEqual(author.calls, 2)
        self.assertEqual(reviewer.calls, 2)
        self.assertEqual(moderator.intake_calls, 1)
        self.assertEqual(moderator.finalize_calls, 1)
        for messages in reviewer.messages:
            reviewer_prompt = messages[-1].content
            self.assertIn("FIXED ACCEPTANCE CRITERIA", reviewer_prompt)
            self.assertIn("Explains the trade-off", reviewer_prompt)
        self.assertNotIn("criteria", result["reviews"][0].model_dump())
        self.assertFalse(result["reviews"][0].approved)
        self.assertTrue(result["reviews"][1].approved)
        self.assertEqual(
            result["reviews"][0].required_changes,
            ["Explain the trade-off and its consequences."],
        )
        revision_prompt = author.messages[1][-1].content
        self.assertIn("The required trade-off is absent.", revision_prompt)
        self.assertNotIn("recommendation may age poorly", revision_prompt)

        transcript = json.loads(render_json(result))
        self.assertEqual(transcript["scores"], [])
        self.assertEqual(transcript["blocking_defects"], [1, 0])
        self.assertIn("moderator", transcript["models"])
        markdown = render_markdown(result)
        self.assertIn("Blocking-defect trend:** 1 → 0", markdown)
        self.assertIn("Missing requirements", markdown)
        self.assertIn("SPECULATIVE", markdown)
        html = render_html(result)
        self.assertIn("Agent B &mdash; adversarial reviewer", html)
        self.assertIn("1 blocking", html)

    def test_approval_is_derived_only_from_blocking_findings(self) -> None:
        review = AdversarialReview(
            edge_cases=[
                Defect(
                    description="An optional edge case is not discussed.",
                    severity="non_blocking",
                    evidence="It is outside the explicit scope.",
                    required_correction="Optionally document it.",
                )
            ],
            summary="No blocking defects.",
        )

        self.assertTrue(review.approved)
        self.assertEqual(review.required_changes, [])
        self.assertNotIn("approved", AdversarialReview.model_json_schema()["properties"])
        self.assertTrue(review.model_dump()["approved"])


if __name__ == "__main__":
    unittest.main()
