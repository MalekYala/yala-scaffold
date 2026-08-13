# `memory/experiments/` — experiment results

Outcomes of **things we tried**. These are especially valuable because
they capture what DIDN'T work, which is information you can't derive from
the current state of the code.

## Who writes these

- **The autoresearch loop** writes one per kept iteration automatically.
  When an iteration improves the metric, the runner captures the change
  and the result here.
- **The orchestration bot** writes one when an experiment is discussed
  in-channel and the outcome is informative.
- **Humans** write one when running an experiment manually.

## When to write

- Every autoresearch iteration that changed the metric meaningfully
  (kept AND discarded — failures are valuable data)
- A/B comparisons of approaches
- Benchmarks showing unexpected results
- Proof-of-concept outcomes

## Suggested body structure

```markdown
## Hypothesis
What you expected to happen.

## Setup
How the experiment was run. Include enough detail to reproduce:
parameters, fixture data, seed, branch name.

## Results
Numbers. Tables. Charts (link to artifact in `outputs/`).

## Conclusion
What the results actually showed. Was the hypothesis confirmed?

## Lesson
The one-sentence takeaway for future agents.
```

## Example

See `0000-example-experiment.md` for the template.

## Naming

`<4-digit-id>-<short-slug>.md`, e.g. `0003-sma-crossover-baseline.md`.

## Interaction with autoresearch

The autoresearch runner (see `AUTORESEARCH.md`) writes one memory per
kept iteration automatically. Its entries have:

- `author: autoresearch`
- `outcome: success` (kept iterations) or `outcome: failure` (discarded)
- `references.kpi: <metric-name>`
- `references.branch: experiments/<iteration>`
- The body includes the before/after metric values and the code diff summary.
