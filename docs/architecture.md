# Architecture

## The graph

```mermaid
flowchart TD
    START([start]) --> intake
    intake["intake<br/><i>moderator</i><br/>problem → criteria"] --> agent_a
    agent_a["agent_a<br/><i>author</i><br/>writes a full solution"] --> agent_b
    agent_b["agent_b<br/><i>reviewer</i><br/>returns a Review"] --> route{route}
    route -->|not approved,<br/>rounds left| agent_a
    route -->|approved| finalize
    route -->|round limit| finalize
    route -->|stalled| finalize
    finalize["finalize<br/><i>moderator</i><br/>verdict + answer"] --> END([end])
```

Four nodes, one cycle. The cycle is `agent_a → agent_b → agent_a`, and everything
interesting is in when it exits.

## Roles

| Node | Role | Returns | Notes |
| --- | --- | --- | --- |
| `intake` | Moderator | `Criteria` (structured) | Restates the problem, emits 3–6 checkable criteria |
| `agent_a` | Author | free text | Always a **complete standalone** solution, never a diff |
| `agent_b` | Reviewer | `Review` (structured) | Grades against the criteria only |
| `finalize` | Moderator | free text | Derives the verdict, writes the user-facing answer |

## Why the moderator isn't the router

The obvious reading of "the moderator decides whether to loop" is an LLM call that
looks at the review and answers yes/no. This project deliberately doesn't do that.

Agent B already returns `approved: bool`. A model asked to re-derive that decision
from the same evidence adds a round trip, real cost, and a fresh way to be wrong — in
exchange for no information that wasn't already in the boolean. So routing is a plain
Python conditional edge.

The moderator is a real LLM at the two points where judgment genuinely adds
something: **framing** an ambiguous problem into gradeable criteria, and
**synthesising** several rounds of history into one answer. Those are the parts a
`bool` can't do.

## Routing rules

`route()` in `graph.py` picks the destination:

| Condition | Next | Verdict |
| --- | --- | --- |
| `review.approved` | `finalize` | `consensus` |
| `round >= max_rounds` | `finalize` | `no_consensus` |
| Score flat or falling for 2 consecutive rounds | `finalize` | `stalled` |
| otherwise | `agent_a` | — |

The **stall guard** exists because the round limit alone is a bad backstop. If a
criterion is unsatisfiable — or the reviewer has fixated — the score parks at 6/10 and
every remaining round is a full author+reviewer pair spent producing nothing. The
guard notices the score has stopped moving and exits early. `STALL_PATIENCE` controls
how many flat rounds to tolerate (default 2) — like every tunable, it's an environment
variable, read through `config.py`.

`route()` returns only a destination; **`finalize` derives the verdict itself** from
the same three signals. One place decides how a run is characterised, so the label in
the transcript can't drift from the reason the loop actually stopped.

## State

```python
class ConsensusState(TypedDict, total=False):
    problem: str                                     # input
    max_rounds: int                                  # input, defaults to $MAX_ROUNDS
    restated_problem: str                            # set by intake
    criteria: list[str]                              # set by intake
    round: int
    proposal: str                                    # latest only
    proposals: Annotated[list[str], operator.add]    # full history
    reviews: Annotated[list[Review], operator.add]   # full history
    verdict: Literal["consensus", "no_consensus", "stalled"]
    final_answer: str
```

`proposals` and `reviews` use additive reducers, so each round **appends** instead of
overwriting. That history is what `finalize` summarises over and what the transcript
renderer walks pairwise — round *N*'s proposal sits at `proposals[N-1]` and its
review at `reviews[N-1]`.

`proposal` (singular) is the latest one, kept separate so `agent_a` and `agent_b`
don't have to index into the history on every call.

## Structured verdicts

Agent B returns a validated object, not prose the router has to pattern-match:

```python
class Review(BaseModel):
    approved: bool
    score: int  # 1-10
    critique: str
    required_changes: list[str]
```

Both providers get this via `with_structured_output(Review, method="json_schema")`,
which uses native schema-enforced structured outputs rather than the tool-calling
workaround.

One wrinkle worth knowing: **Anthropic's structured outputs don't support numeric
bounds**, so LangChain strips Pydantic's `ge`/`le` off the wire schema (it folds the
range into the field description instead) and enforces them client-side. A model
returning `11` would therefore raise a `ValidationError` *after* the call — throwing
away a run that already spent several expensive rounds. `Review` has a `mode="before"`
validator that clamps to 1–10 instead. The score only drives stall detection, so
clamping costs nothing and removes the crash.

## Prompt design

The two prompt rules that matter most, both in `prompts.py`:

1. **Criteria must be checkable** (`MODERATOR_INTAKE`). The prompt spends most of its
   budget on this with contrasting examples, because vague criteria are the single
   biggest cause of a loop that won't converge.

2. **The reviewer may not move the goalposts** (`AGENT_B`). A critic that invents a
   new requirement each round guarantees `no_consensus` no matter how good the author
   is. Agent B is told to grade against the listed criteria and nothing else, and to
   approve when they're met even if further polish is imaginable.

`agent_a` omits the critique block **entirely** on round 1, rather than sending
placeholder text like "N/A" that the model has to interpret.

## Files

```
src/agentic_consensus/
├── config.py      every tunable, read from the environment
├── state.py       ConsensusState, Criteria, Review
├── models.py      provider-agnostic model factories
├── prompts.py     the system prompts
├── nodes.py       intake / agent_a / agent_b / finalize
├── graph.py       wiring + route(), exports `graph`
├── transcript.py  markdown / HTML / JSON renderers
└── __main__.py    CLI runner
```
