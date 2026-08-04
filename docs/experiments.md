# Architecture comparison experiments

The web UI separates a **run** from an **experiment**. A run executes one selected
workflow. An experiment freezes one problem, round limit, and credential-free model
configuration, then executes V1, V2, and V3 sequentially.

## Run a comparison

Start the web app and open **New Experiment**. Enter the problem once and choose the
round limit. The page shows the moderator, author, and reviewer settings that will be
saved with the experiment, then reports each architecture as waiting, running,
complete, or failed.

Experiments continue after an individual failure. Successful runs are preserved and
a failed architecture can be retried from the comparison page using the original
saved settings.

## Read the result

**Experiments** contains one row per problem comparison. Each V1/V2/V3 cell summarizes
verdict, provider-reported cost, tokens, and duration. The detail page compares:

- verdict and revision rounds;
- model calls, tokens, cost, and duration;
- the three final responses side by side;
- a link to each full run replay.

Provider cost is never guessed. If any completed run lacks provider-reported cost,
the experiment total is unavailable rather than a misleading partial sum.

## Evaluation boundary

Operational comparison is implemented; output-quality judging is intentionally not.
Every report therefore says **Evaluation: Not evaluated**. A later independent
rubric-based evaluator can attach quality results without confusing a workflow's own
review score with a shared cross-architecture metric.

Existing History rows are not inferred into experiments by matching problem text.
Standalone runs remain standalone because similar text does not prove controlled
settings.
