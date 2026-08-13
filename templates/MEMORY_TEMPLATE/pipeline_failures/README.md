# `memory/pipeline_failures/` — CI pipeline failure audit trail

**Auto-populated** by `bot/tools/watch_pipeline.py`. Every time a
Gitea Actions pipeline fails on a PR, the bot captures a structured
entry here containing:

- The failed job(s) — workflow, step, conclusion
- A heuristic **classification**: `lint` | `test` | `build` |
  `dependency` | `runtime` | `unknown`
- The log tail (last ~40 lines around the failure)
- Any resolution that followed (auto-fix dispatch branch that made
  it pass, or a human commit)
- A **Lesson** section (human-editable) capturing what this failure
  pattern teaches

## Why this matters

Pipeline failures are a feedback signal. Without capturing them:

- The same class of failure repeats across projects
- Auto-fix dispatches re-discover the same fix every time
- The reviewer can't learn which jobs are flaky vs. genuinely broken

With this memory in place, the orchestration bot can:

- Query `read_memory_local` for "have we seen this failure pattern
  before" when a new pipeline fails
- Feed prior fix patterns to the auto-fix dispatch's pre-flight brief
  so sub-agents know what worked last time
- Promote cross-project lessons ("ruff rule E501 trips cursor runners
  80% of the time in python projects") to the long-term store

## Auto-fix loop integration

When `dispatch_agent.py` opens a PR and the pipeline fails:

1. `watch_pipeline.py` writes an entry here with classification + log tail
2. `dispatch_agent.py` checks the circuit breaker
   (`fix_attempts` in the root sub_agent_run memory)
3. If under `AUTOFIX_MAX_ATTEMPTS` (default 3), a new sub-agent is
   dispatched with the failure context as its task
4. The fix dispatch's post-flight opens another PR and watches that
   pipeline too
5. If the fix PR's pipeline passes, the review agent takes over
6. If the fix PR's pipeline ALSO fails, recurse — but the attempt
   counter increments each time
7. After N failed attempts, the bot stops auto-fixing and posts to
   IRC for human intervention

## Entry structure

```markdown
---
name: PR #42 pipeline failure — test in run-backtest
id: "0005"
type: pipeline_failure
date: 2026-04-12
project: rsi-backtest
shape: backtest
lang: python
tags: [pipeline, test, ci]
confidence: medium
outcome: failure
promote: pending
author: bot
pr_number: 42
pr_url: http://127.0.0.1:3030/rsi-backtest-bot/rsi-backtest/pulls/42
classification: test
elapsed_s: 180
---

## Failed jobs (1)

- `run-backtest` in workflow `rsi-backtest CI (backtest, python)`
  (run 17, conclusion failure)

## Classification: **test**

## Log tail

```
FAILED tests/test_strategy.py::test_sma_crossover_edge - AssertionError
1 failed, 14 passed in 3.2s
```

## Resolution

(filled in if auto-fix succeeded — e.g. "fixed by branch bot/fix-off-by-one-17...")

## Lesson

(edit: what pattern does this failure teach?)
```

## Promotion policy

Pipeline failures are **prime long-term promotion candidates** because
CI patterns transfer directly across projects — "pytest import error
means your requirements.txt is out of sync with your test file" is
universal. The bot marks high-confidence failures as `promote: pending`
automatically; the operator reviews and promotes via `make memory-promote`.

## File naming

`<4-digit-id>-<pr-number>-<classification>-<slug>.md`, e.g.
`0005-42-test-run-backtest.md`.
