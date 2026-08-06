"""Render a finished run into a readable transcript.

LangGraph Studio shows you the live trace, but it is a debugging view — it is
per-node, ephemeral, and awkward to share. These helpers turn the final state into an
artifact you can read end to end, diff between runs, or hand to someone else:

    result = graph.invoke({"problem": "..."})
    Path("run.md").write_text(render_markdown(result))
    Path("run.html").write_text(render_html(result))

Both renderers walk the ``proposals``/``reviews`` history pairwise, so round N shows
exactly what Agent A wrote and what Agent B said about it.
"""

from __future__ import annotations

import html
import json
from typing import Any

from .models import active_models
from .schemas import Review, Usage
from .state import ConsensusState

VERDICT_LABELS = {
    "consensus": "Consensus reached",
    "no_consensus": "No consensus — round limit reached",
    "stalled": "No consensus — review stalled",
}


def _as_review(value: Any) -> Any:
    if isinstance(value, Review):
        return value
    if hasattr(value, "categorized_findings"):
        return value
    if "missing_requirements" in value:
        from .variants.v3_adversarial_reviewer.state import AdversarialReview

        return AdversarialReview.model_validate(value)
    if "criteria" in value:
        from .variants.v1_posthoc_reviewer.state import PostHocReview

        return PostHocReview.model_validate(value)
    return Review.model_validate(value)


def _models_for(state: ConsensusState) -> dict[str, str]:
    models = active_models()
    if state.get("variant") == "v1-posthoc-reviewer":
        return {key: models[key] for key in ("agent_a", "agent_b")}
    return models


def _rounds(state: ConsensusState) -> list[tuple[int, str, Any | None]]:
    """Pair each proposal with its review. A trailing unreviewed proposal yields None."""
    proposals = list(state.get("proposals") or [])
    reviews = [_as_review(r) for r in state.get("reviews") or []]
    return [
        (i, proposal, reviews[i - 1] if i <= len(reviews) else None)
        for i, proposal in enumerate(proposals, start=1)
    ]


def _usage_summary(
    state: ConsensusState,
) -> tuple[list[dict[str, Any]], int | None, float | None]:
    usage = [
        u.model_dump() if isinstance(u, Usage) else dict(u)
        for u in state.get("usage") or []
    ]
    tokens = [u["total_tokens"] for u in usage if u.get("total_tokens") is not None]
    costs = [u["cost"] for u in usage if u.get("cost") is not None]
    total_tokens = sum(tokens) if usage and len(tokens) == len(usage) else None
    total_cost = sum(costs) if usage and len(costs) == len(usage) else None
    return usage, total_tokens, total_cost


def _format_cost(cost: float | None) -> str:
    if cost is None:
        return "—"
    digits = 6 if cost == 0 or abs(cost) < 0.01 else 4 if abs(cost) < 1 else 2
    return f"${cost:.{digits}f}"


def summary(state: ConsensusState) -> dict[str, Any]:
    """Compact machine-readable summary of a run."""
    reviews = [_as_review(r) for r in state.get("reviews") or []]
    usage, total_tokens, total_cost = _usage_summary(state)
    return {
        "verdict": state.get("verdict"),
        "rounds": state.get("round"),
        "max_rounds": state.get("max_rounds"),
        "scores": [r.score for r in reviews if hasattr(r, "score")],
        "blocking_defects": [
            len(r.blocking_findings())
            for r in reviews
            if hasattr(r, "blocking_findings")
        ],
        "approved": bool(reviews and reviews[-1].approved),
        "criteria": list(state.get("criteria") or []),
        "variant": state.get("variant", "v1-posthoc-reviewer"),
        "variant_version": state.get("variant_version", 1),
        "models": _models_for(state),
        "model_calls": len(usage),
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "usage": usage,
    }


