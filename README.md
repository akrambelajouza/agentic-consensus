# agentic-consensus

Three LangGraph author/reviewer workflows built for a later controlled comparison. V1
uses a **Moderator** to commit to criteria before **Agent A** writes and **Agent B**
reviews. V2 removes the moderator: Agent B derives criteria after seeing each
proposal and reviews it in the same call. V3 returns to V1's moderated topology and
changes only Agent B into an adversarial defect finder.

| Variant | Shape | Main trade-off |
| --- | --- | --- |
| `v1-moderated-criteria` (default) | Moderator → Author ↔ Reviewer → Moderator | Independent criteria; two extra calls |
| `v2-posthoc-reviewer` | Author ↔ Reviewer | Cheaper; criteria may anchor to the proposal |
| `v3-adversarial-reviewer` | Moderator → Author ↔ Adversarial reviewer → Moderator | Fixed criteria plus concrete defect evidence |

V1:

```
START → intake ─→ agent_a ─→ agent_b ─→ [route]
                     ↑                     │
                     └──── revise ─────────┤
                                           ↓
                                       finalize → END
```

V2:

```text
START → agent_a ─→ agent_b ─→ [route] → END
            ↑          │
            └─ revise ─┘
```

V3 uses V1's topology and fixed intake criteria. Agent B searches five defect
categories and loops only when at least one substantiated `blocking` finding exists.
It has no numeric score.

## How V1 works

| Node       | Role      | Default model     | What it does                                            |
| ---------- | --------- | ----------------- | ------------------------------------------------------- |
| `intake`   | Moderator | `claude-opus-5`   | Restates the problem, emits 3–6 checkable criteria       |
| `agent_a`  | Author    | `claude-opus-5`   | Writes a complete standalone solution                    |
| `agent_b`  | Reviewer  | `claude-sonnet-5` | Grades against the criteria, returns a structured verdict |
| `finalize` | Moderator | `claude-opus-5`   | Derives the verdict and writes the user-facing answer    |

Agent B is on a **different model** on purpose: a reviewer sharing the author's model
tends to share its blind spots and rubber-stamp its own reasoning. Each role takes a
`provider:model` spec (`anthropic`, `openai`, or `openrouter`), so you can push that
further and run the critic on a different vendor entirely — see
[docs/providers.md](docs/providers.md).

**No Anthropic or OpenAI account?** Route through OpenRouter: one key reaches both
vendors' models, including the ones above.

### The verdict is structured, not parsed

Agent B returns a schema-validated object rather than prose the router has to
regex over:

```python
class Review(BaseModel):
    approved: bool
    score: int  # 1-10
    critique: str
    required_changes: list[str]
```

Both providers get this through the same call
(`with_structured_output(Review, method="json_schema")`), which uses native
schema-enforced structured outputs rather than the tool-calling workaround.

### Routing is deterministic

Routing is a plain conditional edge, not a fourth LLM call. Agent B already returns
`approved: bool` — asking a model "should we loop again?" would add a round trip,
cost, and a failure mode for no information. The Moderator is an LLM at the two points
where judgment actually helps: framing the problem, and synthesising the outcome.

| Condition                                       | Next       | Verdict        |
| ----------------------------------------------- | ---------- | -------------- |
| `review.approved`                               | `finalize` | `consensus`    |
| `round >= max_rounds`                           | `finalize` | `no_consensus` |
| Score hasn't improved for 2 consecutive rounds  | `finalize` | `stalled`      |
| otherwise                                       | `agent_a`  | —              |

The stall guard stops an unsatisfiable criterion from burning every remaining round —
a full author+reviewer pair each — on a critic that keeps re-scoring 6/10 with the
same complaint.

A run that ends `no_consensus` or `stalled` is **not** dressed up as a success: the
moderator presents the best proposal, then a labelled section naming which criteria
remain unmet and what the outstanding objection was.

## Setup

```bash
uv sync --extra dev --extra openrouter   # one key for both vendors' models
cp .env.example .env                     # add your OpenRouter and EU LangSmith keys
```

`.env.example` is preconfigured for OpenRouter — a Claude author reviewed by a GPT
critic — because it needs a single account. To go direct to the vendor APIs instead,
uncomment the `anthropic:` / `openai:` specs in that file and set
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (`--extra openai` for the latter).

`langchain-anthropic` reads `ANTHROPIC_API_KEY` from the environment. It does **not**
pick up an `ant auth login` OAuth profile — a real key in `.env` is required.

### Everything is configured in `.env`

There are no settings to edit in source. `.env` holds the models, the round cap, the
stall guard, per-role token budgets, and per-role reasoning effort:

```bash
MAX_ROUNDS=4                     # author→reviewer rounds before giving up
STALL_PATIENCE=2                 # non-improving reviews that end the loop early
AGENT_A_MODEL=openrouter:anthropic/claude-opus-5
AGENT_B_MODEL=openrouter:openai/gpt-5.5
AGENT_A_MAX_TOKENS=16000
AGENT_B_EFFORT=medium            # cheapest meaningful saving
```

