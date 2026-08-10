# `memory/pr_reviews/` — audit trail of automated PR reviews

**Auto-populated** by `bot/tools/review_pr.py`. Every time the review agent
(or a human on-demand) reviews a PR on this project's Gitea instance, the
outcome lands here as a memory file.

## What's captured

Each file records:

- **PR number + URL** — link to the Gitea PR
- **Source task** — if the PR was opened by `dispatch_agent`, the original
  task prompt pulled from `memory/sub_agent_runs/`
- **Files changed** — list with `+/-` line counts
- **Verdict** — `merge` | `request_changes` | `reject`
- **Confidence** — `high` | `medium` | `low`
- **Rationale** — the LLM's reasoning for the verdict, cited against
  specific files and AGENTS.md sections
- **Feedback** — (for request_changes / reject) actionable items the author
  should address

## Why capture this

The review agent is making decisions that affect the repo. Every decision
needs to be auditable so:

1. Humans can see what the agent merged and reject its judgment if it was
   wrong.
2. Patterns in agent reviews can be learned — "this reviewer always flags
   missing tests" is itself a lesson worth promoting.
3. Bad reviewer behavior can be traced and unwound.

## Promotion

PR review memories are **not** prime long-term promotion candidates by
default (`promote: no` for low/medium confidence reviews, `promote: pending`
for high-confidence reviews that had clear rationale).

What IS worth promoting from this category:

- Patterns of "what kinds of PRs the agent mis-reviewed" (operator
  post-hoc analysis)
- Recurring rule violations that indicate a training-set gap
- Review-prompt improvements discovered empirically

These patterns should be captured as `decisions/` or `experiments/`
memories, NOT as direct promotions of `pr_reviews/` entries.

## File naming

`<4-digit-id>-<pr-number>-<slug>.md`, e.g. `0001-42-fix-off-by-one.md`.

## Structure

```markdown
---
name: PR #42 review — fix off-by-one in backtest.py
id: "0001"
type: pr_review
date: 2026-04-11
project: rsi-backtest
shape: backtest
lang: python
tags: [pr-review, merge, high]
confidence: high
outcome: success
promote: pending
author: bot
pr_number: 42
pr_url: http://127.0.0.1:3030/rsi-backtest-bot/rsi-backtest/pulls/42
source_memory: memory/sub_agent_runs/0042-cursor-fix-off-by-one.md
---

## Task
(from sub_agent_run)

## Files changed (2)
- `backtest.py` (+8/-3)
- `tests/test_backtest.py` (+15/-0)

## Verdict: merge (high)

### Rationale
- Diff is tightly scoped to backtest.py::run_strategy
- Fix addresses the off-by-one identified in the task
- New test covers the edge case
- No out-of-scope changes
- AGENTS.md §6 satisfied (tests exist)
- AGENTS.md §7 not triggered (no user-visible behavior change)

### Feedback
(empty — approved)
```

## Interaction with dispatch_agent

When `dispatch_agent.py` opens a PR with `GITEA_AUTO_REVIEW=true`, it
immediately calls `review_pr(pr_number)`, which writes an entry here. The
dispatch summary posted to IRC includes the verdict.

When `GITEA_AUTO_REVIEW=false` (the default), PRs sit in Gitea until a
human runs `make review PR=<n>` or asks the bot `@bot: review PR 42`.