def render_markdown(state: ConsensusState) -> str:
    """Full transcript as Markdown."""
    models = _models_for(state)
    verdict = state.get("verdict") or "unknown"
    reviews = [_as_review(r) for r in state.get("reviews") or []]
    scored = [r for r in reviews if hasattr(r, "score")]
    scores = " → ".join(f"{r.score}/10" for r in scored) or "—"
    defect_counts = [
        len(r.blocking_findings())
        for r in reviews
        if hasattr(r, "blocking_findings")
    ]
    usage, total_tokens, total_cost = _usage_summary(state)
    role_rows = []
    if "moderator" in models:
        role_rows.append(f"| Moderator | `{models['moderator']}` |")
    role_rows += [
        f"| Agent A (author) | `{models['agent_a']}` |",
        f"| Agent B (reviewer) | `{models['agent_b']}` |",
    ]

    out: list[str] = [
        "# Consensus run",
        "",
        f"**Outcome:** {VERDICT_LABELS.get(verdict, verdict)}  ",
        f"**Variant:** {state.get('variant', 'v1-posthoc-reviewer')}  ",
        f"**Rounds:** {state.get('round', '?')} of {state.get('max_rounds', '?')}  ",
        (
            "**Blocking-defect trend:** " + " → ".join(map(str, defect_counts))
            if defect_counts
            else f"**Score trend:** {scores}"
        ),
        f"**Model calls:** {len(usage)}  ",
        (
            f"**Total tokens:** {total_tokens:,}"
            if total_tokens is not None
            else "**Total tokens:** —"
        ),
        f"**Total cost:** {_format_cost(total_cost)}",
        "",
        "| Role | Model |",
        "| --- | --- |",
        *role_rows,
        "",
        "## Problem",
        "",
        state.get("restated_problem") or state.get("problem", ""),
        "",
        "## Acceptance criteria",
        "",
    ]
    out += [f"{i}. {c}" for i, c in enumerate(state.get("criteria") or [], start=1)]
    out += ["", "## Rounds", ""]

    for number, proposal, review in _rounds(state):
        out += [f"### Round {number}", "", "**Agent A proposed:**", "", proposal, ""]
        if review is None:
            out += ["_Not reviewed._", ""]
            continue
        badge = "APPROVED" if review.approved else "CHANGES REQUESTED"
        criteria = getattr(review, "criteria", None)
        if criteria:
            criteria_label = (
                "Agent B's adversarial criteria"
                if hasattr(review, "categorized_findings")
                else "Agent B's post-hoc criteria"
            )
            out += [f"**{criteria_label}:**", ""]
            out += [f"{i}. {criterion}" for i, criterion in enumerate(criteria, 1)]
            out += [""]
        if hasattr(review, "categorized_findings"):
            blocking = len(review.blocking_findings())
            out += [
                f"**Agent B — {badge} ({blocking} blocking defects):**",
                "",
                review.summary,
                "",
            ]
            for category, findings in review.categorized_findings():
                out += [f"**{category}:**", ""]
                if not findings:
                    out += ["- None", ""]
                    continue
                for finding in findings:
                    out += [
                        f"- **{finding.severity.replace('_', ' ').upper()}** — "
                        f"{finding.description}",
                        f"  - Evidence: {finding.evidence}",
                        f"  - Required correction: {finding.required_correction or 'None'}",
                    ]
                out += [""]
        else:
            out += [
                f"**Agent B — {badge} ({review.score}/10):**",
                "",
                review.critique,
                "",
            ]
            if review.required_changes:
                out += ["**Required changes:**", ""]
                out += [f"- {c}" for c in review.required_changes]
                out += [""]

    out += ["## Final answer", "", state.get("final_answer") or "_(none)_", ""]
    return "\n".join(out)


