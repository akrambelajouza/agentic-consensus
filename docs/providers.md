# Providers

Each of the three roles is configured independently with a `provider:model` spec.
Supported providers:

| Provider | Reaches | Key |
| --- | --- | --- |
| `anthropic` | Claude models, vendor API | `ANTHROPIC_API_KEY` |
| `openai` | GPT models, vendor API | `OPENAI_API_KEY` |
| `openrouter` | Both of the above and much else, one account | `OPENROUTER_API_KEY` |

**No Anthropic or OpenAI account? Use `openrouter`** — it reaches both vendors' models
with a single key, and the models this project defaults to are available through it.
See [Via OpenRouter](#via-openrouter).

## Defaults

| Role | Env var | Default |
| --- | --- | --- |
| Moderator | `MODERATOR_MODEL` | `anthropic:claude-opus-5` |
| Agent A (author) | `AGENT_A_MODEL` | `anthropic:claude-opus-5` |
| Agent B (reviewer) | `AGENT_B_MODEL` | `anthropic:claude-sonnet-5` |

The defaults assume vendor accounts. `.env.example` ships with the OpenRouter
equivalents filled in instead, so a fresh `cp .env.example .env` needs only a key.

## Spec format

```
provider:model
```

```bash
AGENT_A_MODEL=anthropic:claude-opus-5
AGENT_B_MODEL=openrouter:openai/gpt-5.5
```

A bare model name works too — the provider is inferred:

| Shape | Inferred | Example |
| --- | --- | --- |
| contains `/` | `openrouter` | `anthropic/claude-opus-5` |
| starts `claude` | `anthropic` | `claude-opus-5` |
| starts `gpt-`, `o1`, `o3`, `o4` | `openai` | `gpt-5` |

Only a *known* provider name counts as a prefix, which is what keeps OpenRouter IDs
carrying their own colon suffix from being misparsed:

```python
>>> parse_spec("anthropic/claude-sonnet-5:batch")
('openrouter', 'anthropic/claude-sonnet-5:batch')   # not provider "anthropic/claude-sonnet-5"
```

Anything unrecognised raises a clear `ValueError` at construction rather than a
confusing 404 mid-run:

```python
>>> parse_spec("mystery-model")
ValueError: Cannot infer a provider from model 'mystery-model'. Write the spec as
'provider:model' using one of ('anthropic', 'openai', 'openrouter'), e.g.
'anthropic:claude-opus-5' or 'openrouter:anthropic/claude-opus-5'
```

Prefer the explicit form in committed config. Inference is a convenience for
one-off overrides.

## Via OpenRouter

```bash
uv sync --extra openrouter
```

```bash
OPENROUTER_API_KEY=sk-or-...
MODERATOR_MODEL=openrouter:anthropic/claude-opus-5
AGENT_A_MODEL=openrouter:anthropic/claude-opus-5
AGENT_B_MODEL=openrouter:openai/gpt-5.5
```

That's a Claude author reviewed by a GPT critic on one account — the cross-vendor
setup described below, without holding either vendor account.

### The constraint that actually matters

`intake` and `agent_b` both parse into Pydantic, so they need JSON-schema structured
output. On OpenRouter **that's a property of the endpoint, not the model**: the same
model ID can route to several upstream backends with different capabilities.

Two things handle this:

1. `build_llm` sends `provider: {require_parameters: true}`, which restricts routing to
   backends that honour every parameter in the request.
2. If none does, the request fails with an explicit error — it does not silently drop
   `response_format` and hand back unparseable prose.

To check a model before committing to it, filter the model list on
`supported_parameters=structured_outputs`, or query the API directly:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.id=="anthropic/claude-opus-5") | .supported_parameters'
```

Verified present for both `anthropic/claude-opus-5` and `anthropic/claude-sonnet-5`:
`structured_outputs`, `response_format`, and `reasoning_effort`.

Agent A is the relaxed one — it returns free text, so any model OpenRouter routes to
will do. If you want to experiment with an exotic author, that's the role to do it in.

## Enabling OpenAI directly

`langchain-openai` is an optional extra so an Anthropic-only install stays lean:

```bash
uv sync --extra openai
```

Then set a key and at least one role:

```bash
OPENAI_API_KEY=sk-...
AGENT_B_MODEL=openai:gpt-5
```

If you point a role at `openai:` or `openrouter:` without the extra installed, you get
an actionable ImportError naming the fix, not a `ModuleNotFoundError` traceback. Both
extras install the same package — `openrouter` speaks the OpenAI wire format, so it
reuses `ChatOpenAI` against a different `base_url`.

> **Check the model ID against your own account.** Which models you can call depends on
> your organisation's access. The spec is a plain string passed straight through, so
> any model your key can reach works — verify with `openai models list`, the OpenRouter
> models endpoint, or the relevant dashboard if a call 404s.

## Mixing vendors

This is the most interesting configuration, and the reason the abstraction exists:

```bash
# with vendor accounts
AGENT_A_MODEL=anthropic:claude-opus-5
AGENT_B_MODEL=openai:gpt-5

