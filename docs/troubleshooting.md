# Troubleshooting

## Setup

### `GraphLoadError: attempted relative import with no known parent package`

`langgraph.json` points at a **file path** instead of a module. LangGraph imports
file-path specs without package context, so the relative imports in `graph.py` fail.

```jsonc
// wrong
"v1-moderated-criteria": "./src/agentic_consensus/variants/v1_moderated_criteria/graph.py:graph"
// right — no "/", so it is imported as a module
"v1-moderated-criteria": "agentic_consensus.variants.v1_moderated_criteria.graph:graph"
```

Module syntax works because `"dependencies": ["."]` installs the package.

### Studio redirects to `/o/null/` or asks you to log in again

The CLI defaults to the US Studio at `https://smith.langchain.com`. EU accounts,
sessions, and organizations live separately at `https://eu.smith.langchain.com`, so
an EU login is not visible to the US host. Start the development server explicitly
against EU Studio:

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

The “Not seeing LangSmith runs?” warning is related but separate. To enable tracing,
create an API key in the EU UI and configure `LANGSMITH_API_KEY`,
`LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`, and
`LANGSMITH_TRACING=true` in `.env`. Restart the server after changing `.env`.

### `ImportError: The 'openai'/'openrouter' provider needs langchain-openai`

A role is set to `openai:` or `openrouter:` but the extra isn't installed. Both use
the same client, so either extra fixes both:

```bash
uv sync --extra openrouter
```

### `ValueError: OPENROUTER_API_KEY is not set`

The `openrouter` provider deliberately does **not** fall back to `OPENAI_API_KEY`,
even though it reuses `ChatOpenAI`. Silently sending an OpenAI key to OpenRouter would
fail as a confusing 401 from a host you didn't think you were calling.

### `ValueError: Cannot infer a provider from model '...'`

A bare model name that doesn't match a known shape (`/` → openrouter, `claude*` →
anthropic, `gpt-*` → openai). Write the explicit form:

```bash
AGENT_B_MODEL=openrouter:your/model-id
```

### OpenRouter: request fails mentioning `response_format` or no available provider

`intake` and `agent_b` need JSON-schema structured output, and on OpenRouter that's a
property of the routed **endpoint**, not the model ID. `build_llm` already sends
`provider: {require_parameters: true}` to constrain routing; if no backend for that
model qualifies, the request fails rather than silently returning unparseable prose.

Check the model before switching to it:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.id=="your/model-id") | .supported_parameters'
```

You want `structured_outputs` and `reasoning_effort` in that list. Agent A is exempt —
it returns free text, so any routable model works there.

### `error: MAX_ROUNDS='four' is not an integer`

A malformed value in `.env`. Config is validated at startup, before the first paid
call, and the message names the variable, the bad value, and what was expected. Every
accepted value is listed in [configuration.md](configuration.md#every-variable).

### A setting in `.env` seems to be ignored

Two usual causes:

1. **A real environment variable is shadowing it.** Exported vars win over the file by
   design, so a stale `export MAX_ROUNDS=8` in your shell profile silently overrides
   `.env`. Check with `env | grep -E 'MAX_ROUNDS|STALL|AGENT_|MODERATOR_'`.
2. **`--rounds` on the CLI.** The flag overrides `MAX_ROUNDS`; omit it to use the file.

To see what actually resolved, run `uv run python -c "from agentic_consensus import
settings; print(settings())"` — or just read the header the CLI prints on every run.

### Editor says packages aren't installed

Your editor is pointed at a different interpreter than `.venv`. Select
`.venv/bin/python` as the workspace interpreter. `uv run` is unaffected.

## Web UI

### `TypeError: Failed to fetch` when clicking Run

The browser tab is open but `consensus-web` isn't running (or was stopped) — the
page itself doesn't go stale, so this is easy to hit after closing the terminal it
was running in. Start it again:

```bash
uv run consensus-web
```

and confirm you're browsing the address it printed (`http://127.0.0.1:8000` by
default, or your `--port` if you set one).

### A run doesn't show up in History

By design if the run errored mid-way — only runs that reach `finalize` (any
verdict: consensus, no_consensus, or stalled) are persisted. Check the error banner
on the page, or the server's stderr, for what actually failed.

