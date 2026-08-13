# AUTORESEARCH.md — Autonomous Iteration Loop

> This file configures the standalone autoresearch runner for **<name>**. Run it with:
>
> ```bash
> make iterate          # foreground
> make iterate-bg       # background, forever
> make stop-iterate     # graceful stop
> ```
>
> The runner is operator-supplied (`AUTORESEARCH_RUNNER` env var in the Makefile). Any compatible runner that accepts this file as config will work — see the `karpathy/autoresearch` reference implementation. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). The runner reads this file, then loops: **modify → measure → keep/discard → repeat**, indefinitely, until you stop it (Ctrl-C, `kill`, or `touch STOP_AUTORESEARCH`).

---

## Goal

> **TODO: write a single sentence describing what you're optimizing.**
>
> Examples:
> - "Reduce p99 latency of POST /v1/embeddings to under 200ms while keeping all qa_check.py checks green."
> - "Get the qa_check.py overall_score from 0.65 to 0.95 without breaking any of the e2e tests."
> - "Cut RAM usage from 4GB to under 1GB while keeping throughput within 10% of baseline."

## Metric (the score the loop optimizes)

The agent runs `./metric.sh` after every change. The script must:
- Print a single floating-point number to stdout (the score).
- Exit `0` on success, non-zero if the change broke something fundamental.
- Log details to `metric.log` for the agent to read.

**Default `metric.sh`** runs `qa_check.py` and outputs the pass rate. **Override it for project-specific metrics** (latency, accuracy, RAM, etc.).

```bash
# Higher is better by default. Set DIRECTION=lower in this file to flip.
DIRECTION=higher
```

## Scope (what the agent CAN modify)

**Editable:**
- All files under the project root EXCEPT those listed below.

**Read-only (the harness):**
- `metric.sh` — the ground truth measurement. Never let the agent edit this.
- `qa_check.py` — the QA harness. Never edit during a loop.
- `tests/` — test suite. Never edit during a loop (the agent might "fix" failing tests by deleting them).
- `AUTORESEARCH.md`, `AGENTS.md`, `README.md`, `CLAUDE.md` — documentation/config.
- `.git/`, `.gitignore`, `pyproject.toml`/`package.json` (dependencies only changeable manually).

**TODO: add project-specific paths the agent should not touch.**

## Direction (what kinds of changes to try)

> **TODO: list directions the agent should explore**, ordered roughly by promise. The agent uses these as hints — it'll try other things too.
>
> Examples for a service:
> - Tune connection pool sizes (`pool_size`, `max_overflow`)
> - Add request batching / coalescing
> - Replace blocking I/O with async equivalents
> - Cache hot paths (be careful about staleness)
> - Reduce allocations in the hot loop
> - Lazy-load heavy imports

## Verify (what gates each change)

Every iteration MUST pass these gates before being kept:

1. **`metric.sh` exits 0** — no fundamental break.
2. **`python qa_check.py` exits 0** — E2E health check still passes.
3. **No `127.0.0.1` → `0.0.0.0` regressions** — `grep -r '0\.0\.0\.0' .` should not include any new bind sites.
4. **No new secrets committed** — `grep -rE '(api[_-]?key|secret|password)\s*=' --include='*.py'` clean of literal values.
5. **Score moved in the desired direction** — strictly better than the previous best (or equal-but-simpler, see Simplicity below).

## Simplicity criterion

All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing code and getting equal or better results is a great outcome — keep it. Weigh complexity cost against improvement magnitude on every iteration.

## Time budget

- **Per iteration:** 5 minutes total (wall clock). Kill any run exceeding 10 minutes and treat as a crash.
- **Total run:** indefinite — until the user stops the loop.
- **Crashes:** if obvious (typo, import), fix and retry. If fundamental, log "crash" in `results.tsv` and move on.

## Branch & results

Each autoresearch run lives on its own branch:

```bash
git checkout -b autoresearch/$(date +%b%d)-run
```

Results go in `results.tsv` (TAB-separated, append-only):

```
commit	score	memory_mb	status	description
```

- `commit`: 7-char short hash
- `score`: the metric's float output (0.000000 for crashes)
- `memory_mb`: peak resident set size in MB if measurable, else 0
- `status`: `keep` / `discard` / `crash`
- `description`: short text — what this iteration tried

`results.tsv` is in `.gitignore` — it's the experiment log, not source.

## How to run

From this project directory:

```bash
# Foreground (default — 50 iterations)
python3 "$AUTORESEARCH_RUNNER"

# Background, indefinitely, log to file
nohup python3 "$AUTORESEARCH_RUNNER" --iterations 0 > autoresearch.log 2>&1 &

# Use a specific local model (default: routes via llm-router on :11436)
python3 "$AUTORESEARCH_RUNNER" --model "qwen3-coder:latest"

# Resume on an existing branch (otherwise creates autoresearch/<date>)
python3 "$AUTORESEARCH_RUNNER" --branch autoresearch/apr09
```

The runner:
1. Reads this file to understand goal/scope/metric/direction.
2. Creates or checks out an `autoresearch/<tag>` branch.
3. Runs `./metric.sh` to establish baseline.
4. Loops: ask local LLM to propose ONE change → apply → run metric → keep or `git reset` → repeat.
5. Logs every iteration to `results.tsv` (also tee'd to `autoresearch.log`).
6. Posts a one-line summary to `#autoresearch-logs` IRC channel after each iteration.

To stop: Ctrl-C if foreground, or `kill <PID>` if background. Restart resumes from `results.tsv`.

## Stop conditions

The runner exits when ANY of these is true:
- `--iterations N` reached (default 50, `0` = forever)
- Score plateau: no improvement in last 20 iterations
- Score regression catastrophe: 5 consecutive crashes
- File `STOP_AUTORESEARCH` exists in project root (just `touch STOP_AUTORESEARCH` to halt)

## Operating modes

Set the mode in this file:

```
mode = optimize
```

- `optimize` — keep improving the score (default)
- `fix` — get the score to 1.0 (all checks passing) then stop
- `explore` — try diverse changes regardless of score, log everything
- `simplify` — prefer changes that reduce code size with equal-or-better score

## Notes for THIS project

> **TODO: add anything project-specific the agent should know** — known dead ends, performance hot spots, files that crash on certain inputs, dependencies the agent shouldn't add, etc.