_CSS = """
:root { color-scheme: light dark; --fg:#111; --muted:#666; --bg:#fff; --card:#f6f6f7;
        --line:#e2e2e5; --ok:#0a7d33; --warn:#a2500a; --accent:#3b5bdb; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8ea; --muted:#9a9aa2; --bg:#131316; --card:#1c1c21;
          --line:#2c2c33; --ok:#4ac16f; --warn:#e0a458; --accent:#8fa4ff; }
}
* { box-sizing: border-box; }
body { margin:0; padding:2.5rem 1.25rem; background:var(--bg); color:var(--fg);
       font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width: 62rem; margin: 0 auto; }
h1 { font-size:1.75rem; margin:0 0 .4rem; }
h2 { font-size:1.25rem; margin:2.5rem 0 .75rem; padding-bottom:.35rem;
     border-bottom:1px solid var(--line); }
.sub { color:var(--muted); margin:0 0 1.5rem; }
.meta { display:flex; flex-wrap:wrap; gap:.5rem; margin:0 0 1.5rem; padding:0; list-style:none; }
.meta li { background:var(--card); border:1px solid var(--line); border-radius:999px;
           padding:.25rem .75rem; font-size:.85rem; }
.meta b { font-weight:600; }
code { background:var(--card); padding:.1rem .35rem; border-radius:4px; font-size:.9em; }
.round { border:1px solid var(--line); border-radius:10px; margin:0 0 1rem;
         background:var(--card); overflow:hidden; }
.round > summary { cursor:pointer; padding:.85rem 1rem; font-weight:600;
                   display:flex; align-items:center; gap:.6rem; }
.round > summary::-webkit-details-marker { display:none; }
.round > summary:hover { background:rgba(128,128,128,.08); }
.badge { font-size:.75rem; font-weight:700; letter-spacing:.03em; padding:.15rem .5rem;
         border-radius:999px; border:1px solid currentColor; }
.badge.ok { color:var(--ok); } .badge.warn { color:var(--warn); }
.body { padding:0 1rem 1rem; }
.who { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--accent); font-weight:700; margin:1rem 0 .35rem; }
pre { white-space:pre-wrap; word-wrap:break-word; background:var(--bg);
      border:1px solid var(--line); border-radius:8px; padding:.85rem;
      margin:0; font:13.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }
ul.changes { margin:.4rem 0 0; padding-left:1.25rem; }
ol.criteria { padding-left:1.4rem; }
.final { border:2px solid var(--accent); border-radius:10px; padding:1rem; }
table { border-collapse:collapse; width:100%; }
"""


def _esc(text: str) -> str:
    return html.escape(text or "")


