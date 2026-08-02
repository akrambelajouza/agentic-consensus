# Documentation

A three-agent LangGraph loop. A **Moderator** turns a problem into checkable
acceptance criteria, **Agent A** proposes a solution, **Agent B** grades it against
those criteria, and rejected proposals go back to A with the critique attached — until
B approves or a stopping rule fires.

| Page | What's in it |
| --- | --- |
| [architecture.md](architecture.md) | The graph, the state, the routing rules, why the moderator isn't the router |
| [configuration.md](configuration.md) | Every `.env` variable: rounds, stall guard, models, token budgets, effort |
| [providers.md](providers.md) | Anthropic, OpenAI and OpenRouter; mixing vendors across roles |
| [visualization.md](visualization.md) | Watching a run and exporting a shareable transcript |
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

Or run it interactively in LangGraph Studio:

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

Or from Python:

```python
from agentic_consensus import graph

result = graph.invoke({"problem": "...", "max_rounds": 3})
result["verdict"]        # "consensus" | "no_consensus" | "stalled"
result["final_answer"]
result["reviews"]        # every critique, in order
```

## The one thing worth knowing up front

The quality of this loop is set almost entirely by the **acceptance criteria** the
moderator writes at intake. Criteria like *"handles concurrent writes without lost
updates"* give Agent B something to actually decide. Criteria like *"is well
designed"* give it nothing, and the loop either rubber-stamps round 1 or grinds to
`no_consensus` on vibes.

If a run goes wrong, read the criteria first. It is the fix far more often than the
author or reviewer prompt is.