# or the same thing on one OpenRouter key
AGENT_A_MODEL=openrouter:anthropic/claude-opus-5
AGENT_B_MODEL=openrouter:openai/gpt-5.5
```

The whole design rests on Agent B being a genuinely independent check. A reviewer
running the *same* model as the author shares its blind spots — if the author's model
misreads the problem in a particular way, the reviewer tends to misread it the same
way and approve. Different model families fail differently, so a cross-vendor critic
catches a class of error a same-model critic structurally cannot.

The default config already applies a weaker version of this (Opus author, Sonnet
reviewer). Cross-vendor is the stronger version.

Going direct needs both keys and both extras; going through OpenRouter needs one of
each.

## What the abstraction relies on

The graph never branches on provider because every integration exposes the three
things it needs:

| Need | Anthropic | OpenAI | OpenRouter |
| --- | --- | --- | --- |
| Schema-enforced structured output | `with_structured_output(..., method="json_schema")` | same | same, per endpoint |
| Reasoning depth control | `reasoning_effort` | `reasoning_effort` | `reasoning_effort` |
| Output cap | `max_tokens` | `max_tokens` | `max_tokens` |

Differences that `models.py` absorbs:

- **Effort vocabulary.** Anthropic accepts `low`/`medium`/`high`/`xhigh`/`max`; OpenAI
  accepts `minimal`/`low`/`medium`/`high`; OpenRouter accepts all six. Set
  `<ROLE>_EFFORT` to any of them — `xhigh`/`max` fold down to `high` for OpenAI and
  `minimal` folds up to `low` for Anthropic, so switching a role's provider never
  fails on the effort value. OpenRouter needs no folding.
- **Endpoint-level capability.** Only OpenRouter has this: structured-output support
  belongs to the routed backend, not the model ID, so `require_parameters` is sent to
  constrain routing.
- **`max_tokens` semantics.** On Claude it caps thinking *plus* visible output; on
  OpenAI reasoning models the reasoning tokens are also billed against the completion
  budget. Either way, budget generously — see
  [configuration.md](configuration.md#token-budgets-and-effort).
- **Import cost.** Provider packages are imported lazily inside `build_llm`, so you
  only need the SDK for the providers you actually use, and importing the graph never
  requires an API key (Studio imports it at startup, before credentials matter).

## Adding another provider

`models.py` is the only file that needs to change:

1. Add the name to `SUPPORTED_PROVIDERS`.
2. Add an entry to `_EFFORT_MAPS` — `{}` if it accepts every level this project allows.
3. Add a branch in `build_llm` that lazily imports the integration and returns the
   chat model. If it's OpenAI-wire-compatible, reuse `ChatOpenAI` with its `base_url`
   the way the OpenRouter branch does.
4. Add a prefix rule to `_infer_provider` if bare-name inference should work.
5. Add the package as an optional extra in `pyproject.toml`.

Nothing in `nodes.py`, `graph.py`, `state.py`, or `config.py` should need touching — if it does,
the abstraction has leaked and that's worth fixing rather than working around.
