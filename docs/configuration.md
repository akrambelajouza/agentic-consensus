# Configuration

Everything tunable lives in `.env`. There are no settings to change in source —
`config.py` reads each one from the environment, and the same values apply whether you
run the CLI, LangGraph Studio, or the library.

```bash
cp .env.example .env
```

`.env` is loaded automatically: by `langgraph dev` via `langgraph.json`, and by
`config.py` via `python-dotenv` for the CLI and library. Real environment variables
take precedence over the file, so a one-off override works:

```bash
MAX_ROUNDS=2 AGENT_B_EFFORT=medium uv run consensus "..."
```

## Every variable

### Credentials

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Required if any role uses the `anthropic` provider |
| `OPENAI_API_KEY` | Required if any role uses the `openai` provider |
| `OPENROUTER_API_KEY` | Required if any role uses the `openrouter` provider |

You only need keys for the providers you actually route to. `openrouter` reaches both
Claude and GPT models on one account, and does **not** fall back to `OPENAI_API_KEY`
despite sharing a client — a missing key raises a message naming the right variable.

> `langchain-anthropic` reads `ANTHROPIC_API_KEY` from the environment. It does
> **not** pick up an `ant auth login` OAuth profile, so a real key is required.

### Loop control

| Variable | Default | Min | Effect |
| --- | --- | --- | --- |
| `MAX_ROUNDS` | `4` | 1 | Author→reviewer rounds before giving up |
| `STALL_PATIENCE` | `2` | 1 | Consecutive non-improving reviews that end the loop |

`MAX_ROUNDS` counts **author→reviewer pairs**, not node executions. A run that hits
the cap makes `1 + 2·MAX_ROUNDS + 1` model calls: intake, each round's author and
reviewer, and finalize. Set it to `2` while iterating on prompts — a 4-round run is
about nine calls, most of them on the most expensive model in the config.

Lower `STALL_PATIENCE` to `1` to bail the moment a round fails to improve — cheaper,
but it will cut off genuine slow progress. Raise it if your reviewer's scores are
noisy round to round.

### Models

| Variable | Default |
| --- | --- |
| `MODERATOR_MODEL` | `anthropic:claude-opus-5` |
| `AGENT_A_MODEL` | `anthropic:claude-opus-5` |
| `AGENT_B_MODEL` | `anthropic:claude-sonnet-5` |
| `EVALUATOR_MODEL` | inherits `AGENT_B_MODEL` |

Specs are `provider:model` over `anthropic`, `openai`, or `openrouter` — see
[providers.md](providers.md). `.env.example` ships with the OpenRouter equivalents
filled in, since one key there reaches both vendors.

### Token budgets

| Variable | Default | Min |
| --- | --- | --- |
| `MODERATOR_MAX_TOKENS` | `8000` | 256 |
| `AGENT_A_MAX_TOKENS` | `16000` | 256 |
| `AGENT_B_MAX_TOKENS` | `8000` | 256 |
| `EVALUATOR_MAX_TOKENS` | inherits Agent B | 256 |

Agent A gets double because it writes the actual deliverable every round, in full.

**On Claude, `max_tokens` caps thinking *plus* response text.** Adaptive thinking is
on by default on Opus 5 and Sonnet 5, so a budget sized only for the visible answer
will truncate mid-sentence. That's why these numbers look generous.

### Reasoning effort

| Variable | Default |
| --- | --- |
| `MODERATOR_EFFORT` | `high` |
| `AGENT_A_EFFORT` | `high` |
| `AGENT_B_EFFORT` | `high` |
| `EVALUATOR_EFFORT` | inherits Agent B |

Passed through as `reasoning_effort`. The two providers accept different vocabularies:

| Provider | Accepted |
| --- | --- |
| `anthropic` | `low` `medium` `high` `xhigh` `max` |
| `openai` | `minimal` `low` `medium` `high` |
| `openrouter` | all six |

You can set any of the six. `models.py` folds a level the target provider doesn't
accept onto its nearest supported neighbour (`xhigh`/`max` → `high` for OpenAI,
`minimal` → `low` for Anthropic), so changing a role's provider never breaks a run on
an effort value.

Dropping `AGENT_B_EFFORT` to `medium` is the cheapest meaningful saving — the reviewer
grades against fixed criteria and doesn't need the author's horsepower.

