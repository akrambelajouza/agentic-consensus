# Seeing what each agent said

Five ways, depending on whether you want to watch a run happen or read it afterwards.

| | Live | Artifact | Best for |
| --- | --- | --- | --- |
| [LangGraph Studio](#1-langgraph-studio) | yes | no | Debugging, replaying, editing state mid-run |
| [CLI progress](#2-cli-progress) | yes | no | Watching the score move without leaving the terminal |
| [Transcripts](#3-transcripts) | no | md / html / json | Reading, sharing, diffing runs |
| [Python](#4-from-python) | either | whatever you build | Evals and custom tooling |
| [Web UI](#5-web-ui) | yes | persisted + replayable | Clicking through a run node by node, browsing past runs |

## 1. LangGraph Studio

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

This selects the EU Studio host. Without `--studio-url`, LangGraph CLI defaults to the
US host, whose login and organizations are separate from EU LangSmith. Open the URL
it prints and submit:

```json
{ "problem": "Design a rate limiter for a multi-tenant API", "max_rounds": 4 }
```

Studio gives you the node-by-node trace: click any node to see its exact input and
output, watch the `agent_a → agent_b` cycle repeat, and time-travel to re-run from any
step. It's the best view while you're *changing* the graph — the transcript renderers
below are better once you want to read or share a result.

Things worth clicking into:

- **`intake`** — are the criteria concrete? This is where most bad runs are decided.
- **round 2's `agent_a` input** — it should contain round 1's `required_changes`
  verbatim. If it doesn't, the feedback isn't reaching the author.
- **`reviews[].score`** — should trend upward.

## 2. CLI progress

```bash
uv run consensus "Design a rate limiter for a multi-tenant API"
```

Each node reports as it finishes:

```
author   anthropic:claude-opus-5
reviewer anthropic:claude-sonnet-5
moderator anthropic:claude-opus-5

intake   3 criteria:
           1. Enforces a per-tenant request quota over a sliding window
           2. Allows a configurable burst above the steady-state rate
           3. States the time and space complexity per request

round 1  agent A proposed (4,182 chars)
         agent B: CHANGES REQUESTED (5/10)
           - Describe how burst credit refills
           - State complexity for the eviction path

round 2  agent A proposed (5,006 chars)
         agent B: APPROVED (9/10)

Consensus reached
```

Progress goes to **stderr** and the final answer to **stdout**, so redirection works:

```bash
uv run consensus "..." > answer.md          # answer only, progress still on screen
uv run consensus "..." --quiet > answer.md  # nothing but the answer
```

Exit code is `0` on consensus and `1` otherwise, so it composes:

```bash
uv run consensus -f spec.txt --rounds 3 --quiet > out.md || echo "did not converge"
```

Other flags: `-f/--file` to read the problem from a file, `--rounds N`, `--out PREFIX`.

## 3. Transcripts

`--out PREFIX` writes three files:

```bash
uv run consensus "Design a rate limiter" --out runs/limiter
# runs/limiter.md  runs/limiter.html  runs/limiter.json
```

**`.html`** — a standalone page with no external assets, so it opens from disk and
survives being emailed. Each round is a collapsible block (the last one open) showing
Agent A's full proposal, then Agent B's verdict badge, score, critique, and required
changes. Header carries the outcome, score trend, and which model played each role.
Follows the system light/dark theme.

**`.md`** — the same content linearly, for pasting into a PR, an issue, or a doc.

**`.json`** — structured, for diffing runs or feeding an eval harness:

```json
{
  "verdict": "consensus",
  "rounds": 2,
  "scores": [5, 9],
  "criteria": ["..."],
  "models": { "agent_a": "anthropic:claude-opus-5", "agent_b": "openai:gpt-5" },
  "rounds_detail": [
    { "round": 1, "proposal": "...", "review": { "approved": false, "score": 5, "...": "..." } }
  ]
}
```

The renderers pair proposals with reviews positionally, so round *N* always shows the
proposal that was reviewed and the review it got — never a mismatched pair.

## 4. From Python

```python
from pathlib import Path
from agentic_consensus import graph, render_html, render_markdown, summary

result = graph.invoke({"problem": "...", "max_rounds": 3})

print(summary(result))
# {'verdict': 'consensus', 'rounds': 2, 'scores': [5, 9], 'approved': True, ...}

Path("run.html").write_text(render_html(result, title="Rate limiter"))
Path("run.md").write_text(render_markdown(result))
```

Stream it yourself to build your own progress UI:

```python
for chunk in graph.stream({"problem": "..."}, stream_mode="updates"):
    for node, update in chunk.items():
        if node == "agent_b":
            review = update["reviews"][0]
            print(node, review.score, review.approved)
```

`stream_mode="updates"` yields `{node_name: keys_that_node_returned}` as each node
finishes — that's exactly what the CLI's progress output is built on.

## 5. Web UI

```bash
uv sync --extra web
uv run consensus-web    # http://127.0.0.1:8000
```

Three pages, reachable from the same top nav:

- **Single Run → New run** — choose V1, V2, or V3, submit a problem, and watch it stream live over
  Server-Sent Events: a flow
  panel on the left (Intake → Agent A · Round *N* → Agent B · Round *N* → ... →
  Finalize, appended as each node finishes), a details panel on the right showing
  the selected node's role, model, effort, duration, token usage, reasoning/cache
  token details, provider-reported cost, and content rendered as Markdown. The flow
  shows tokens and cost per call; a completed run shows total calls, tokens, and cost.
- **History** — every completed run (any verdict), most recent first, searchable and
  sortable by variant, cost, tokens, duration, and outcome. Backed by SQLite
  (`CONSENSUS_DB_PATH`, default
  `consensus.db`) — see [configuration.md](configuration.md#web-ui-run-history).
  Runs that error out mid-way are not saved.
- **Replay** (`/history/{id}`) — click a row to see that run exactly as it looked
  live, reconstructed entirely from the saved state. No LLM calls, so it's free and
  instant, and it survives server restarts.

Export buttons on both New run (after a run finishes) and Replay produce the same
`.md`/`.html`/`.json` as the CLI's `--out`, via `render_markdown`/`render_html`/
`render_json` — one renderer, three ways to reach it.

## Diagramming the graph

The graph object can render its own topology:

```python
from agentic_consensus import graph

print(graph.get_graph().draw_mermaid())        # paste into any mermaid renderer
graph.get_graph().draw_mermaid_png(output_file_path="graph.png")
```

`draw_ascii()` also works but needs `grandalf` installed. A hand-maintained mermaid
version of the same diagram is in [architecture.md](architecture.md#the-graph).
