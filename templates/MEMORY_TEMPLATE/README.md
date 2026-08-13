# `memory/` — project learning + experience

This directory is the **project-local memory** for <name>. Every significant
decision, experiment outcome, bug fix, piece of user feedback, and sub-agent
dispatch lives here as a markdown file with structured frontmatter.

**Why this exists:** AI agents (orchestration and sub-agents) need to learn
from each project's experience and carry lessons forward. Without explicit
memory, every dispatch starts from scratch — the same mistakes get made
over and over. With this directory, the orchestration bot can cite past
experiments before running a new one, sub-agents can read prior attempts
before they start coding, and lessons that generalize get promoted to the
operator's long-term cross-project memory store.

## Two tiers

| Tier | Lives in | Scope | Who reads |
|---|---|---|---|
| **Project-local** (this dir) | `memory/` committed to git | This project only | The project's bot, sub-agents, humans |
| **Long-term** | Operator's cross-project store (reached via `$MEMORY_STORE_URL`) | Every project on the same operator | All projects' bots + sub-agents via the `read_memory_longterm` tool |

Local memories can be **promoted** to long-term after operator review — see
*Promotion* below.

## Structure

```
memory/
├── README.md              this file
├── SCHEMA.md              frontmatter reference + category conventions
├── decisions/             ADRs — architectural decisions made + why
├── experiments/           autoresearch iteration outcomes (kept & discarded)
├── bugs/                  bugs encountered, root cause, fix
├── feedback/              user feedback, reports, feature requests
└── sub_agent_runs/        outcomes from dispatched coding agents (auto)
```

Each subdirectory has its own `README.md` explaining what belongs there and
a numbered example file.

## Who writes memories

Three sources:

1. **Humans** — just create markdown files with frontmatter in the right
   subdirectory. Or use `make memory-new CATEGORY=decision NAME="foo-vs-bar"`
   which scaffolds a file with the frontmatter pre-filled.
2. **The orchestration bot** — has a `write_memory` tool. When the LLM
   decides something is worth capturing (an experiment taught us something,
   a dispatch uncovered a pattern), it writes to the appropriate category.
3. **Automation** — the autoresearch loop writes `memory/experiments/` on
   every kept iteration. `dispatch_agent.py` writes `memory/sub_agent_runs/`
   after every dispatched agent finishes.

## Who reads memories

**The orchestration bot** reads memories on every mention-handling loop:

- `rag/index.py` indexes `memory/**` alongside code + docs, so `local_rag`
  tool queries automatically surface relevant lessons
- Dedicated `read_memory_local` tool for structured queries (filter by
  category / tags / confidence / outcome)
- Dedicated `read_memory_longterm` tool for cross-project wisdom

**Sub-agents dispatched inside the Docker sandbox** read a **pre-flight brief**:

Before `dispatch_agent.py` runs the sub-agent, the orchestration bot
compiles `memory/_relevant-for-<branch>.md` — a short markdown file listing
the top few relevant memories from both project and long-term stores. The
sandbox has the project mounted, so the sub-agent's runner reads this file
as its first step and bakes the lessons into its planning.

## Frontmatter schema

Every memory file starts with YAML frontmatter. See `SCHEMA.md` for the
complete reference. Minimum required fields:

```markdown
---
name: Short descriptive title
id: 0042                        # auto-incremented per category
type: decision | experiment | bug | feedback | sub_agent_run
date: 2026-04-10
project: <name>
shape: service
lang: python
tags: [fastify, http, auth]
confidence: high | medium | low
outcome: success | failure | neutral | abandoned
promote: yes | no | pending
---

# Body

Structured markdown — see the subdirectory README for the suggested sections.
```

## Promotion — project → long-term

Not every local memory generalizes. Some contain project-specific names,
some are one-off, some are wrong. **Promotion requires operator review.**

**Flow:**

1. Bot writes a memory with `promote: pending` if it thinks the lesson
   generalizes beyond this project.
2. `make memory-promote-list` shows all pending memories.
3. Operator reviews, edits the file to `promote: yes`, strips
   project-specific details from the body, sets `confidence:` honestly.
4. `make memory-promote` POSTs approved memories to `$MEMORY_STORE_URL/submit`.
5. Long-term store indexes into appropriate remote collections:
   `agent_learnings_common`, `agent_learnings_shape_<shape>`,
   `agent_learnings_lang_<lang>`, `agent_learnings_category_<category>`.

Bad lessons that made it in can be unpromoted later — every promoted memory
carries provenance metadata tying it back to the project + commit + date it
came from.

## Writing a good memory

A good memory answers these questions:

1. **Context** — what was happening? What triggered this?
2. **What we tried** — one or more approaches, with enough detail to
   reproduce.
3. **What worked / didn't** — per approach. Include numbers if applicable.
4. **Lesson** — the one sentence a future agent needs. If the lesson is
   project-specific, mark `promote: no`. If it generalizes, mark
   `promote: pending`.
5. **For future agents** — actionable: "when you see X, do Y, not Z".

Short is fine. A one-paragraph memory is better than a 10-page essay no
one reads. Aim for 200-600 words in the body.

## What NOT to put here

- **Not a task list** — use `STRATEGY.md` or issue tracker for todos.
- **Not code** — memory is prose about code, not the code itself.
- **Not secrets** — no API keys, passwords, private URLs. `.gitleaks.toml`
  scans this directory.
- **Not stale docs** — don't move `docs/API.md` content here. Memory is
  about *lessons*, not reference material.
- **Not session logs** — if the bot writes "I just answered Q about X",
  that's a perf log, not a memory.

Memory should be the stuff you'd want a new team member — or a new agent
run — to read before they start.

## Commands

```bash
# Create a new memory file with frontmatter pre-filled
make memory-new CATEGORY=decision NAME="fastify-vs-express"

# List all memories pending promotion
make memory-promote-list

# Promote approved memories to long-term store (after operator review)
make memory-promote

# Index memories into the RAG (automatic on make reindex)
make reindex
```

## See also

- `SCHEMA.md` — full frontmatter reference
- `decisions/README.md`, `experiments/README.md`, etc. — per-category conventions
- `AGENTS.md §23` — memory + learning conventions across all scaffolded projects
- `bot/tools/write_memory.py`, `read_memory_local.py`, `read_memory_longterm.py` — bot tools
- `bot/tools/dispatch_agent.py` — pre/post-flight memory integration for sub-agents