> **Never set `temperature`, `top_p`, or `top_k`.** Claude Opus 5 and Sonnet 5 reject
> non-default sampling parameters with a 400, and OpenAI reasoning models ignore them.
> `models.py` deliberately never sets them. Steer through the prompts and effort.

### LangSmith Studio and tracing

The environment template targets the EU LangSmith region:

| Variable | Default in `.env.example` | Purpose |
| --- | --- | --- |
| `LANGSMITH_API_KEY` | empty | EU-issued key used to send traces to LangSmith |
| `LANGSMITH_ENDPOINT` | `https://eu.api.smith.langchain.com` | Keeps SDK traffic in the EU LangSmith instance |
| `LANGSMITH_TRACING` | `true` | Enables LangSmith tracing |
| `LANGSMITH_PROJECT` | `agentic-consensus` | Project that receives the traces |
| `LANGSMITH_WORKSPACE_ID` | unset | Needed only when the key can access multiple workspaces |

Create the API key at `https://eu.smith.langchain.com`. If a workspace ID is needed,
copy it from Settings → General; the organization ID in an `/o/...` browser URL is a
different value.

The Studio browser host is not controlled by `.env`. Launch the local server with:

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

### Web UI run history

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONSENSUS_DB_PATH` | `consensus.db` | SQLite file the web UI persists completed runs to |

Only `consensus-web` reads this — the CLI, Studio, and library never write here.
Every graph that completes with a verdict is saved automatically; a run that errors
mid-way is not. Browse past runs on the web UI's History page.

## Bad values fail loudly

A malformed setting raises at startup, before the first paid call, naming the
variable:

```
error: MAX_ROUNDS='four' is not an integer. Expected a whole number of at least 1 (default: 4).
error: AGENT_A_EFFORT='turbo' is not a recognised value. Expected one of minimal, low, medium, high, xhigh, max (default: high).
```

Falling back to the default silently would be worse — you'd pay for a full run before
noticing the setting did nothing.

## Run inputs

`max_rounds` can also be passed per run, which overrides `MAX_ROUNDS`:

```python
graph.invoke({"problem": "...", "max_rounds": 3})
```

```bash
uv run consensus "..." --rounds 3
```

| Key | Required | Default | Meaning |
| --- | --- | --- | --- |
| `problem` | yes | — | The raw problem statement |
| `max_rounds` | no | `MAX_ROUNDS` | Maximum A/B rounds before giving up |

## Reading the resolved config

```python
>>> from agentic_consensus import settings
>>> settings()
{'max_rounds': 4,
 'stall_patience': 2,
 'roles': {'moderator': {'model': 'anthropic:claude-opus-5', 'max_tokens': 8000, 'effort': 'high'},
           'agent_a':   {'model': 'anthropic:claude-opus-5', 'max_tokens': 16000, 'effort': 'high'},
           'agent_b':   {'model': 'anthropic:claude-sonnet-5', 'max_tokens': 8000, 'effort': 'high'}}}
```

The CLI prints the same thing as a header on every run, so a transcript always records
what produced it.

Values are read on each access rather than frozen at import, so a test can change one
with `monkeypatch.setenv` without reimporting the package.

## Tuning the prompts

Prompts are the one thing still in source, under each named variant directory —
they're prose, not settings. For V1, in rough order of leverage:

1. **`MODERATOR_INTAKE`** — the highest-leverage prompt in the project. If criteria
   come out vague, nothing downstream can save the run. Add domain-specific guidance
   here about what a good criterion looks like for *your* problem space.

2. **`AGENT_B`** — controls how strict the loop is. If it approves round 1 every time,
   the bar is too low; if it never approves, check that it isn't inventing
   requirements beyond the criteria.

3. **`AGENT_A`** — mostly about output shape. The "complete standalone solution, not a
   diff" instruction is load-bearing: without it the author starts writing changelogs
   and the final answer becomes unreadable.

4. **`FINALIZE_CONSENSUS` / `FINALIZE_NO_CONSENSUS`** — presentation only. The
   no-consensus variant deliberately forces an explicit "criteria still unmet"
   section so a failed run can't be mistaken for a successful one at a glance.
