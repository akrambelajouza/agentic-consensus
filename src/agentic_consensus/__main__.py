"""Run a consensus loop from the terminal and write out the transcript.

    uv run python -m agentic_consensus "Design a rate limiter for a multi-tenant API"
    uv run python -m agentic_consensus -f problem.txt --rounds 3 --out runs/limiter

Progress streams live as each node finishes, so you can watch the score move without
opening Studio. Use Studio when you want to inspect or replay individual node
payloads; use this when you want a shareable artifact at the end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .transcript import (
    VERDICT_LABELS,
    render_html,
    render_json,
    render_markdown,
    _as_review,
)
from .variants.registry import (
    DEFAULT_VARIANT,
    V1_POSTHOC_REVIEWER,
    VARIANTS,
    get_variant,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agentic_consensus",
        description="Run a named Agent A / Agent B review workflow.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("problem", nargs="?", help="The problem statement.")
    source.add_argument("-f", "--file", type=Path, help="Read the problem from a file.")
    parser.add_argument(
        "--variant",
        choices=tuple(VARIANTS),
        default=DEFAULT_VARIANT,
        help=f"Workflow variant to run (default: {DEFAULT_VARIANT}).",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=None,
        metavar="N",
        help="Maximum A/B rounds before giving up. Overrides MAX_ROUNDS "
        f"(currently {config.max_rounds()}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="PREFIX",
        help="Write PREFIX.md, PREFIX.html and PREFIX.json.",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress live progress output."
    )
    return parser.parse_args(argv)


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        # Resolve every env-backed setting up front so a typo in `.env` fails here,
        # before the first paid call, with the variable name in the message.
        cfg = config.settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verbose = not args.quiet
    rounds = args.rounds if args.rounds is not None else cfg["max_rounds"]
    variant = get_variant(args.variant)

    problem = args.file.read_text(encoding="utf-8") if args.file else args.problem
    if not problem or not problem.strip():
        print("error: the problem statement is empty.", file=sys.stderr)
        return 2

    roles: dict = cfg["roles"]
    configured_roles = [("author", "agent_a"), ("reviewer", "agent_b")]
    if args.variant != V1_POSTHOC_REVIEWER:
        configured_roles.append(("moderator", "moderator"))
    _log(verbose, f"variant   {variant.label}")
    for label, role in configured_roles:
        r = roles[role]
        _log(verbose, f"{label:<9} {r['model']}  ({r['max_tokens']:,} tok, {r['effort']} effort)")
    _log(verbose, f"{'rounds':<9} max {rounds}, stall patience {cfg['stall_patience']}\n")

    graph = variant.build_graph()
    state: dict = {
        "problem": problem,
        "variant": variant.id,
        "variant_version": variant.version,
    }

    # `updates` yields one dict per node as it finishes: {node_name: returned_keys}.
    for chunk in graph.stream(
        {
            "problem": problem,
            "variant": variant.id,
            "variant_version": variant.version,
            "max_rounds": rounds,
        },
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            state.update(
                {
                    k: (
                        state.get(k, []) + v
                        if k in ("proposals", "reviews", "criteria_history", "usage")
                        else v
                    )
                    for k, v in update.items()
                }
            )
            if node == "intake":
                _log(verbose, f"intake   {len(update['criteria'])} criteria:")
                for i, c in enumerate(update["criteria"], start=1):
                    _log(verbose, f"           {i}. {c}")
            elif node == "agent_a":
                chars = len(update["proposal"])
                _log(verbose, f"\nround {update['round']}  agent A proposed ({chars:,} chars)")
            elif node == "agent_b":
                review = _as_review(update["reviews"][0])
                if hasattr(review, "criteria"):
                    _log(verbose, "         reviewer criteria:")
                    for i, criterion in enumerate(review.criteria, start=1):
                        _log(verbose, f"           {i}. {criterion}")
                mark = "APPROVED" if review.approved else "CHANGES REQUESTED"
                if hasattr(review, "categorized_findings"):
                    blocking = len(review.blocking_findings())
                    _log(verbose, f"         agent B: {mark} ({blocking} blocking defects)")
                    for category, findings in review.categorized_findings():
                        for finding in findings:
                            _log(
                                verbose,
                                f"           - [{finding.severity}] {category}: "
                                f"{finding.description}",
                            )
                else:
                    _log(verbose, f"         agent B: {mark} ({review.score}/10)")
                    for c in review.required_changes:
                        _log(verbose, f"           - {c}")
                if update.get("verdict"):
                    verdict = update["verdict"]
                    _log(verbose, f"\n{VERDICT_LABELS.get(verdict, verdict)}\n")
            elif node == "finalize":
                verdict = update["verdict"]
                _log(verbose, f"\n{VERDICT_LABELS.get(verdict, verdict)}\n")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        for suffix, text in (
            (".md", render_markdown(state)),
            (".html", render_html(state)),
            (".json", render_json(state)),
        ):
            path = args.out.with_suffix(suffix)
            path.write_text(text, encoding="utf-8")
            _log(verbose, f"wrote {path}")
    else:
        print(state.get("final_answer", ""))

    # Non-zero exit when the agents never agreed, so this composes in a pipeline.
    return 0 if state.get("verdict") == "consensus" else 1


if __name__ == "__main__":
    raise SystemExit(main())
