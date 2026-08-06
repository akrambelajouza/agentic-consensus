# Workflow variants

The repository keeps three graphs deliberately separate so their cost and behaviour
can be compared later without turning one graph into a maze of experiment flags.

| Variant | Graph | Criteria timing | Calls for *R* rounds |
| --- | --- | --- | --- |
| `v1-posthoc-reviewer` | Author ↔ Reviewer | After each proposal, inside its review | `2R` |
| `v2-moderated-reviewer` | Moderator → Author ↔ Reviewer → Moderator | Before the first proposal | `2 + 2R` |
| `v3-adversarial-reviewer` | Moderator → Author ↔ Adversarial reviewer → Moderator | Before the first proposal | `2 + 2R` |

## V1 — Post-hoc reviewer

V1 is the default baseline. It sends the raw user problem directly to Agent A. Agent
B then receives both the raw problem and the proposal, derives 3–6 criteria, and
reviews the proposal in one structured-output call. Rejected proposals loop back to
Agent A. Approval, the round limit, or the stall guard ends the graph directly;
Agent A's latest proposal is the final answer.

Every round preserves its own criteria in `criteria_history`. This is intentional:
criteria drift and answer-conditioned rubrics are hypotheses to measure, not details
to hide by overwriting state.

## V2 — Moderated reviewer

V2 adds a moderator that commits to criteria before Agent A writes. Agent B receives
those fixed criteria on every round. A final moderator call synthesizes the history.

This design protects the rubric from being anchored to Agent A's answer, at the cost
of two additional model calls and a longer sequential path.

## V3 — Adversarial reviewer

V3 retains V2's intake, fixed criteria, author/reviewer loop, and moderator finalizer.
The controlled change is Agent B's objective: it tries to prove that the proposal is
not ready by searching for missing requirements, violated acceptance criteria, edge
cases, ambiguities, and risks. Each finding carries severity, evidence, and a required
correction.

The model does not output a numeric score or an independent approval flag. Approval
is derived in code: any `blocking` finding requests revision; `non_blocking` and
`speculative` findings remain visible but cannot prevent approval. Its stall guard
tracks whether the number of blocking findings is decreasing.

Because V2 and V3 share topology and call count, their comparison isolates reviewer
posture more cleanly than a comparison with V1: criteria timing and moderator
cost stay constant while scoring is replaced by adversarial defect search.

## Selection

```bash
uv run consensus --variant v1-posthoc-reviewer "..."
uv run consensus --variant v2-moderated-reviewer "..."
uv run consensus --variant v3-adversarial-reviewer "..."
```

The web UI exposes the same registry as a selector. LangGraph Studio exposes all three
graphs by their public IDs. The convenience library import resolves to the default V1;
programmatic selection uses `get_variant(id).build_graph()`.
