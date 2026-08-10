# Memory frontmatter schema

Every file under `memory/**/*.md` (except `README.md` / `SCHEMA.md`) has
YAML frontmatter with these fields.

## Required fields

| Field | Type | Purpose |
|---|---|---|
| `name` | string | Short descriptive title (≤80 chars). Used in indexes and search. |
| `id` | 4-digit string | Auto-incremented per-category. `0001`, `0002`, ... |
| `type` | enum | `decision` \| `experiment` \| `bug` \| `feedback` \| `sub_agent_run` \| `pr_review` \| `pipeline_failure` |
| `date` | YYYY-MM-DD | When the memory was written (the *lesson* date, not the event date). |
| `project` | string | Project slug this memory came from. Filled by `write_memory` tool. |
| `confidence` | enum | `high` \| `medium` \| `low` — how sure the author is this lesson generalizes. |
| `outcome` | enum | `success` \| `failure` \| `neutral` \| `abandoned` |

## Optional (but recommended) fields

| Field | Type | Purpose |
|---|---|---|
| `shape` | string | Project shape (`service`, `backtest`, `report`, ...). Used by long-term filter. |
| `lang` | string | `python` \| `node` \| `other`. Used by long-term filter. |
| `tags` | list[string] | Free-form keywords for discovery. 3-8 tags is ideal. |
| `promote` | enum | `yes` \| `no` \| `pending` — controls whether this memory is eligible for long-term promotion. |
| `references` | list[object] | Pointers to commits, branches, issues, PRs, KPIs, or other memories. |
| `related_memories` | list[string] | Cross-refs to other memory IDs: `["experiments/0007", "bugs/0012"]`. |
| `author` | string | `bot` \| `human:<nickname>` \| `subagent:<runner>`. |
| `agent_task` | string | For sub_agent_runs: the task the sub-agent was dispatched with. |
| `agent_branch` | string | For sub_agent_runs: the branch the sub-agent worked on. |

## References format

```yaml
references:
  - type: commit
    ref: abc1234
  - type: branch
    ref: bot/fix-race-123
  - type: issue
    ref: "#42"
  - type: pr
    ref: "#57"
  - type: kpi
    ref: win_rate
  - type: url
    ref: https://example.com/postmortem
```

## Confidence field — be honest

- **`high`** — reproduced multiple times or demonstrates something
  fundamental. Safe to promote to long-term. Future agents should treat
  this as a strong prior.
- **`medium`** — worked once, in this context. Might generalize. Mark
  `promote: pending` so operator can decide.
- **`low`** — worked on a hunch, or result depended on conditions we
  don't fully understand. Keep local (`promote: no`) unless reviewing
  agent confirms it later.

Bad memory calibration poisons the long-term store — over-confident `high`
memories become gospel that breaks future projects. When in doubt, mark
`medium` or `low`.

## Outcome field

- **`success`** — the approach worked.
- **`failure`** — the approach didn't work. (**These are often the most
  valuable memories.** Future agents learn what NOT to try.)
- **`neutral`** — neither clearly succeeded nor failed. Usually an
  observation or a decision whose effects aren't measurable yet.
- **`abandoned`** — never finished. Capture why it was dropped — that's
  the lesson.

## Promote field

- **`no`** (default) — stay project-local. Too project-specific, or too
  uncertain, or contains names/URLs that shouldn't leak.
- **`pending`** — bot/human thinks this might generalize. Waits for
  operator review before being pushed to long-term.
- **`yes`** — operator reviewed and approved. On next `make memory-promote`,
  gets submitted to `$MEMORY_STORE_URL/submit`.

## Example — a decision memory

```markdown
---
name: Use SQLite FTS5 for RAG instead of chromadb
id: "0003"
type: decision
date: 2026-04-10
project: rsi-backtest
shape: backtest
lang: python
tags: [rag, sqlite, dependencies, portability]
confidence: high
outcome: success
promote: pending
references:
  - type: commit
    ref: a1b2c3d
author: bot
---

## Context

Needed project-local RAG for the bot to answer questions about this
backtest's code + strategy config + prior experiment outcomes.

## What we tried

1. chromadb in local mode — worked but added a 400MB Docker layer
2. SQLite FTS5 — keyword-only but ships with Python stdlib

## What worked

SQLite FTS5 indexed 33 files in 18ms, zero dependencies, fits inside the
bot's 256m memory budget.

## Lesson

For project-local RAG where the corpus is <1000 files and queries are
keyword-shaped, SQLite FTS5 is strictly better than chromadb. Semantic
search isn't worth the dependency weight at this scale.

## For future agents

Default RAG backend for new scaffolds should be `sqlite`, not `remote`
or chromadb. Operators who want semantic search across projects should
use the operator-side shared remote, not per-project embeddings.
```

## Example — a failed experiment memory

```markdown
---
name: SMA 50/200 crossover lost to buy-and-hold over 10 years
id: "0012"
type: experiment
date: 2026-04-11
project: rsi-backtest
shape: backtest
lang: python
tags: [sma, crossover, baseline, s&p]
confidence: high
outcome: failure
promote: pending
references:
  - type: kpi
    ref: total_return_pct
  - type: branch
    ref: experiments/sma-crossover
author: bot
---

## Context

Autoresearch iteration of the sma_crossover strategy with short_window=50,
long_window=200 against S&P500 constituents, 2014-2023.

## Results

| Metric | SMA crossover | Buy-and-hold |
|---|---|---|
| total_return_pct | +8.3% | +12.1% |
| win_rate | 0.42 | 1.0 |
| max_drawdown_pct | -0.31 | -0.34 |
| sharpe | 0.21 | 0.51 |

## Lesson

SMA 50/200 crossover underperforms buy-and-hold on large-cap US equities
over multi-year horizons. Any future "trend following" strategy that can't
beat this baseline isn't worth investigating.

## For future agents

Before spending compute on any crossover-family strategy, verify it beats
buy-and-hold on the same fixture window. If it doesn't, stop and try a
different strategy family.
```

## File naming

Category subdirectories enforce a numbered naming scheme:

- `decisions/0001-fastify-vs-express.md`
- `experiments/0003-sma-crossover-baseline.md`
- `bugs/0007-race-in-worker-pull-batch.md`
- `feedback/0002-user-report-pdf-font.md`
- `sub_agent_runs/bot_fix-off-by-one-1775000000.md`

The `write_memory` tool auto-increments the numeric prefix. Use
`make memory-new CATEGORY=... NAME=...` to create a new file with the
correct number + frontmatter pre-filled.

## Lint

The `scripts/check_memory.py` tool (ships with the project) validates:

- All memory files have required frontmatter fields
- `type` matches the containing directory
- `confidence` and `outcome` values are valid
- `references` are well-formed
- No duplicate IDs in the same category
- No broken `related_memories` cross-refs

Runs in the bot's lint stage and can be invoked via `make memory-lint`.
