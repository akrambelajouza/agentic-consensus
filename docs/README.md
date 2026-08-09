# Documentation

Three named LangGraph workflows explore criteria timing and reviewer posture: V1
derives criteria after the answer, V2 commits to them beforehand, and V3 keeps V2's
fixed criteria while replacing scoring with an adversarial search for defects.

| Page | What's in it |
| --- | --- |
| [architecture.md](architecture.md) | The graph, the state, the routing rules, why the moderator isn't the router |
| [variants.md](variants.md) | V1–V3 topology, reviewer behavior, selection, and cost shape |
| [configuration.md](configuration.md) | Environment defaults plus persisted web settings, models, budgets, and tracing |
| [experiments.md](experiments.md) | Running one controlled problem through V1–V3 and reading the comparison |
| [providers.md](providers.md) | Anthropic, OpenAI and OpenRouter; mixing vendors across roles |
| [visualization.md](visualization.md) | Watching a run, the web UI, and exporting a shareable transcript |
| [troubleshooting.md](troubleshooting.md) | Failure modes and what actually causes them |

## 60-second version

```bash
uv sync --extra dev --extra web --extra openrouter
cp .env.example .env          # add OpenRouter and EU LangSmith keys
```

`.env` holds the defaults for models, round cap, stall guard, token budgets, and
reasoning effort. The web Settings page can persist OpenRouter and LangSmith
overrides in SQLite. Nothing needs editing in source. See
[configuration.md](configuration.md).

Run it from the terminal and get an HTML transcript:

```bash
uv run consensus "Design a rate limiter for a multi-tenant API" --out runs/limiter
```

The default command runs the answer-first V1 graph. Add
`--variant v2-moderated-reviewer` to run the moderated V2 graph.
Use `--variant v3-adversarial-reviewer` for the score-free defect-finding graph.

Or run it interactively in LangGraph Studio:

```bash
uv run langgraph dev --studio-url https://eu.smith.langchain.com
```

Or from a browser, with run history and saved architecture comparisons:

```bash
uv sync --extra dev --extra web --extra openrouter
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

V1 is cheaper, but its criteria may be anchored to what Agent A chose to discuss. V2's
criteria are independent of the proposal but require moderator calls. V1 keeps
each round's rubric in `criteria_history` so that later comparison can measure this
rather than relying on impressions. V3 tests whether an evidence-backed adversarial
reviewer reduces false approvals without causing excessive rejection.
