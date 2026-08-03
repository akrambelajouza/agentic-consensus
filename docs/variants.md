# Workflow variants

The repository keeps two graphs deliberately separate so their cost and behaviour
can be compared later without turning one graph into a maze of experiment flags.

| Variant | Graph | Criteria timing | Calls for *R* rounds |
| --- | --- | --- | --- |
| `v1-moderated-criteria` | Moderator → Author ↔ Reviewer → Moderator | Before the first proposal | `2 + 2R` |
| `v2-posthoc-reviewer` | Author ↔ Reviewer | After each proposal, inside its review | `2R` |

## V1 — Moderated criteria

V1 is the original and default graph. The moderator commits to criteria before Agent
A writes. Agent B receives those fixed criteria on every round. A final moderator
call synthesizes the history.

This design protects the rubric from being anchored to Agent A's answer, at the cost
of two additional model calls and a longer sequential path.

## V2 — Post-hoc reviewer

V2 sends the raw user problem directly to Agent A. Agent B then receives both the raw
problem and the proposal, derives 3-6 criteria, and reviews the proposal in one
structured-output call. Rejected proposals loop back to Agent A. Approval, the round
limit, or the stall guard ends the graph directly; Agent A's latest proposal is the
final answer.

Every round preserves its own criteria in `criteria_history`. This is intentional:
criteria drift and answer-conditioned rubrics are hypotheses to measure, not details
to hide by overwriting state.

## Selection

```bash
uv run consensus --variant v1-moderated-criteria "..."
uv run consensus --variant v2-posthoc-reviewer "..."
```

The web UI exposes the same registry as a selector. LangGraph Studio exposes both
graphs by their public IDs. Existing library imports continue to resolve to V1 for
backward compatibility; programmatic selection uses `get_variant(id).build_graph()`.
