# Architecture comparison experiments

The web UI separates a **run** from an **experiment**. A run executes one selected
workflow. An experiment freezes one problem, round limit, and credential-free model
configuration, then executes V1, V2, and V3 sequentially.

## Run a comparison

Start the web app and open **New Experiment**. Enter the problem once, choose the
round limit, and optionally enter one evaluation criterion per line. The criteria
are normalized to stable IDs (`C1`, `C2`, …), frozen with the experiment, and never
shown to the three workflows. The page reports each architecture as waiting,
running, complete, or failed.

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

## Evaluate quality

When criteria exist and all three workflows have completed, the comparison page
offers **Evaluate outputs**. The evaluator receives three separate requests. Each
contains only the original problem, frozen rubric, and one anonymized final answer;
it never sees the architecture, transcript, internal score, cost, or competing
answers.

Each criterion is marked `satisfied`, `partial`, or `violated`, with evidence and an
explanation. Coverage is deterministic (`1`, `0.5`, and `0` respectively), and an
answer passes only when every criterion is satisfied. Successful evaluations are
preserved if another call fails, and the retry action evaluates only missing or
failed outputs. Evaluator usage and cost are displayed separately and never added to
workflow cost.

Existing History rows are not inferred into experiments by matching problem text.
Standalone runs remain standalone because similar text does not prove controlled
settings.
