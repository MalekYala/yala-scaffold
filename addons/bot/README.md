# Project bot — IRC-driven coding agent

Internal tool for AI-assisted project development. An IRC bot backed by an
LLM tool-calling loop scaffolds code, dispatches coding agents, manages PRs,
and tracks project memory — all on feature branches. **The final master branch
ships clean with no evidence of this tooling.** Whether the output is a private
company repo or a public open-source project, the end result looks hand-built.

---

## Quick Start: Scaffold to First PR

This walkthrough takes you from zero to a working bot that dispatches coding
agents and opens PRs in under 10 minutes.

### Prerequisites

| Dependency | Purpose | Required? |
|---|---|---|
| Docker + Compose v2 | Runs all containers | yes |
| An IRC server | Where you talk to the bot | yes |
| An OpenAI-compatible LLM endpoint | The bot's reasoning — Ollama, vLLM, OpenAI, anything | yes |
| The Gitea add-on (`--with-gitea`) | Somewhere for dispatched agents to open PRs | for the PR tools |
| The RAG add-on (`--with-rag`) | Lets the bot answer questions about this project | for `local_rag` |

Neither add-on is required to run the bot. Without them the matching tools are
skipped with a message saying so, rather than being offered to the model and
failing when it calls them.

### Step 1: Scaffold a new project

The bot is an add-on, so ask for it explicitly. Gitea gives the bot somewhere
to open PRs, and RAG lets it answer questions about the project:

```bash
./yala.sh my-project --type service --with-bot --with-gitea --with-rag
```

The project is created in the current directory. Every add-on is optional and
independent — `--with-bot` alone gives you a working bot with fewer tools.

### Step 2: Configure `.env`

```bash
cd my-project
cp .env.example .env
```

Fill in the required values:

```bash
# IRC — the server the bot joins. Any IRC server will do; ergo is a
# lightweight one to self-host if you do not already run one.
IRC_SERVER=irc.example.invalid       # hostname or container name
IRC_PORT=6667
IRC_NICK=my-project-bot
IRC_CHANNEL=#my-project

# LLM — any OpenAI-compatible endpoint
LLM_ROUTER_URL=http://127.0.0.1:11434/v1    # Ollama, vLLM, OpenAI, anything
LLM_MODEL=gpt-4o-mini                        # or qwen3-coder:latest, etc.
LLM_API_KEY=                                 # leave empty for local models
```

Then check what the bot can actually do with that configuration, before
starting anything:

```bash
make bot-check
```

It reports which tools loaded, which were skipped and why, and whether IRC and
the LLM endpoint are set. It makes no network calls, so it costs nothing and
works offline.

### Step 3: Start Gitea

Each project gets its own Gitea instance for isolated PR workflows.

```bash
make gitea               # start the Gitea container
make gitea-bootstrap     # create bot user, token, and repo (idempotent)
```

Gitea is now running at `http://127.0.0.1:<GITEA_HTTP_PORT>` (default 3030).
Repositories are private by default and the web UI requires authentication.
Use the bot credentials written to `.env` by `make gitea-bootstrap`.

### Step 4: Expose Gitea via Caddy (optional)

Add a block to your Caddy reverse proxy:

```
my-project-git.example.local {
    tls internal
    reverse_proxy 127.0.0.1:3030
}
```

Restart Caddy to generate the TLS cert:

```bash
docker compose -f ~/caddy-proxy/docker-compose.yml restart caddy
```

### Step 5: Start the bot

```bash
make bot          # starts the bot container and verifies it stays up
make bot-logs     # follow logs (confirm "joined #my-project")
```

`make bot` refuses to start when `IRC_SERVER` is unset, and after starting it
confirms the container is still running with no restarts — printing the last
log lines if not. A bot that dies immediately and is restarted forever used to
report itself as started; it no longer does.

### Step 6: Dispatch work via IRC

In your IRC client, mention the bot in `#my-project`:

```
my-project-bot: dispatch_agent add a /health endpoint that returns JSON status
```

The bot will:
1. Create a `bot/<slug>` branch
2. Launch a sandboxed coding agent
3. Post the branch name when done
4. Open a PR in Gitea

### Step 7: Review and merge

```bash
make prs                 # list open PRs
make review PR=1         # trigger the automated review agent
```

Or review in the Gitea web UI and merge manually.