If a run that *did* finish is still missing, check `CONSENSUS_DB_PATH` hasn't
changed between runs — each value points at a different SQLite file, so a run saved
under one path won't appear when the server is started with another. See
[configuration.md](configuration.md#web-ui-run-history).

## Run quality

### Agent B approves round 1 every time

Almost always the criteria, not the reviewer. Vague criteria ("is well designed") are
trivially satisfiable, so the first proposal clears them.

Check `intake` output first. If the criteria are soft, tighten `MODERATOR_INTAKE`
with domain-specific examples of what a real criterion looks like for your problem
space. Only if the criteria are genuinely sharp and still get waved through is
`AGENT_B` the thing to make stricter.

### It never converges — always `no_consensus`

Three usual causes, in order of likelihood:

1. **The reviewer is moving the goalposts.** Read the critiques in sequence. If round
   3 raises something that isn't in the criteria and wasn't mentioned in round 1, that
   is the bug. `AGENT_B` already forbids this; strengthen it, or lower the bar
   explicitly ("approve when every criterion is met, even if further polish is
   imaginable").
2. **A criterion is unsatisfiable as written.** Look at which one is cited every
   round. The stall guard should catch this — if it did, the verdict is `stalled`
   rather than `no_consensus`, which is the tell.
3. **The author isn't getting the feedback.** Check round 2's `agent_a` input in
   Studio; it should contain round 1's `required_changes` verbatim.

### Verdict is `stalled`

By design: the score stopped improving while the proposal stayed unapproved, so the
loop exited instead of burning the remaining rounds. Read the last critique — it names
what the reviewer is stuck on. Usually an unsatisfiable criterion or a genuine
disagreement between the two models.

To tolerate slower progress, raise `STALL_PATIENCE` in `.env`.

### The final answer reads like a changelog

The author is writing diffs instead of complete solutions. `AGENT_A` instructs
"complete standalone solution, not a diff" — if you edited that prompt, put it back.
It's load-bearing: the reader only ever sees the latest proposal.

### Scores bounce around (7 → 4 → 8)

The reviewer is grading inconsistently, which also makes stall detection unreliable.
Make the criteria more objective — bouncing scores usually mean the reviewer is
exercising taste because the criteria don't decide the question for it.

## Cost and latency

### A run costs more than expected

`1 + 2·rounds + 1` model calls, most on the largest model in the config. Every lever
below is a line in `.env`:

- `MAX_ROUNDS=2` while iterating on prompts.
- `AGENT_B_MODEL=` a cheaper model — the reviewer grades against fixed criteria and
  doesn't need the author's horsepower.
- `AGENT_B_EFFORT=medium`. On Claude Opus 5, `low` and `medium` are unusually strong;
  sweep before assuming you need `high`.
- `STALL_PATIENCE=1` to exit unproductive runs a round earlier.

### Responses get cut off mid-sentence

`max_tokens` is too low. On Claude it caps thinking **plus** visible output, and
adaptive thinking is on by default on Opus 5 and Sonnet 5 — so a budget sized for the
answer alone truncates. Raise the relevant role's budget in `.env`
(`AGENT_A_MAX_TOKENS`, `AGENT_B_MAX_TOKENS`, `MODERATOR_MAX_TOKENS`); Agent A needs
the most.

### `400` mentioning `temperature` / `top_p` / `top_k`

Claude Opus 5 and Sonnet 5 reject non-default sampling parameters. Remove them — the
factories in `models.py` deliberately never set them. Steer with the prompts and
`reasoning_effort` instead.

## Data

### `ValidationError` on `score`

Shouldn't happen: `Review` clamps out-of-range scores to 1–10 in a `mode="before"`
validator, because Anthropic's structured outputs drop numeric bounds from the wire
schema and Pydantic would otherwise raise *after* the call and discard the run. If you
see one anyway, the model returned a non-numeric score — check `AGENT_B`'s prompt
hasn't been edited into asking for a letter grade.

### Reviews come back as dicts instead of `Review` objects

Expected after a checkpointer round-trip. `_as_review()` in `nodes.py`,
`transcript.py`, and `graph.py` normalises both shapes — use it rather than assuming
the type.