def render_html(state: ConsensusState, *, title: str = "Consensus run") -> str:
    """Full transcript as a standalone HTML page.

    No external assets, so it opens straight from disk and survives being emailed
    around. Rounds are collapsible; the last one starts open.
    """
    models = _models_for(state)
    verdict = state.get("verdict") or "unknown"
    reviews = [_as_review(r) for r in state.get("reviews") or []]
    rounds = _rounds(state)
    usage, total_tokens, total_cost = _usage_summary(state)

    meta = [
        f"<li><b>Outcome:</b> {_esc(VERDICT_LABELS.get(verdict, verdict))}</li>",
        f"<li><b>Variant:</b> {_esc(state.get('variant', 'v1-posthoc-reviewer'))}</li>",
        f"<li><b>Rounds:</b> {_esc(str(state.get('round', '?')))}"
        f" of {_esc(str(state.get('max_rounds', '?')))}</li>",
        (
            "<li><b>Blocking defects:</b> "
            + " &rarr; ".join(
                str(len(r.blocking_findings()))
                for r in reviews
                if hasattr(r, "blocking_findings")
            )
            + "</li>"
            if any(hasattr(r, "blocking_findings") for r in reviews)
            else "<li><b>Scores:</b> "
            + (" &rarr; ".join(f"{r.score}/10" for r in reviews) or "&mdash;")
            + "</li>"
        ),
        f"<li><b>Author:</b> <code>{_esc(models['agent_a'])}</code></li>",
        f"<li><b>Reviewer:</b> <code>{_esc(models['agent_b'])}</code></li>",
        f"<li><b>Model calls:</b> {len(usage)}</li>",
        (
            f"<li><b>Total tokens:</b> {total_tokens:,}</li>"
            if total_tokens is not None
            else "<li><b>Total tokens:</b> &mdash;</li>"
        ),
        f"<li><b>Total cost:</b> {_esc(_format_cost(total_cost))}</li>",
    ]
    if "moderator" in models:
        meta.insert(6, f"<li><b>Moderator:</b> <code>{_esc(models['moderator'])}</code></li>")

    criteria = "".join(
        f"<li>{_esc(c)}</li>" for c in (state.get("criteria") or [])
    )

    blocks: list[str] = []
    for number, proposal, review in rounds:
        is_last = number == len(rounds)
        if review is None:
            badge = '<span class="badge warn">NOT REVIEWED</span>'
            review_html = ""
        else:
            cls, label = (
                ("ok", "APPROVED") if review.approved else ("warn", "CHANGES REQUESTED")
            )
            adversarial = hasattr(review, "categorized_findings")
            metric = (
                f"{len(review.blocking_findings())} blocking"
                if adversarial
                else f"{review.score}/10"
            )
            badge = (
                f'<span class="badge {cls}">{label}</span>'
                f'<span class="badge {cls}">{metric}</span>'
            )
            changes = ""
            posthoc_criteria = ""
            review_criteria = getattr(review, "criteria", None)
            if review_criteria:
                items = "".join(f"<li>{_esc(c)}</li>" for c in review_criteria)
                criteria_label = (
                    "Agent B adversarial criteria"
                    if adversarial
                    else "Agent B post-hoc criteria"
                )
                posthoc_criteria = (
                    f'<div class="who">{criteria_label}</div>'
                    f'<ol class="criteria">{items}</ol>'
                )
            if adversarial:
                finding_blocks = []
                for category, findings in review.categorized_findings():
                    items = "".join(
                        "<li>"
                        f"<b>{_esc(finding.severity.replace('_', ' ').upper())}</b> &mdash; "
                        f"{_esc(finding.description)}<br>"
                        f"<b>Evidence:</b> {_esc(finding.evidence)}<br>"
                        "<b>Required correction:</b> "
                        f"{_esc(finding.required_correction or 'None')}"
                        "</li>"
                        for finding in findings
                    ) or "<li>None</li>"
                    finding_blocks.append(
                        f'<div class="who">{_esc(category)}</div><ul class="changes">{items}</ul>'
                    )
                review_html = (
                    f'<div class="who">Agent B &mdash; adversarial reviewer</div>'
                    f"{posthoc_criteria}<pre>{_esc(review.summary)}</pre>"
                    + "".join(finding_blocks)
                )
            else:
                if review.required_changes:
                    items = "".join(f"<li>{_esc(c)}</li>" for c in review.required_changes)
                    changes = (
                        '<div class="who">Required changes</div>'
                        f'<ul class="changes">{items}</ul>'
                    )
                review_html = (
                    f'<div class="who">Agent B &mdash; reviewer</div>'
                    f"{posthoc_criteria}<pre>{_esc(review.critique)}</pre>{changes}"
                )

        blocks.append(
            f'<details class="round"{" open" if is_last else ""}>'
            f"<summary>Round {number}{badge}</summary>"
            f'<div class="body">'
            f'<div class="who">Agent A &mdash; author</div>'
            f"<pre>{_esc(proposal)}</pre>"
            f"{review_html}"
            f"</div></details>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{_esc(title)}</h1>
<p class="sub">{_esc(state.get('restated_problem') or state.get('problem', ''))}</p>
<ul class="meta">{''.join(meta)}</ul>
<h2>Acceptance criteria</h2>
<ol class="criteria">{criteria}</ol>
<h2>Rounds</h2>
{''.join(blocks)}
<h2>Final answer</h2>
<div class="final"><pre>{_esc(state.get('final_answer') or '(none)')}</pre></div>
</main></body></html>
"""


def render_json(state: ConsensusState) -> str:
    """The whole run as JSON — for diffing runs or feeding an eval harness."""
    payload = {
        **summary(state),
        "problem": state.get("problem"),
        "restated_problem": state.get("restated_problem"),
        "rounds_detail": [
            {
                "round": number,
                "proposal": proposal,
                "review": review.model_dump() if review else None,
            }
            for number, proposal, review in _rounds(state)
        ],
        "final_answer": state.get("final_answer"),
    }
    return json.dumps(payload, indent=2)
