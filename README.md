# yala-scaffold

**One command creates a new project that is already dockerised, already
testable, already documented, and already safe to make public.**

```bash
./yala.sh my-project --type service --lang python --port 8080
cd my-project && make setup && make run && make qa
```

Not sure what you want yet? `./yala.sh --wizard` asks instead.

That's it. You now have a running HTTP service with a health endpoint, a test
harness, CI config, a Makefile, secret-scanning, and documentation stubs — no
copy-pasting from your last project.

---

## Table of contents

- [Who this is for](#who-this-is-for)
- [The problem it solves](#the-problem-it-solves)
- [Install](#install)
- [Your first project (walkthrough)](#your-first-project-walkthrough)
- [Project shapes](#project-shapes)
- [What you get, file by file](#what-you-get-file-by-file)
- [The four ideas](#the-four-ideas)
- [Add-ons](#add-ons)
- [Configuration](#configuration)
- [FAQ / troubleshooting](#faq--troubleshooting)
- [Extending the kit](#extending-the-kit)

---

## Who this is for

You, if you start projects often and are tired of the first two hours being
the same two hours every time: a Dockerfile that mostly works, a health check
you'll add later, a README you'll write eventually, a `.env.example` you'll
forget to update, and a `.gitignore` that lets a credential slip through.

**No prior knowledge assumed.** If you can run `docker compose up`, you can use
this. Terms like *shape*, *KPI*, and *autoresearch* are explained below — they
are simpler than they sound.

## The problem it solves

New projects rot at the edges. The code gets attention; the scaffolding
doesn't. Six months later you have five projects with five different ways to
run tests, three of which leak an absolute path from your laptop into a public
repo.

This kit makes the boring parts identical across every project, so that:

- **You** only think about the interesting part.
- **Automation** (CI, agents, monitors) can treat every project the same way,
  because `qa_check.py`, `metric.sh` and `/health` mean the same thing
  everywhere.
- **Publishing is safe by default** — the generated project separates
  committed files from operator-only ones and runs a leak check on creation.

## Install

Requires `bash`, `git`, and Docker with the Compose v2 plugin. Python, Node.js,
formatters, linters, and test runners are installed only inside project
containers; the scaffold does not install packages or change global Git
configuration on the host.

If Git author identity is not configured, the bootstrap commit uses a
commit-scoped `Yala Scaffold <yala@localhost.invalid>` identity. It does
not write repository-local or global Git configuration.

```bash
git clone <this-repo-url> yala-scaffold
cd yala-scaffold
./yala.sh --help
```

Optionally put it on your `PATH` — the script resolves its own location, so a
symlink works fine:

```bash
ln -s "$PWD/yala.sh" ~/.local/bin/yala
```

Nothing is installed system-wide and nothing writes outside the directory you
run it in.

Generated containers run as dedicated non-root users, drop Linux capabilities,
set `no-new-privileges`, use read-only root filesystems, bound process/resource
counts, and expose ports only on `127.0.0.1`. Writable access is limited to the
volumes declared by each project shape. The optional Gitea Actions runner is
disabled by default because mounting the Docker socket grants host-level Docker
control; enabling it requires the separate `make gitea-runner` command.
Generated `.env` files record the invoking numeric UID/GID so writable bind
mounts work without running containers as root or changing unrelated ownership.

## Your first project (walkthrough)

### 1. Create it

```bash
cd ~/code
yala.sh hello-api --type service --lang python --port 8080
```

The project is created in the **current directory** (`~/code/hello-api`). Use
`--into /some/other/dir` to put it elsewhere.

### 2. Look around

```bash
cd hello-api
ls
```

You'll see `app.py` (a FastAPI service with a `/health` endpoint),
`Dockerfile`, `docker-compose.yml`, `qa_check.py`, `README.md`, and more. Every
file is explained in [What you get](#what-you-get-file-by-file).

### 3. Run it

```bash
make doctor
make setup
make run
curl http://127.0.0.1:8080/health
# {"status":"ok","service":"hello-api"}
```

### 4. Check it

```bash
make test
make qa
```

These commands run inside least-privilege Docker containers. `make qa` probes
`/health` plus every `GET` route it can find and prints a JSON report. This is
the same checker CI runs, so there is no separate "CI version" to drift out of
sync.

### 5. Write your actual code

Edit `app.py`. Then extend `qa_check.py` so it verifies *your* thing works, not
just that the process is alive. The scaffolded checks are the floor, not the
ceiling.

### 6. Publish it

The generated `.gitignore` already separates committed files from operator-only
ones (`.env`, `LOCAL.md`, local data). A git repo was initialised with one
commit. Add a remote and push when you're ready.

## Project shapes

Not every project is a web service. The **shape** decides the layout, the
Dockerfile's command, what `qa_check` verifies, and what "done" means.

| Shape | For | Entry point | `qa_check` verifies |
|---|---|---|---|
| `service` | HTTP API / web app | `app.py` → uvicorn, or `src/index.js` → Fastify | `/health` returns 200, every GET route responds |
| `worker` | background processor, queue consumer | `worker.py` | heartbeat file is fresh |
| `analysis` | one-shot data analysis | `analyze.py` | `metrics.json` success flag, outputs non-empty |
| `backtest` | strategy backtest | `backtest.py` | metrics schema, graphs exist, trade count > 0 |
| `report` | PDF/HTML/xlsx generator | `report.py` | every artifact exists and exceeds a plausible size |
| `notebook` | Jupyter exploration | `notebooks/` | every notebook executes with no cell errors |
| `pipeline` | multi-stage ETL | `stages/NN_*.py` | manifest says success, every stage ran, rows > 0 |
| `webapp` | front-end app | framework default | build succeeds, health responds |
| `image` | image-to-image browser interface | `app.py` → FastAPI + Pillow | UI loads and a real image upload returns a valid transformed PNG |
| `tui` | interactive terminal application | `cmd/tui/main.go` | Go tests pass and a non-interactive render smoke check succeeds |
| `model` | LLM fine-tune (LoRA) | `dataset/build.py` → `train.py` → `evaluate.py` | dataset is sound and leak-free, an evaluation ran, and every committed threshold is met |
| `mcp` | Model Context Protocol server | `server.py` / `src/server.js` | handshake completes, `tools/list` is non-empty, schemas are valid, every tool round-trips, stdout is uncorrupted |
| `scraper` | extract records from remote pages | `scrape.py` + `extract.py` | extraction works against committed fixtures, and zero records from a page that didn't say it was empty is a **failure** |
| `bridge` | wrap an upstream service | `app.py` | `/health` and `/ready` answer different questions, upstream failure degrades to 502/503/504 not 500, credentials leak neither way |
| `cli` | distributable command-line tool | `cmd/cli/main.go` | `--help` on stdout exits 0, `--version` reports the build, a bad flag exits non-zero, stdout matches golden files |
| `agent` | LangGraph agent with tools | `graph.py` | graph compiles with no unreachable or dead-end nodes, tools are documented and bound, committed scenarios replay exactly, and a looping model is stopped |
| `audio` | speech / audio generation | `app.py` + `engines.py` | output is non-empty and **not silent**, duration scales with input, sample rate is honoured, nothing clips, and the signal survives encode/decode |
| `game` | video game (Godot) | `scripts/sim.gd` + `scenes/` | scenes load, every `res://` reference resolves, scripts compile, the simulation advances, **the same seed still produces the same game**, and a tick stays in budget |
| `browser` | multi-step browser automation | `workflows/*.json` + `runner.py` | every workflow asserts something, no workflow waits on a fixed delay, a missing selector **fails**, repeated runs agree, failures leave artifacts |
| `stream` | WebRTC media/data streaming | `server.py` + `tracks.py` | a real loopback session hands shakes, frames actually flow (connected with zero is a **failure**), a stalled source is detected, backoff is bounded, teardown leaks nothing |

```bash
yala.sh my-etl     --type pipeline
yala.sh q3-report  --type report
yala.sh price-scan --type worker
yala.sh photo-tool --type image --port 8080
yala.sh ops-console --type tui
yala.sh intent-model --type model
yala.sh docs-mcp    --type mcp --lang node
yala.sh price-watch --type scraper
yala.sh api-bridge  --type bridge --port 8080
yala.sh dotfiles    --type cli
yala.sh triage-bot  --type agent
yala.sh viewport    --type stream --port 8560
yala.sh checkout-e2e --type browser
yala.sh asteroids   --type game
yala.sh narrator    --type audio --port 8570
```

`service`, `worker` and `mcp` support `--lang python` (default) or `--lang node`.
Data-heavy shapes, `image`, `model`, `scraper`, `bridge`, `agent`, `stream`, `browser`, `game` and `audio` are Python-only.
`tui` and `cli` use Go.

The `agent` shape checks itself **offline**: `make test` and `make qa` exercise
the whole graph — routing, tool dispatch, termination — against a scripted
model, so they need no API key, no network and cost nothing. Asking a real
model whether it picks the right tools is the separate, opt-in `make evaluate`.

The `model` shape is the only one that needs a GPU — and only for `make train`
and `make serve`. Building the dataset, validating it, evaluating a served
model and running the ship gate all work on an ordinary laptop, because the
heavy dependencies live in a separate image behind a Compose profile. A
fine-tuning project where nobody can run the tests is a common and avoidable
outcome.

**Not sure?** Use `service` if something calls it over HTTP; `worker` if it runs
continuously on its own; `analysis` if it runs once and produces a number.

## What you get, file by file

```
my-project/
├── app.py                  ← your code starts here (shape-dependent)
├── Dockerfile              ← multi-stage, non-root, healthcheck included
├── docker-compose.yml      ← memory + CPU limits, 127.0.0.1 binding
├── docker-compose.override.yml  ← host-specific wiring (gitignored)
├── .env.example            ← every variable, documented; copy to .env
├── qa_check.py             ← end-to-end checker (see below)
├── metric.sh               ← prints ONE number: how good is it right now?
├── kpi.json                ← which numbers to track over time
├── Makefile                ← make up / test / lint / iterate
├── AGENTS.md               ← the rulebook (conventions, security, testing)
├── README.md               ← yours to write; starts with a working skeleton
├── STRATEGY.md             ← what problem this solves + success metric
├── AUTORESEARCH.md         ← how to run the self-improvement loop
├── CHANGELOG.md            ← keep it updated in the same PR as the code
├── CONTRIBUTING.md
├── LICENSE                 ← MIT (unsupported license values are rejected)
├── .gitleaks.toml          ← secret scanning config
├── .gitlab-ci.yml          ← lint → typecheck → secret-scan → build → test
├── .pre-commit-config.yaml ← formatting + secret scan before every commit
├── docs/                   ← SETUP, ARCHITECTURE, API stubs
├── tests/                  ← real tests, not placeholders
├── brand/                  ← colours, logo, naming
├── locales/                ← i18n strings
└── memory/                 ← decision log (see below)
```

Files that must never be committed (`.env`, `LOCAL.md`, local data) are already
in `.gitignore`.

## Things that cannot silently drift

Four failure modes are invisible to lint, typecheck and tests, and all four are
broken deploys waiting to happen. Each gets a check that runs in CI and on
commit:

| `make …` | Fails when |
|---|---|
| `check-env` | `.env.example` no longer matches the config schema — a variable added in code and never documented, or documented long after it was deleted. |
| `check-locales` | A translation is missing a key the reference locale has, or has one it does not. |
| `check-styles` | A CSS custom property is referenced but never defined. It resolves to nothing, renders invisible, and raises no error anywhere. |
| `check-clutter` | Scratch files are accumulating at the repository root instead of in `scratch/`. |

`.env.example` is worth expanding on: the block between its `scaffold:env`
markers is **generated** from the config module, not maintained beside it.
`make env-example` regenerates it. Everything outside the markers is yours.

The general principle: a check that cannot fail is decoration. Each of these
has a test in `tests/scaffold_matrix.sh` asserting it *does* fail when the
thing it guards is actually broken.

## The four ideas

Four concepts recur in every generated project. None is complicated.

### 1. `/health` — is it alive?

Every service exposes `GET /health` returning `200` with a small JSON body.
Monitoring, Docker healthchecks and reverse proxies all key off this one
endpoint, so it must never require auth and never be slow.

### 2. `qa_check.py` — does it actually work?

A single script that verifies the project end to end and prints JSON:

```json
{ "checks": [ { "name": "health", "ok": true } ], "status": "ok" }
```

Run it by hand, from CI, or from a monitor — always the same command.

Two rules the shipped checker follows, worth preserving if you rewrite it:

- **Finding zero routes is a failure.** A checker that discovers nothing and
  reports success is worse than one that fails — it looks like coverage and
  isn't.
- **Parameterised routes (`/items/{id}`) are skipped, not probed.** The
  placeholder isn't a real path; probing it yields a permanent 404 that trains
  everyone to ignore the check.

Run the checker with its `--smoke` argument inside the service container for
the strict version CI uses. It also fails when an endpoint returns an empty
list, which usually means a broken dependency rather than a legitimately empty
result. If empty *is* correct for a path, add it to `EMPTY_OK`.

### 3. `metric.sh` + `kpi.json` — is it getting better?

`metric.sh` prints exactly **one number** on its last line. That number is the
project's current score — by default the fraction of `qa_check` checks passing,
but you should change it to whatever "good" actually means here (accuracy,
p95 latency, revenue, anything).

`kpi.json` lists the numbers worth tracking over time, where each comes from,
and what you're aiming for. It's a declaration, not code:

```json
{ "name": "health_latency_ms", "unit": "ms", "direction": "lower",
  "target": 100, "source": { "type": "http_latency",
  "url": "http://127.0.0.1:8080/health" } }
```

Anything can consume it — a cron collector, a dashboard, an alerting rule. The
optional `--with-kpi` add-on ships a collector and dashboard.

### 4. `AUTORESEARCH.md` — the improvement loop

Because `metric.sh` gives a single score, you can improve the project
mechanically:

```
measure → change one thing → measure again → keep it if better, revert if not
```

`make iterate` runs that loop. It works with a local LLM, a hosted one, or your
own hands — the loop doesn't care. The only prerequisite is an honest
`metric.sh`; a metric that always returns `1.0` makes the loop useless.

### 5. Version identity and benchmarks

`metric.sh` says how good it is *now*. Two more things say *which build* and
*whether it got slower*:

```bash
make version          # derived from `git describe`, no VERSION file to forget
make bench-baseline   # once, on a quiet machine — commit bench/baseline/
make bench-compare    # the delta, as a table and a dated JSON report
```

The version reaches the image as an OCI label and comes back out of `/health`,
so an incident can answer "which build is running?" without reading deployment
logs to guess.

`make bench-compare` **always exits 0** and warns above +10% p50. Timings on
shared runners jitter by a few percent, and a check that fires on that gets
ignored within a week. Gate on the report JSON in a separate, deliberately
tuned job if you want enforcement.

### Bonus: `memory/`

A plain-text decision log: why you chose Postgres, why that timeout is 30s and
not 5s. Six months later this is the difference between understanding your own
code and rewriting it. `scripts/check_memory.py` lints it.

## Add-ons

The core scaffold produces a self-contained project. Add-ons connect it to
**infrastructure you must already run**, so they are opt-in:

| Flag | Adds | You need |
|---|---|---|
| `--with-vault` | `vault/` — pull secrets from Vault into `.env`, verify and rotate them | a reachable Vault + an AppRole |
| `--with-monitor` | `monitor/` — scheduled prober for `/health` and every HTTP KPI | somewhere to run cron |
| `--with-review` | `review/` — AI code review on merge requests, with a severity gate | an OpenAI/Anthropic-compatible LLM endpoint |
| `--with-kpi` | `scripts/kpi_collector.py` + dashboard | somewhere to store metrics |
| `--with-rag` | `rag/` — local document index for semantic search over your docs | an embeddings model |
| `--with-bot` | `bot/` — IRC bot that can answer questions and dispatch coding agents | an IRC server + an LLM endpoint |
| `--with-gitea` | `gitea/` — a per-project git server; Docker-socket CI runner is separately opt-in | Docker, a spare port |
| `--with-all` | all of the above | all of the above |

```bash
yala.sh my-project --type service --with-bot --with-kpi
```

Start without them. Add one later by scaffolding a throwaway project with the
flag and copying the directory across — the add-ons are self-contained.

See [docs/ADDONS.md](docs/ADDONS.md) for what each one needs.

## Configuration

Everything has a working default. Override with flags or environment variables:

| Flag / variable | Default | Meaning |
|---|---|---|
| `--type` | `service` | project shape |
| `--lang` | shape-dependent | `python`; `node` for service/worker/webapp; `go` for tui |
| `--port` | `8500` | host port for the service |
| `--into DIR` | `$PWD` | where the project is created |
| `--license` | `MIT` | license file to generate (currently MIT only) |
| `--holder` | `The Project Authors` | copyright holder |
| `PROJECTS_ROOT` | `$PWD` | same as `--into`, as an env var |
| `SCAFFOLD_DOMAIN` | `example.local` | local domain used in generated proxy/docs examples |
| `IRC_NETWORK` | `irc-server_default` | Docker network for the bot add-on |
| `RAG_NETWORK` | — | Docker network hosting your LLM |

`IRC_NETWORK` and `RAG_NETWORK` are **Docker network names, not hostnames**.
Find yours with `docker network ls`.

## FAQ / troubleshooting

**`network X declared as external, but could not be found`**
The compose file refers to a network by an alias that isn't its real name. Run
`docker network ls`, then set `IRC_NETWORK` / `RAG_NETWORK` in `.env` to the
real names.

**My service starts but nothing else can reach it.**
By design: everything binds to `127.0.0.1`, never `0.0.0.0`. Put a reverse
proxy in front rather than opening the port to your network.

**I added a network to `docker-compose.override.yml` and something broke.**
Compose *replaces* a service's `networks:` list from the override instead of
merging it. Repeat **every** network the service needs, including the ones in
`docker-compose.yml`. This is why the generated override ships with that block
commented out.

**`qa_check.py` passes but my endpoints are broken.**
Check the `route_discovery` entry in its output. If `discovered` is 0, the
checker isn't finding your routes — extend `_discover_get_routes`.

**Can I scaffold into an existing project?**
No. It refuses to write into an existing directory. Scaffold a fresh one and
copy across what you want.

**Do I have to use Docker?**
No, but the Dockerfile and compose file are what make the project reproducible
on another machine. `make up` runs it in Docker; you can always run
`python3 app.py` directly.

**Can I delete the parts I don't want?**
Yes. It's your project — the kit has no runtime and never touches the project
again after creating it.

## Extending the kit

- **A new shape** — add `shapes/<shape>/<lang>/` with at minimum an entry
  point, `Dockerfile`, `docker-compose.yml`, `qa_check.*`, `kpi.json` and
  `metric.sh`, then add it to `VALID_SHAPES` in `yala.sh`.
- **A new universal file** — drop it in `templates/`, add it to the
  `UNIVERSAL_TEMPLATES` array, and `fill` it into place.
- **A new add-on** — add `addons/<name>/`, a `--with-<name>` flag, and a gated
  `fill_dir` block.

Placeholders substituted into every template: `<name>`, `<PORT>`, `<shape>`,
`<lang>`, `<domain>`, `<year>`, `<date>`, `<holder>`.

**Test a change with the repository matrix:**

```bash
make test       # generate and statically validate every core shape
make test-full  # additionally build, run, test, lint, typecheck, and QA in Docker
```

`test-full` builds an image per variant, so a whole run takes tens of minutes.
When you are iterating on one shape, name it — the filter skips the rest, and
an unrecognised name is an error rather than a green run that tested nothing:

```bash
./tests/scaffold_matrix.sh --full stream          # just this shape
./tests/scaffold_matrix.sh --full mcp scraper     # or a few
```

### If Docker cannot write to a bind mount

Some daemons — user-namespace remapping, rootless, SELinux — cannot write to a
bind mount owned by the invoking user, which makes every generated project fail
the moment it writes to `outputs/` or `data/`. `make doctor` probes for this and
prints the fix rather than leaving you to infer it from a permission error:

```yaml
# docker-compose.override.yml
services:
  <name>:
    userns_mode: host
```

`test-full` applies the same override to the projects it generates, so the
suite runs on such a host.

## License

MIT — see [LICENSE](LICENSE).