### Step 8: Ship the project

When the MVP is ready, strip all bot artifacts before the repo goes public.
See the [Shipping a Project](#shipping-a-project) section below.

---

## Architecture

```
     IRC channel #<name>
              |
     +--------v--------+
     |   <name>-bot    |  <-- watches logs/, results/metrics.json, outputs/manifest.json
     |   (bot.py)      |  <-- project context: STRATEGY.md, README.md, AGENTS.md
     +--------+--------+
              | tool-calling loop (max 6 iterations)
              | (OpenAI-compatible LLM)
              |
   +----------+----------+----------+
   |          |          |          |
   v          v          v          v
 Search &   Memory    Code       PR
 Knowledge            Dispatch   Workflow
```

### How it works

1. Bot connects to the operator's IRC server, joins `#<name>`.
2. Bot reads `STRATEGY.md`, `README.md`, `AGENTS.md`, `results/metrics.json`
   into its system prompt as compact project context.
3. Bot watches `logs/`, `results/metrics.json`, `outputs/manifest.json` and
   posts updates to the channel when they change.
4. On mention (`<name>-bot: how's the win rate?`) the bot runs a
   **tool-calling loop**: the LLM picks a tool, the bot executes it, feeds
   the result back, and iterates (up to 6 rounds) until the LLM produces a
   final answer.
5. Answer is posted to IRC.
6. A **5-second replay guard** on connect prevents the bot from re-processing
   IRC history messages after a restart (which could re-dispatch expensive
   workflows).

### Key files

| File | Purpose |
|---|---|
| `bot/bot.py` | IRC client, LLM tool loop, message handler, heartbeat |
| `bot/config.yml` | Tool inventory, IRC config, LLM settings, agent dispatch config |
| `bot/tools/*.py` | Individual tool modules (one file per tool) |
| `bot/runners/*.sh` | Agent runner scripts (Cursor, Claude Code, Aider, custom) |
| `bot/docker-compose.bot.yml` | Compose overlay to run the bot alongside the main project |
| `bot/Dockerfile` | Bot container image |

---

## Configuration

### config.yml

The bot's behavior is defined in `bot/config.yml`. Environment variables are
interpolated as `${VAR}` or `${VAR:-default}`.

Key sections:
- **`identity`** — bot name, role description (becomes the LLM system prompt)
- **`irc`** — server, port, TLS, nick, channel, peer channels
- **`llm`** — endpoint URL, model, temperature, max_iterations, timeout
- **`tools`** — list of tools with module path, description, and required env vars
- **`watch`** — files to monitor and announce changes for
- **`agent_dispatch`** — sandbox config, concurrency limits, timeouts

### .env Reference

**Required:**

| Variable | Purpose | Example |
|---|---|---|
| `IRC_SERVER` | IRC server hostname | `irc-server` |
| `IRC_PORT` | IRC server port | `6667` |
| `LLM_ROUTER_URL` | OpenAI-compatible LLM endpoint | `http://llm-router:11436/v1` |
| `LLM_MODEL` | Model identifier | `gpt-4o-mini` |

**Optional (enable additional tools):**

| Variable | Enables | Default |
|---|---|---|
| `IRC_NICK` | Custom bot nick | `<name>-bot` |
| `IRC_CHANNEL` | Custom channel | `#<name>` |
| `IRC_TLS` | TLS connection | `false` |
| `LLM_API_KEY` | API key for cloud LLMs | (empty) |
| `AGENT_COMMAND` | `dispatch_agent` tool | (skipped) |
| `AGENT_SANDBOX` | Sandbox mode | `docker` |
| `AGENT_SANDBOX_IMAGE` | Docker image for sandbox | (required if sandbox=docker) |
| `AGENT_SANDBOX_NETWORK` | Sandbox network mode | `none` |
| `AGENT_SANDBOX_CPUS` | CPU limit for sandbox | `2` |
| `AGENT_SANDBOX_MEMORY` | Memory limit for sandbox | `2g` |
| `AGENT_SANDBOX_FORWARD_ENV` | Env vars forwarded to sandbox | `OPENAI_API_KEY,ANTHROPIC_API_KEY,...` |
| `AGENT_MAX_CONCURRENT` | Max parallel agents | `3` |
| `AGENT_TIMEOUT_S` | Agent timeout | `1800` |
| `GITEA_URL` | `gitea`, `review_pr`, `watch_pipeline` tools | (skipped) |
| `GITEA_TOKEN` | Gitea API token | (skipped) |

Tools with unsatisfied `requires_env` in `config.yml` are **skipped at startup
with a warning** — missing infrastructure degrades gracefully.

### LLM Backend

The bot works with any OpenAI-compatible `/v1/chat/completions` endpoint:

| Backend | `LLM_ROUTER_URL` | Notes |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | Set `LLM_API_KEY`. Fast, ~$0.01/query. |
| Ollama | `http://ollama:11434/v1` | Free, local. Set `timeout_s: 180` for cold starts. |
| vLLM | `http://vllm:8000/v1` | GPU-accelerated local serving. |
| llm-router | `http://llm-router:11436/v1` | Operator's routing proxy (tries local first, falls back to cloud). |

---

## Tools

Each file in `tools/` is an independent module with a `call(query, ctx)`
function. The bot loads them at startup based on `config.yml`.

For detailed query formats, examples, and error modes for each tool, see the
**module docstring** in `tools/<name>.py`.

### Tool Summary

A tool is offered to the model only when everything it needs is present. When
it is not, the bot says so at startup and the model is never told the tool
exists — an advertised tool that cannot work costs a turn and produces a
confusing failure mid-conversation.

| Tool | Category | Purpose | Needs |
|---|---|---|---|
| `local_rag` | Search | Full-text or semantic search over this project's code, docs and strategy | `--with-rag` |
| `write_memory` | Memory | Persist a learning to `memory/<category>/` | — |
| `read_memory_local` | Memory | Search this project's memory directory | — |
| `dispatch_agent` | Dispatch | Spawn sandboxed coding agents (Cursor/Claude/Aider) | `AGENT_COMMAND` |
| `gitea` | PR | List/open/merge/close PRs, post comments | `--with-gitea` + `GITEA_URL`, `GITEA_TOKEN` |
| `review_pr` | PR | LLM-based PR review with pipeline and test-quality checks | `--with-gitea` + `GITEA_URL`, `GITEA_TOKEN`, `LLM_ROUTER_URL` |
| `watch_pipeline` | PR | Wait for a Gitea Actions pipeline, classify failures | `--with-gitea` + `GITEA_URL`, `GITEA_TOKEN` |
| `test_quality` | PR | Static analysis of test meaningfulness (0.0–1.0 score) | — |

The Gitea variables are written by `make gitea-bootstrap`; you do not set them
by hand.

**Adding your own tools is the expected path** — these eight are a working
base, not the intended ceiling. See [Adding Custom Tools](#adding-custom-tools).

### When the bot reaches for what

- `local_rag` — first stop for "how does X work in this project?"
- `read_memory_local` — before repeating an experiment or dispatching an agent,
  to check whether this was already tried and what happened
- `write_memory` — after an outcome worth not rediscovering: an experiment
  result, a bug's cause, a decision and its reasoning
- `dispatch_agent` — hand a single scoped task to a sandboxed coding agent,
  which returns a branch and a PR
- `watch_pipeline` — wait for CI on that PR, classify any failure, and record it
- `test_quality` — score how meaningful the tests are, not just whether they
  pass; `review_pr` blocks a merge below 0.8
- `review_pr` — the full review: pipeline state, test quality, an LLM read of
  the diff, and a check against project memory

---

## Agent Dispatch & Sandbox Isolation

When the LLM decides a task needs code changes, it calls `dispatch_agent`.
The tool:

1. Creates a throwaway git branch (`bot/<slug>`) on the host
2. **Launches a hard-isolated Docker sandbox** — only the project root
   mounted, `--network=none`, `--read-only` rootfs, cpu/memory capped,
   env var whitelist applied
3. Runs `$AGENT_COMMAND` inside the sandbox
4. Caps concurrency at `$AGENT_MAX_CONCURRENT` (default 3)
5. Times out after `$AGENT_TIMEOUT_S` (default 1800s)
6. Captures stdout/stderr to `logs/agent-<branch>.log`
7. Opens a PR in Gitea with the diff
8. **Never auto-merges** — humans always review

Example runners are in `bot/runners/`:
- `runners/cursor.sh` — Cursor CLI
- `runners/claude_code.sh` — Claude Code CLI
- `runners/aider.sh` — Aider
- `runners/custom.sh` — template for rolling your own

### Sandbox constraints

| Constraint | How |
|---|---|
| Filesystem | Only `<project-root>:/workspace` mounted. No host files, no sibling projects, no `$HOME`. |
| Network | `--network=none` by default. Zero outbound access. |
| Rootfs | `--read-only` with `/tmp` and `/workspace/.agent-home` as tmpfs. |
| Capabilities | `--cap-drop=ALL` + `--security-opt=no-new-privileges`. |
| Resources | `--cpus=2`, `--memory=2g`, `--pids-limit=256` (all overridable). |
| Env vars | Only `AGENT_SANDBOX_FORWARD_ENV` whitelist is forwarded — operator secrets are stripped. |
| Git | The host creates the branch; the sandbox inherits the checkout via the mount. |

### Building a sandbox image

```bash
cat > sandbox.Dockerfile <<'EOF'
FROM alpine:latest
RUN apk add --no-cache git bash curl
# Install the coding agent CLI your runner calls:
# RUN curl -L ... -o /usr/local/bin/cursor-agent && chmod +x /usr/local/bin/cursor-agent
EOF
docker build -f sandbox.Dockerfile -t agent-sandbox-cursor:latest .
```

Then in `.env`:

```bash
AGENT_SANDBOX=docker
AGENT_SANDBOX_IMAGE=agent-sandbox-cursor:latest
```

### Escape hatch: `AGENT_SANDBOX=none`

For local development only. Runs the runner directly on the host. **Never
use in production** — you lose all isolation guarantees.

### Brokering pattern

If a sub-agent needs something outside the project (an API, a database, another
project's code):

1. The sub-agent writes a `REQUEST.json` in the workspace describing what it needs
2. The orchestration bot (running outside the sandbox) sees the request
3. The bot fulfills it using its own tools — the bot is the policy enforcement point
4. The bot writes the result back and the sub-agent continues
5. The request + result are logged in IRC for audit

Sub-agents never hold operator credentials. The bot holds them; sub-agents
see only the result.

---

## Memory System

The bot maintains a `memory/` directory of persistent learnings organized by
category. This survives bot restarts and prevents the bot from repeating
mistakes across iterations.

### Structure

```
memory/
  decisions/          # architecture choices, trade-off rationale
  experiments/        # what was tried, what worked, what didn't
  bugs/               # root causes and fixes
  feedback/           # operator corrections
  pipeline_failures/  # CI failure classifications
  pr_reviews/         # review outcomes and verdicts
  sub_agent_runs/     # dispatch outcomes and lessons
```

### Writing memories

The bot writes memories automatically when:
- A dispatch_agent run completes (success or failure)
- A PR review completes (verdict + reasoning)
- A pipeline failure is classified
- The operator asks it to remember something

Format: YAML frontmatter + markdown body. Each memory has `name`, `category`,
`date`, `confidence`, `outcome`, `tags`, and `promote` fields.

### Searching memories

- `read_memory_local`: searches this project's `memory/` directory. Supports
  filters by category, confidence, outcome, and tags.
  for lessons from other projects.

### Promotion workflow

Memories start with `promote: pending`. After review:
- Set `promote: yes` to push to the long-term store (`make memory-promote`)
- Set `promote: no` to keep local-only

```bash
make memory-promote-list   # see what's pending
make memory-promote        # push approved memories to long-term store
make memory-lint           # validate frontmatter format
```

Promotion is optional and needs `MEMORY_STORE_URL` pointing at a store you
run; without it `make memory-promote` says so and stops. Everything else in
the memory system works locally with no external service — `memory/` is just
files in the repo.

---

## PR Workflow

The full lifecycle from code dispatch to merged PR:

```
dispatch_agent
         |
    creates branch (bot/<slug>)
         |
    agent writes code in sandbox
         |
    bot pushes branch to Gitea
         |
    bot opens PR
         |
    Gitea Actions runs CI pipeline
         |
    watch_pipeline waits for result
         |  (failure → classify, write memory, notify)
         |
    test_quality scores the tests (0.0-1.0)
         |  (< 0.8 → blocks merge)
         |
    review_pr runs LLM review
         |  - fetches diff
         |  - cross-references project memory
         |  - verdict: merge / request_changes / reject
         |
    bot announces result in IRC
         |
    memory/pr_reviews/ captures the outcome
```

### Configuration

```bash
GITEA_AUTO_REVIEW=true           # auto-trigger review_pr after dispatch
GITEA_AUTO_MERGE_CONFIDENCE=high # min confidence for auto-merge (high|medium|low)
```

### Manual review

```bash
make prs                 # list open PRs
make review PR=1         # trigger the review agent on PR #1
```

Or in IRC:

```
my-project-bot: use review_pr to review PR 1
```

---

## Shipping a Project

When the MVP is ready to leave the pipeline, strip all internal tooling so
the final repo looks hand-built.

### What to remove

| Artifact | Why |
|---|---|
| `bot/` | IRC bot, config, tools, runners — all internal |
| `memory/` | Project learnings — internal knowledge base |
| `rag/` | RAG index — internal search |
| `gitea/` | Per-project Gitea setup — internal CI |
| `runners/` | Agent runner scripts — internal dispatch |
| `.env` | Operator secrets — never ship |
| Bot-related Makefile targets | `bot`, `bot-logs`, `gitea`, `review`, `memory-*`, `rag-*` |
| `STRATEGY.md` | Internal project strategy doc |
| `AUTORESEARCH.md` | Internal iteration config |
| `kpi.json` | Internal KPI definitions |
| `logs/`, `state/`, `outputs/` | Runtime artifacts |

### What to keep

- Application source code (the actual product)
- `README.md` (rewrite for the product's audience — not this operator manual)
- `Dockerfile` and `docker-compose.yml` (if the product needs them)
- Tests (the real ones, not `qa_check.py`)
- License, contributing guide, etc.

### Verification

Before shipping, grep for tooling fingerprints:

```bash
# Scaffolding fingerprints — should return nothing outside bot/ and docs/:
grep -rn "yala\|dispatch_agent\|bot-heartbeat\|qa_check" .
grep -rn "AGENT_SANDBOX\|AGENT_COMMAND\|LLM_ROUTER\|GITEA_TOKEN" .
```

The kit ships no private names of its own, so the rest of this check is about
*yours*. Grep for whatever a reader outside your organisation should not learn
— internal service and product names, colleagues' names and bot nicks, private
IRC channels, hostnames, and your git namespace:

```bash
grep -rniE "your-org|your-internal-service|colleague-nick|#private-channel" .
grep -rn "$SCAFFOLD_DOMAIN" .   # your own private hostname(s)
git log --all --format='%s' | grep -iE "your-org|internal-project-name"
```

Check the git history as well as the working tree: a name removed in the latest
commit is still readable in every commit before it, and in the commit messages.

If any matches appear in committed files, clean them before shipping.

### Clean master branch

The simplest approach: create a fresh repo from the working directory after
removing all bot artifacts. The git history from the development branch
(with all the bot commits) stays in the internal Gitea — it never reaches
the shipped repo.

---

## Running

### Docker Compose (recommended)

```bash
make bot           # start the bot alongside the main project
make bot-logs      # follow bot logs
make bot-down      # stop the bot (leaves main project running)
```

Under the hood this uses the compose overlay:

```bash
docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml up -d <name>-bot
```

The bot runs as a non-root UID, drops all Linux capabilities, sets
`no-new-privileges`, uses a read-only container filesystem, and receives only
the explicit project/data/log mounts. If the project directory is not owned by
UID/GID 1000, set `HOST_UID` and `HOST_GID` in `.env` before building the bot.

### Standalone (development / debugging)

```bash
pip install -r bot/requirements.txt
python3 bot/bot.py
```

### Makefile targets

| Target | What it does |
|---|---|
| `make bot-check` | Report which tools loaded and what is missing. Offline, no LLM calls. |
| `make bot` | Start the bot container, and verify it stays up |
| `make bot-logs` | Follow bot logs |
| `make bot-down` | Stop the bot |
| `make bot-standalone` | Run the bot in the foreground **on the host** (needs `bot/requirements.txt` installed there) |
| `make gitea` | Start Gitea container |
| `make gitea-bootstrap` | First-run setup (create user, token, repo) |
| `make gitea-logs` | Follow Gitea logs |
| `make gitea-down` | Stop Gitea (data preserved) |
| `make gitea-nuke` | Wipe Gitea data (destructive) |
| `make prs` | List open PRs |
| `make review PR=<n>` | Trigger review agent on a PR |
| `make reindex` | Incremental RAG re-index |
| `make reindex-full` | Full RAG rebuild |
| `make rag-search Q="..."` | Search the RAG index |
| `make rag-stats` | Show RAG index stats |
| `make memory-new CATEGORY=x NAME=y` | Create a new memory file |
| `make memory-promote-list` | List memories pending promotion |
| `make memory-promote` | Push approved memories to long-term store |
| `make memory-lint` | Validate memory frontmatter |
| `make iterate` | Run autoresearch loop (foreground) |
| `make iterate-bg` | Run autoresearch loop (background) |
| `make stop-iterate` | Stop the background loop |
| `make dashboard` | Show KPI dashboard URL |
| `make test` | Run the project's unit tests |
| `make qa` | Run the end-to-end checker |
| `make health` | Probe the `/health` endpoint |
| `make clean` | Remove generated artifacts |

---

## Adding Custom Tools

1. Create `bot/tools/my_tool.py`:

```python
"""my_tool — one-line description.

Detailed description of what this tool does.

Query format:
  <pattern>    — what it does

Examples:
  "example query"    -> expected result

Required environment:
  MY_VAR    — description (default: value)

Error modes:
  - "(error pattern)" — cause and fix
"""
import os

NAME = "my_tool"
DESCRIPTION = "One-line description for the LLM to decide when to use this tool."

MY_VAR = os.environ.get("MY_VAR", "")

def call(query: str, ctx: dict) -> str:
    """Execute the tool. Returns a string result for the LLM."""
    # ctx contains: {"project": "<name>", "config": <full config dict>}
    return f"result for: {query}"
```

2. Add an entry in `bot/config.yml` under `tools:`:

```yaml
  - name: my_tool
    module: tools.my_tool
    description: "One-line description matching the module's DESCRIPTION."
    requires_env: [MY_VAR]   # omit if no env vars needed
```

3. Restart the bot (`make bot-down && make bot`)

---

## Troubleshooting

### Bot won't start, or won't connect to IRC

**Run `make bot-check` first.** It reports which tools loaded, which were
skipped and why, and whether IRC and the LLM endpoint are configured — without
connecting to anything. Most start-up problems are visible there in a second.

- Check `IRC_SERVER` and `IRC_PORT` in `.env`
- If the bot runs in Docker, it needs network access to the IRC server.
  The compose overlay joins `irc_default` and `rag_network` — make sure
  those external Docker networks exist.
- Check logs: `make bot-logs`

### Tool calls timing out

- Default LLM timeout is 30s (good for cloud APIs). If using local Ollama
  with cold starts, set `timeout_s: 180` in config.yml under `llm:`.
- Individual tool HTTP timeouts are in each tool's source.

### Sandbox image not found

- Build the image first (see [Building a sandbox image](#building-a-sandbox-image))
- Set `AGENT_SANDBOX_IMAGE` in `.env`
- Or use `AGENT_SANDBOX=none` for local dev (unsafe)

### Gitea bootstrap fails

- Make sure the Gitea container is healthy first: `make gitea-logs`
- `bootstrap.sh` is idempotent — safe to re-run
- Check `.env` for `GITEA_HTTP_PORT` conflicts with other projects

### Bot re-dispatches old messages on restart

The bot has a 5-second replay guard that ignores IRC history messages after
connecting. If you're still seeing duplicates, check if `irc-server` has a
long CHATHISTORY buffer that outlasts the grace period.

### LLM returns empty or broken tool calls

- Verify the model supports function/tool calling (not all local models do)
- Check `make bot-logs` for `tool_call=True/False` in perf lines
- Try a known-good model like `gpt-4o-mini` to isolate the issue

---

## See also

- [`config.yml`](config.yml) — bot configuration schema
- [`bot.py`](bot.py) — IRC client + tool loop implementation
- [`tools/`](tools/) — individual tool modules (docstrings are the per-tool reference)
- [`runners/`](runners/) — example agent runners
- [`../rag/`](../rag/) — project RAG (the bot's primary knowledge source)
- [`../gitea/`](../gitea/) — per-project Gitea setup
- AGENTS.md — project conventions (sections 22-24 cover bot, memory, and Gitea)
