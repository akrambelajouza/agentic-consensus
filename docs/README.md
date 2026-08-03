# Documentation

Two named LangGraph workflows explore when evaluation criteria should be created:
V1 commits to them before the answer, while V2 derives them after seeing the answer.

| Page | What's in it |
| --- | --- |
| [architecture.md](architecture.md) | The graph, the state, the routing rules, why the moderator isn't the router |
| [variants.md](variants.md) | V1 versus V2 topology, criteria timing, selection, and cost shape |
| [configuration.md](configuration.md) | Every `.env` variable: rounds, stall guard, models, token budgets, effort |
| [providers.md](providers.md) | Anthropic, OpenAI and OpenRouter; mixing vendors across roles |
| [visualization.md](visualization.md) | Watching a run, the web UI, and exporting a shareable transcript |
| [troubleshooting.md](troubleshooting.md) | Failure modes and what actually causes them |

## 60-second version

```bash
uv sync --extra dev --extra openrouter
cp .env.example .env          # add OpenRouter and EU LangSmith keys
```

`.env` holds **every** tunable — models, round cap, stall guard, token budgets,
reasoning effort. Nothing needs editing in source. See
[configuration.md](configuration.md).

Run it from the terminal and get an HTML transcript:

```bash
uv run consensus "Design a rate limiter for a multi-tenant API" --out runs/limiter
```

Add `--variant v2-posthoc-reviewer` to run the answer-first V2 graph.

Or run it interactively in LangGraph Studio:

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

Or from a browser, with a history of past runs:

```bash
uv sync --extra web
uv run consensus-web    # http://127.0.0.1:8000
```

Or from Python:

```python
from agentic_consensus import graph

result = graph.invoke({"problem": "...", "max_rounds": 3})
result["verdict"]        # "consensus" | "no_consensus" | "stalled"
result["final_answer"]
result["reviews"]        # every critique, in order
```

## The experiment worth knowing up front

V1's criteria are independent of the proposal but require moderator calls. V2 is
cheaper, but its criteria may be anchored to what Agent A chose to discuss. V2 keeps
each round's rubric in `criteria_history` so that later comparison can measure this
rather than relying on impressions.
