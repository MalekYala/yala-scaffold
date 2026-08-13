# `memory/sub_agent_runs/` — outcomes from dispatched coding agents

**Auto-populated** by `bot/tools/dispatch_agent.py`. When the orchestration
bot dispatches a sub-agent (Cursor, Claude Code, Aider, custom) via the
sandboxed runner, the outcome is captured here as a memory file.

These memories are the feedback loop that makes agent dispatch smarter over
time. Before running a new dispatch, the bot queries this directory (via
`read_memory_local`) for similar past tasks so the LLM can use prior
experience when composing the task prompt and picking a runner.

## What's captured

Each file records:

- **Task** — the prompt that was dispatched
- **Runner** — which coding agent was used (cursor, claude_code, aider, custom)
- **Branch** — the throwaway git branch name
- **Sandbox** — docker / none, image, network, resource caps
- **Duration** — wall-clock time from dispatch to completion/timeout
- **Outcome** — success / failure / timeout / refused
- **Diff stats** — files changed, lines added, lines removed
- **Log path** — pointer to `logs/agent-<branch>.log` for full detail
- **Lesson** — (written by the bot after reviewing the run) what this
  dispatch taught us about how to frame similar tasks in the future

## Promotion

Sub-agent run outcomes are **prime candidates for long-term promotion**
because agent dispatch patterns are the most cross-project-transferable
knowledge we capture. Lessons like "for task X, runner Y with prompt
structure Z works best" apply across any project.

The bot marks high-signal runs as `promote: pending` automatically. Low-
signal runs (trivial tasks, repeated failures of the same pattern) stay
local with `promote: no`.

## File naming

`<runner>_<branch-slug>-<timestamp>.md`, e.g.
`cursor_fix-off-by-one-1775000000.md`.

## Structure

```markdown
---
name: cursor fixed off-by-one in backtest.py
id: "0042"
type: sub_agent_run
date: 2026-04-10
project: rsi-backtest
shape: backtest
lang: python
tags: [cursor, bugfix, indexing]
confidence: medium
outcome: success
promote: pending
references:
  - type: branch
    ref: bot/fix-off-by-one-1775000000
  - type: commit
    ref: a1b2c3d
author: bot
agent_task: "Fix the off-by-one in backtest.py::run_strategy that drops the last trade"
agent_branch: bot/fix-off-by-one-1775000000
---

## Task
(verbatim task prompt)

## Runner
cursor (./bot/runners/cursor.sh) — sandbox=docker, network=none, cpus=2, memory=2g

## Result
- Duration: 127s
- Diff: 2 files changed, 5 insertions(+), 3 deletions(-)
- Outcome: success

## What the agent did right
- Found the off-by-one on the first read of the file
- Wrote a test that would have caught the bug

## What the agent did wrong
- Modified an unrelated import (cosmetic, reverted in review)

## Lesson
For "fix a bug in <file>" tasks, Cursor performs well when the task
description cites the exact file + function. Less successful when only
the symptom is given.

## For future agents
When dispatching a "fix bug" task: always include the file + function
path in the task prompt. Avoid vague symptoms alone.
```

## Pre-flight integration

Before dispatching a new sub-agent, the bot compiles
`memory/_relevant-for-<new-branch>.md` by querying this directory for
similar past runs (same tag overlap, same runner, same confidence) plus
matching memories from the long-term store. The sub-agent reads this file
as its first step inside the sandbox.