The file is loaded by `langgraph dev`, the CLI, and the library alike; real environment
variables override it, so `MAX_ROUNDS=2 uv run consensus "..."` works for a one-off. A
malformed value fails at startup naming the variable, before the first paid call. Full
table in [docs/configuration.md](docs/configuration.md).

## Run

### CLI — watch it, then keep the transcript

```bash
uv run consensus "Design a rate limiter for a multi-tenant API" --out runs/limiter
```

Select V2 explicitly:

```bash
uv run consensus --variant v2-posthoc-reviewer \
  "Design a rate limiter for a multi-tenant API"
```

Select V3 explicitly:

```bash
uv run consensus --variant v3-adversarial-reviewer \
  "Design a rate limiter for a multi-tenant API"
```

Progress streams to stderr as each node finishes; the final answer goes to stdout.
`--out` additionally writes `runs/limiter.{md,html,json}`. Exit code is `0` on
consensus and `1` otherwise, so it composes in a pipeline.

```
intake   3 criteria:
           1. Enforces a per-tenant request quota over a sliding window
           ...
round 1  agent A proposed (4,182 chars)
         agent B: CHANGES REQUESTED (5/10)
           - Describe how burst credit refills
round 2  agent A proposed (5,006 chars)
         agent B: APPROVED (9/10)

Consensus reached
```

### Web UI — run it from a browser

```bash
uv sync --extra web
uv run consensus-web                  # http://127.0.0.1:8000
```

Choose a workflow, submit a problem on **Home**, and watch it stream live node by
node (the same events the CLI logs to stderr, over Server-Sent Events): a flow panel
on the left, and a details
panel on the right showing each node's model, effort, duration, token usage,
provider-reported cost, and content rendered as markdown. Completed runs also show
total calls, tokens, and cost. OpenRouter costs come directly from its response
rather than a local price estimate; providers that do not report cost are labelled
unavailable. No auth, no external service — it's a thin transport around
`graph.stream()`, so it reads whatever `.env` already configures. Use
`--host 0.0.0.0` to expose it beyond localhost, `--port` to change the port.

Every completed run is saved to a local SQLite file
(`CONSENSUS_DB_PATH`, default `consensus.db`) and shows up on **History** — a
searchable, sortable table of past runs. Click one to replay it on its own page,
identical to how it looked live, reconstructed entirely from the saved state (no
LLM calls). Runs that error out mid-way are not saved.

### Studio — inspect and replay individual steps

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

Studio exposes all three graphs under their public variant IDs. The explicit Studio URL
matters for EU LangSmith accounts: the CLI otherwise opens
the US host, where an EU login and organization do not exist. Add an EU-created
`LANGSMITH_API_KEY` to `.env` to enable hosted traces; the local graph itself can run
without that key. Open the URL the command prints and submit:

```json
{
  "problem": "Design a rate limiter for a multi-tenant API with per-tenant quotas and burst allowance.",
  "max_rounds": 4
}
```

`max_rounds` is optional and falls back to `MAX_ROUNDS` from `.env` (default 4). Use
`2` while iterating on prompts — a 4-round run is roughly nine model calls, most on the
largest model in the config.

### Library

```python
from agentic_consensus import graph, render_html

result = graph.invoke({"problem": "...", "max_rounds": 3})
result["verdict"]        # consensus | no_consensus | stalled
result["reviews"]        # every critique, in order
open("run.html", "w").write(render_html(result))
```

### What to look for in a run

1. `intake` emits concrete criteria. If they're vague ("is well designed"), the loop
   won't converge and that prompt is what needs fixing first.
2. `agent_a → agent_b` runs more than once — the loop actually loops.
3. Round 2's `agent_a` input contains round 1's `required_changes` verbatim.
4. `reviews[].score` trends upward and the run ends `approved: true`.

## Documentation

Full docs in [docs/](docs/):
[architecture](docs/architecture.md) · [variants](docs/variants.md) ·
[configuration](docs/configuration.md) ·
[providers](docs/providers.md) ·
[visualization](docs/visualization.md) ·
[troubleshooting](docs/troubleshooting.md)

## Layout

```
src/agentic_consensus/
├── variants/
│   ├── registry.py
│   ├── v1_moderated_criteria/  graph / nodes / prompts / state
│   ├── v2_posthoc_reviewer/    graph / nodes / prompts / state
│   └── v3_adversarial_reviewer/ graph / nodes / prompts / state
├── config.py      every tunable, read from the environment
├── state.py       backward-compatible V1 schema exports
├── schemas.py     Review / Usage / Verdict shared by variants
├── models.py      provider-agnostic model factories
├── usage.py       shared token and cost extraction
├── graph.py       backward-compatible default V1 graph export
├── transcript.py  markdown / HTML / JSON renderers
├── __main__.py    CLI runner
├── web.py         FastAPI app (`--extra web`): routes, worker thread, persistence
├── web_templates.py  Home/History/Replay pages — shared CSS/JS, self-contained HTML
└── db.py          SQLite run history for the web UI
```
