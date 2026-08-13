# AGENTS.md — Project Conventions

> **For AI agents and contributors working on this project.** This file is the source of truth for how to build, ship, test, monitor, and maintain code here. It is committed to git and meant to be read by anyone who clones the repo. Keep it generic — host-specific operational notes belong in `LOCAL.md` (gitignored), not here.

---

<!--
  Everything between the scaffold:start and scaffold:end markers below is
  GENERATED. `make refresh-agents KIT=<path-to-yala-scaffold>` rewrites that
  region in place and touches nothing outside it.

  Put project-specific conventions — domain rules, team agreements, anything
  particular to this codebase — OUTSIDE the markers, above or below. They will
  survive every refresh.

  Without this split, adopting an improved shared convention means either
  hand-merging or losing your local rules, so in practice neither happens and
  the conventions rot.
-->

<!-- scaffold:start -->

## 0. Project shape and strategy

**Before writing a single line of code, compose the strategy.** Every project starts by filling in `STRATEGY.md`:

1. **What problem are we solving?** One paragraph.
2. **What shape is this project?** Pick one from the matrix below. The shape determines defaults for qa_check, kpi.json, the CI test stage, the Dockerfile CMD, and the directory layout.
3. **Inputs** — what does it consume? Where does the data come from? Is there fixture data committed for CI?
4. **Outputs** — what does it produce? Where do artifacts land?
5. **Success metric** — the single number that answers "did this work?" This becomes the primary KPI and the autoresearch loop's target.
6. **Out of scope** — what this project deliberately does *not* do.

See `STRATEGY.md` for the full template. Update it whenever the strategy changes.

### Project shapes

| Shape | What it does | Long-running? | Languages | Default entry point | KPIs | CI test |
|---|---|---|---|---|---|---|
| **`service`** | HTTP API / web app | yes | `python` \| `node` | `app.py` → uvicorn *(python)* / `src/index.js` → Fastify *(node)* | `health_up`, `health_latency_ms`, `qa_score` | `compose up` → hit `/health` → run `qa_check.{py,js}` inside container |
| **`worker`** | Background queue/task processor | yes | `python` \| `node` | `worker.py` *(python)* / `src/worker.js` *(node)* — main loop + heartbeat file | `heartbeat_fresh`, `jobs_completed_per_min`, `p99_job_duration_ms`, `job_error_rate` | start worker, assert heartbeat appears, verify perf logs |
| **`analysis`** | One-shot data analysis → report + graphs | no | `python` only | `analyze.py` | `last_run_success`, `output_freshness_s`, `row_count`, `run_duration_ms` | run once against `fixtures/`, assert `results/metrics.json` + `outputs/*` exist |
| **`backtest`** | Strategy backtest → metrics + trade log + equity curve | no | `python` only | `backtest.py` | **`win_rate`**, `sharpe_ratio`, `max_drawdown_pct`, `total_return_pct`, `trades_count` | run against `fixtures/SPY.csv`, assert metrics schema + graph files |
| **`report`** | Document generator (PDF / slides / Excel / docx / epub / book / essay / blog) | no | `python` only | `generate_report.py` (Pandoc + WeasyPrint + openpyxl; optional `CONVERTX_URL`) | `last_build_success`, `pdf_size_bytes`, `build_duration_ms`, `build_freshness_s` | generate all targets, assert each artifact exists and exceeds a plausible min size |
| **`notebook`** | Jupyter-first exploration | interactive | `python` only | `notebooks/*.ipynb` | `notebooks_passing`, `notebooks_failing` | `nbconvert --execute` every notebook, upload executed copies as artifacts |
| **`pipeline`** | Multi-stage ETL | no (scheduled) | `python` only | `pipeline.py` + `stages/NN_*.py` | `last_run_success`, `final_row_count`, `p99_stage_duration_ms`, `run_freshness_s` | run pipeline on fixtures, assert manifest + row counts |
| **`webapp`** | Branded, i18n-ready web frontend | yes | `node` only | `src/main.jsx` (React 18 + Vite + i18next) + `server.js` (Fastify prod server) | `health_up`, `health_latency_ms`, `index_html_size_bytes`, `supported_locales` | build, serve the dist, hit `/health` + `/api/brand` + `/api/locales`, verify brand injection landed in `index.html` |

**Why the data-heavy shapes are Python-only:** `analysis`, `backtest`, `report`, `notebook`, and `pipeline` depend on libraries (pandas, numpy, matplotlib, openpyxl, jupyter, pyarrow, pandoc wrappers) whose Node equivalents aren't production-grade. Using them from Node means shelling out to Python anyway — skip the indirection and use Python directly. If a future Node ecosystem catches up, we'll add the variants; until then, `--lang node` is rejected for these shapes at scaffold time.

**Choosing a shape:**

- If it serves HTTP JSON/API traffic → `service`
- If it's a branded web frontend (marketing site, dashboard UI, customer-facing app) → `webapp`
- If it pulls work off a queue or runs forever in the background → `worker`
- If it reads data and writes a report/graphs/summary once → `analysis`
- If it's a trading/ML strategy whose success is measured by a win rate, return, Sharpe, etc. → `backtest`
- If it generates documents/PDFs/slideshows/books/essays/blog posts → `report`
- If it's Jupyter-first exploration → `notebook`
- If it's multi-stage ETL → `pipeline`

**Choosing a language (`--lang`):**

- Default is `python` for every shape.
- `--lang node` is allowed for `service` and `worker` only. Use Node when the project is a web API / background worker that fits idiomatically with Node's ecosystem (real-time sockets, heavy JSON, existing npm libraries, TypeScript downstream consumers).
- Data-heavy shapes (`analysis`, `backtest`, `report`, `notebook`, `pipeline`) are Python-only and reject `--lang node` at scaffold time. See the table above for why.

**Shape composition at project kick-off:**

The scaffolded project already ships with shape-appropriate defaults. Your job is to:

1. Confirm the shape matches reality. If the PDF/brief drives a different shape than what was scaffolded, rerun the scaffold with the right `--type`.
2. Fill in `STRATEGY.md` with the problem statement, inputs, outputs, success metric, and iteration loop.
3. Wire the real inputs (`fixtures/` for committed sample data, `.env` → `DATA_PATH` for operator-supplied real data).
4. Update `kpi.json` to track the KPIs that actually matter for YOUR problem — the defaults are starting points, not the full list.
5. Update `<qa_file>` to verify YOUR success criteria — not just that files exist.
6. Update `metric.sh` so the autoresearch loop optimizes the right thing.
7. Update all the docs (`README.md`, `docs/SETUP.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`) to describe what you actually built — see §7.

### How shapes interact with the rest of this file

Some sections apply to *all* shapes; others only to specific shapes. Each section header notes which:

- **§1 Layout** — shape-dependent top-level files; always-present files called out
- **§2 Network security** — **service + worker + notebook only**
- **§3 Configuration** — all shapes
- **§4 Containerization** — all shapes
- **§5 Resource limits** — all shapes
- **§6 Testing / `<qa_file>`** — all shapes; the *contents* vary by shape
- **§7 Living documentation** — all shapes
- **§8 Performance timing logs** — all shapes
- **§9 Git workflow + CI** — all shapes
- **§10–§13** — all shapes, with minor adaptations
- **§14 Health endpoint** — **service only**
- **§15 Secrets** — all shapes
- **§16 Self-check** — all shapes; shape-specific items called out
- **§17 KPI tracking** — all shapes; defaults vary by shape
- **§18 Autoresearch** — all shapes
- **§19 License** — all shapes
- **§20 When in doubt** — all shapes
- **§21 Branding + i18n** — all shapes ship `brand/` + `locales/`; **webapp** and **report** actively consume them, other shapes treat them as stubs
- **§22 RAG + IRC bot** — all shapes ship `rag/` + `bot/`; the bot is optional at runtime (only starts when `IRC_SERVER`/`LLM_ROUTER_URL` are set), but the scaffolding is always present
- **§23 Memory + learning** — all shapes ship `memory/`; project-local memories are always present, long-term cross-project store is optional (enabled when `MEMORY_STORE_URL` is set)
- **§24 Gitea + PR workflow** — all shapes ship `gitea/`; the Gitea container + bot push/open/review workflow is optional at runtime (enabled when `GITEA_URL` + `GITEA_TOKEN` are set, which `make gitea-bootstrap` populates)
- **§24.5 Pipeline + self-awareness + test quality** — all shapes ship `.gitea/workflows/ci.yml`; the act_runner comes up with `make gitea`; dispatch_agent watches pipelines and auto-fixes failures (circuit breaker); review_pr blocks merges on red pipelines or weak tests

---

## 1. Layout

### Universal files (every shape, all committed)

- `README.md` — what the project does, how to run it, who it's for.
- `AGENTS.md` — this file.
- `STRATEGY.md` — problem statement, inputs/outputs, success metric, iteration loop (see §0).
- `CHANGELOG.md` — user-visible changes; updated with every PR (see §7).
- `Dockerfile` and `docker-compose.yml` — the canonical way to run this project.
- `.env.example` — every required environment variable, with safe placeholder values. Real `.env` is gitignored.
- `.gitignore` — at minimum: `.env`, `*.log`, `__pycache__/`, `node_modules/`, `dist/`, `build/`, `*.db`, `*.sqlite*`, secrets.
- `LICENSE` — open-source license (MIT by default).
- `CONTRIBUTING.md` — how external contributors should engage.
- `<qa_file>` — end-to-end checker (see §6).
- `kpi.json` — KPI definitions (see §17).
- `metric.sh` — single-script metric for the autoresearch loop (see §18).
- `AUTORESEARCH.md` — iteration config (see §18).
- `.gitlab-ci.yml` — automated pipeline: lint, secret-scan, build, shape-appropriate e2e test (see §9).
- `.gitleaks.toml` — secret scanner rules.
- `.pre-commit-config.yaml` — optional host-side hooks; the canonical checks run through the Docker-only Make targets (see §9.5).
- `.dockerignore` — keeps build contexts lean and excludes root-owned runtime state (gitea/data/, runner-data/, pycache).
- `pyproject.toml` — single source of truth for `[tool.ruff]`, `[tool.mypy]` strict config, and `[tool.pytest.ini_options]` (Python shapes only).
- `requirements.txt` + `requirements-dev.txt` — runtime vs dev dependencies. requirements-dev.txt has ruff, mypy, pre-commit, py-spy so CI and local dev share versions (Python shapes only).
- `tests/` with a starter test that exercises real behavior — no `assert True`, no mock-only dead ends. See §6 on why.
- `scripts/kpi_collector.py` + `scripts/kpi_dashboard.py` — portable reference KPI stack when `--with-kpi` is enabled.
- `scripts/translate_docs.sh` + `scripts/translate_docs_impl.py` — pluggable doc/locale translator (see §21).
- `brand/` — single source of truth for colors, fonts, logos, contact info (see §21).
- `locales/` — translation keys for i18n, shared by frontend + reports (see §21).
- `rag/` — optional project RAG config + indexer when `--with-rag` is enabled (see §22).
- `bot/` — optional IRC agent when `--with-bot` is enabled (see §22).
- `memory/` — project learnings (decisions/, experiments/, bugs/, feedback/, sub_agent_runs/, pr_reviews/, SCHEMA.md, README.md) (see §23).
- `gitea/` — optional per-project Gitea when `--with-gitea` is enabled; its Docker-socket Actions runner remains separately opt-in (see §24).
- `.gitea/workflows/ci.yml` — shape-appropriate Gitea Actions workflow (lint, secret-scan, build, test, artifact upload) (see §24.5).

### Shape-specific entry points

| Shape | Entry point | Extra directories |
|---|---|---|
| `service` (python) | `app.py` (FastAPI) | `tests/`, `data/` |
| `service` (node) | `src/index.js` (Fastify) | `tests/`, `data/` |
| `worker` (python) | `worker.py` (main loop) | `data/` (holds `heartbeat`) |
| `worker` (node) | `src/worker.js` (main loop) | `data/` (holds `heartbeat`) |
| `webapp` (node) | `src/main.jsx` (React) + `server.js` (Fastify) | `src/`, `public/`, `dist/` (gitignored) |
| `analysis` | `analyze.py` | `fixtures/`, `data/` (gitignored), `outputs/` (gitignored), `results/` |
| `backtest` | `backtest.py` + `config/strategy.yml` | `fixtures/`, `data/` (gitignored), `outputs/`, `results/` |
| `report` | `generate_report.py` | `content/`, `templates/`, `assets/`, `outputs/` |
| `notebook` | `notebooks/*.ipynb` | `data/`, `outputs/` |
| `pipeline` | `pipeline.py` + `stages/NN_*.py` | `fixtures/`, `data/`, `state/`, `outputs/` |

### Required `docs/` directory (every shape, committed, kept current — see §7)

- `docs/SETUP.md` — full install/config walkthrough beyond the README quickstart.
- `docs/API.md` — endpoint-by-endpoint API reference (**service only**; for other shapes, rename to `docs/USAGE.md` and document CLI flags + env vars + entry point contract).
- `docs/ARCHITECTURE.md` — module map, data flow, design decisions and trade-offs.
- `docs/KPI_SETUP.md` — how to wire `kpi.json` into a monitoring stack (ships as a template).

---

## 2. Network security — localhost only

**Applies to: `service`, `worker`, `notebook`, and any other shape that binds a network port.** One-shot shapes (`analysis`, `backtest`, `report`, `pipeline`) typically expose no ports at all — skip this section for those unless they spin up an ad-hoc HTTP listener.

**Every service binds to `127.0.0.1`. Never `0.0.0.0`** unless you have a specific reason and have audited the auth model. External access is the operator's responsibility, handled by their reverse proxy of choice — not by your service.

- Python: `--host 127.0.0.1` / `host="127.0.0.1"`.
- Node: `app.listen(PORT, '127.0.0.1')`.
- Go: `http.ListenAndServe("127.0.0.1:PORT", ...)`.
- Docker compose ports: `"127.0.0.1:${PORT}:${PORT}"`. **Never** `"${PORT}:${PORT}"`.
- The container itself can bind `0.0.0.0` internally if it's behind a published port that maps to `127.0.0.1` on the host.

The only exception is when an explicit deployment guide instructs the operator otherwise.

---

## 3. Configuration — `.env` only

**Zero hardcoded paths, hostnames, ports, secrets, or operator-specific values in source code.** Everything goes through environment variables — and every one of them is **declared once, in `<config_module>`**.

### Never read the environment directly

Do not call `os.environ` / `process.env` / `os.Getenv` anywhere outside the config module. Not "just this once", not for a debug flag.

An undeclared variable fails at the point of use — three layers deep, at 3am, as a `NoneType` or an `undefined`. A declared one fails at startup, by name, with every problem listed at once. That difference is worth more than the two lines it costs.

```python
# WRONG — undeclared, untyped, undocumented, fails somewhere else entirely
timeout = int(os.environ.get("TIMEOUT", "30"))

# RIGHT — add a Field to <config_module>, then:
timeout = settings.timeout
```

### `.env.example` is generated, not maintained

The block between the `scaffold:env` markers in `.env.example` is rendered from the config module's schema:

```bash
make env-example    # regenerate it
make check-env      # fail if it and the config module disagree
```

A hand-maintained `.env.example` is always a little bit wrong — a variable added in code and never documented, or documented long after it was deleted. Both are invisible until someone tries to deploy. Everything *outside* the markers is yours: operator notes, optional add-on wiring.

### Rules

- `.env` is gitignored. The user copies `.env.example` → `.env` and fills in real values.
- If a required variable is missing, the process **must not start**. Never fall back to a default that only works on the original author's machine.
- Validate at the boundary: a port is in range, a URL is well-formed, an enum is one of its values. The config module ships casts for these.
- Mark secrets `secret=True` so they are never echoed by `--check`, by `/health`, or in an error message.
- Shape-specific variables go in `config_extra.py`, which the config module picks up automatically — they land in `.env.example` too.

### Secrets

Prefer the Vault add-on (`--with-vault`) over long-lived values pasted into `.env`:

```bash
make secrets-pull     # fetch into .env at mode 0600
make secrets-check    # verify each resolves — prints names, never values
```

`vault/secret-map.tsv` is committed: it holds names and paths, never values, so every change to what this project may read shows up in a diff.

---

## 4. Containerization — fully self-contained Docker

The project must be runnable by anyone with **only Docker installed**, with no other host dependencies. The `docker-compose.yml` and `Dockerfile` capture the entire runtime contract.

- The Dockerfile installs all OS-level dependencies (don't assume the host has `ffmpeg`, `git`, `libpq`, etc.).
- The docker-compose.yml maps `127.0.0.1:${PORT}:${PORT}`.
- All config comes from `.env` via `env_file: .env` in compose.
- Persistent data lives in named volumes (`./data`, declared in `docker-compose.yml`).
- The `quickstart` is always: `cp .env.example .env && docker compose up -d`.
- Set `mem_limit` and `cpus` on every service (see §5).
- Use `restart: unless-stopped` for daemons.
- The container's healthcheck:
  ```yaml
  healthcheck:
    test: ["CMD", "curl", "-f", "http://127.0.0.1:${PORT}/health"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 30s
  ```

If the project is a library, ship a `Dockerfile` that demonstrates running its tests + example.

---

## 5. Resource limits — RAM, CPU, DB pools

### Docker
Every container has explicit memory and CPU limits. Size memory at **~3× current observed usage** to absorb spikes without OOM.

```yaml
services:
  myservice:
    image: myimage
    mem_limit: 512m       # required
    cpus: 2               # required if compute-heavy
    restart: unless-stopped
```

#### External networks: always map the alias with `name:`

Compose files refer to operator networks by a stable alias (`irc_default`, `rag_network`, ...). The alias is almost never the network's real name, so it **must** be mapped:

```yaml
networks:
  irc_default:
    external: true
    name: ${IRC_NETWORK:-irc-server_default}   # real name; override in .env
```

Without `name:`, the whole stack refuses to start with `network irc_default declared as external, but could not be found`. Find real names with `docker network ls`.

#### `docker-compose.override.yml` REPLACES `networks:`, it does not merge

Compose merges most keys from the override but **replaces** a service's `networks:` list wholesale. Listing two networks in the override when the tracked compose file lists three silently detaches the service from the third: the container starts, reports healthy, and cannot resolve one of its dependencies — surfacing much later as a DNS error deep in a log.

So the scaffolded override ships with its `networks:` block commented out. If you enable it, repeat **every** network the service needs, including those the tracked file already declares. `extra_hosts` merges cleanly and is safe to set alone.

### Database connection pools
- **Postgres (psycopg/psycopg2):** `psycopg_pool.ConnectionPool` with `min_size=2, max_size=10` for typical services. Never one connection per request.
- **Postgres (SQLAlchemy):** `pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=3600`.
- **Redis:** `redis.ConnectionPool` with `max_connections=20`. Always `decode_responses=True`.
- **HTTPX/requests/fetch:** create one client per process; don't open a new client per request.

### Avoid leaks
- Always `close()` HTTP clients, DB cursors, file handles. Use context managers (`with` / `using`).
- Don't accumulate unbounded lists/dicts in long-running processes — bound them with `collections.deque(maxlen=N)` or evict on a TTL.
- For queues, set explicit caps and document the drop strategy.

---

## 6. Testing — `<qa_file>`

Every project ships an end-to-end checker at `<qa_file>`. Python and Node
implementations both return `{"checks": [...], "status": "ok"|"fail"}`, but
what the checker *verifies* depends on the shape:

| Shape | What `<qa_file>` verifies |
|---|---|
| `service` | `GET /health` returns 200 + any app-specific endpoints pass |
| `worker` | `data/heartbeat` file is fresh, worker-specific signals healthy |
| `analysis` | `results/metrics.json` success sentinel present, required `outputs/*` exist and are non-empty |
| `backtest` | `results/metrics.json` schema has win_rate/sharpe/drawdown/trades, graph files exist, trades_count > 0 |
| `report` | Every expected artifact file exists and exceeds a plausible minimum size; manifest marks success=true |
| `notebook` | Every `notebooks/**/*.ipynb` executes cleanly under nbclient with no cell errors |
| `pipeline` | `outputs/manifest.json` marks success=true, every stage ran, final output row count > 0 |

The scaffold drops the right variant into place based on `--type`. You still need to **extend** it with checks specific to your problem — the scaffolded version is the floor, not the ceiling.

### Route discovery must never pass vacuously (`service` shape)

`qa_check.{py,js}` discovers `GET` routes by scanning the **whole project**, not just `app.py` / `src/index.js`, and matches `@router.get` / `router.get(...)` as well as `app.get`. Any service that grows past a single file registers routes in a module; a discoverer that reads only the entrypoint then finds nothing and returns a clean pass over an empty set.

Two rules follow, both already implemented in the shipped checkers — preserve them if you rewrite:

- **Zero discovered routes is a failure**, reported as a `route_discovery` check and a non-zero `--audit` exit. Vacuous success is worse than failure: it looks like coverage and is not.
- **Parameterised routes are skipped, not probed.** `/jobs/{job_id}` and `/jobs/:id` are 404s by construction — the placeholder is not a real path. They are listed under `skipped_parameterised` so the omission is visible rather than silent. Probing them produces a permanent meaningless failure that trains everyone to ignore the check.

If your service registers routes some other way (a table, a plugin loader), extend `_discover_get_routes` / `discoverGetRoutes` rather than letting the check pass over nothing.

Example (service shape):

```python
"""E2E health/QA checker for <project>. Run through: make qa"""
import os
import httpx


class Checker:
    name = "<project>"

    def run(self) -> dict:
        port = os.environ.get("PORT", "8500")
        results = {"checks": [], "status": "ok"}
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
            ok = r.status_code == 200
            results["checks"].append({"name": "health", "ok": ok, "status_code": r.status_code})
            if not ok:
                results["status"] = "fail"
        except Exception as exc:
            results["checks"].append({"name": "health", "ok": False, "error": str(exc)})
            results["status"] = "fail"
        # Add additional checks: DB connectivity, key endpoints, expected behavior
        return results


CHECKER_CLASS = Checker

if __name__ == "__main__":
    import json
    result = Checker().run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "ok" else 1)
```

For projects with non-trivial logic, also add:
- **Unit tests** in `tests/` (`pytest` for Python, `vitest` / `node --test` for JS/TS).
- **Integration tests** that hit the real `/health` endpoint and key API surface.
- A `Makefile` or `bun run test` / `pytest` script.
- CI config (`.gitea/workflows/ci.yml` + `.gitlab-ci.yml`) that runs the full test suite inside a container.

### Tests must NEVER make real network calls to external services

**Tests must be hermetic.** CI runs inside a container with no access to
the operator's host services (an IRC server on 127.0.0.1:16667, a speech
service on host.docker.internal:8197, etc.) or to third-party APIs
(api.openai.com, api.elevenlabs.io, api.x.ai). A test that opens a real
socket or issues a real HTTP request to any of these is a flaky test
waiting to happen — it fails in CI even when the code is correct.

The review agent rejects PRs with:

- **Real IRC connections in tests** — `irc.connect()`, direct `socket`
  usage against `127.0.0.1:16667` or `irc-server:6667`. Use the
  `_send`-patch pattern from `tests/test_irc_client.py` (assign
  `client._send = fake_send` to capture outgoing lines without
  actually connecting).
- **Real external HTTP in tests** — any `httpx.post`/`requests.post`
  to `api.openai.com`, `api.elevenlabs.io`, `api.x.ai`, `api.anthropic.com`,
  `generativelanguage.googleapis.com`, etc. Mock with
  `respx.mock` / `httpx.MockTransport` / `monkeypatch.setattr` so the
  test asserts your code handles a known response shape, not that the
  vendor's API is up.
- **Real ASR/TTS backends in tests** — speech-service URLs and similar
  downstream services must be mocked.
  Integration tests that DO exercise them belong in a separate
  `tests/integration/` dir gated by a marker (`pytest -m integration`)
  that CI skips by default.

Pattern for mocking httpx outbound calls in FastAPI tests:

```python
import respx
from httpx import Response

@respx.mock
def test_speak_grok_returns_audio(client):
    respx.post("https://api.x.ai/v1/audio/speech").mock(
        return_value=Response(200, content=b"\\x00\\x00fake-audio-bytes")
    )
    r = client.post("/api/speak", params={"text": "hi", "voice": "grok-male"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
```

If you catch yourself writing a test that needs the real vendor to be
up, split it: mock it here, and put the real-integration version under
`tests/integration/` with `@pytest.mark.integration`.

### Tests must be REAL functional validating tests — not just present

**Writing a test file with `assert True` is worse than writing no tests at all** — it creates the illusion of coverage while hiding broken code. The review agent (AGENTS.md §24) explicitly rejects PRs with:

- **Tautological assertions** — `assert True`, `assert 1 == 1`, `expect(true).toBe(true)`, `strictEqual(1, 1)`
- **Empty test bodies** — `def test_foo(): pass` or `it('works', () => {})` with no body
- **Mock-only tests** — setting up a mock inside the test and then only asserting `mock.assert_called_with(...)`. Mocks are fine for external dependencies, but the test must still verify real behavior of YOUR code with real inputs and real outputs
- **Tests with zero assertions** — a test that executes code but makes no assertions about the result
- **Missing source→test coverage** — if a source file is changed in a PR but the corresponding test file has no new assertions, the reviewer treats it as missing tests

For every new public function, endpoint, or class, require at least:

1. **One happy-path test** with real inputs and assertions on real outputs
2. **One edge case** (empty input, boundary condition, error case)

The `bot/tools/test_quality.py` static analyzer scores changed test files 0.0-1.0 and the review agent's **merge verdict requires a score ≥ 0.8**. Anti-patterns or missing coverage force the verdict to `request_changes` regardless of what the LLM thinks about the rest of the diff. See AGENTS.md §24.5 for the full pipeline + test-quality gating.

### The runner's test gate

Every coding-agent runner in `bot/runners/` (cursor, claude_code, aider, custom) runs `make test` inside the sandbox after the agent declares success. **If tests fail, the dispatch is marked failed and no PR is opened.** This is the first line of defense — broken code never reaches Gitea at all.

If the local tests pass but the Gitea Actions pipeline still fails (because the sandbox tests differed from the CI environment), `dispatch_agent.py` catches that too and starts an auto-fix loop (§24.5 circuit breaker).

---

### Visual verification — for anything with a UI

**Applies to the `webapp` and `image` shapes, and to any shape that renders HTML.**

After changing a page, a component, or styles, **look at it rendered** before calling the task done. Type-check, lint and formatter passing proves the code compiles — not that it looks right.

The failure mode this exists for: an undefined design token (`bg-primary` with no `--color-primary` defined, a CSS variable that never resolves) compiles clean, raises nothing, and renders invisible. Only pixels catch it. A test asserting HTTP 200 on a page that renders as a blank white rectangle passes happily.

So:

1. Render the page headlessly and **look at the image**, not just the status code.
2. Check both light and dark mode if the change touches colour.
3. `qa_check` writes `outputs/screenshot-*.png` and fails on a uniform (blank) frame — that catches the crude case automatically, but it is a floor, not a substitute for looking.

If the dev server cannot start, render the component against compiled CSS and screenshot that. Do not skip verification because the full app will not boot — that is precisely when appearance regressions ship.


## 7. Living documentation — MANDATORY

**Documentation is not a deliverable at the end — it is updated continuously as the code changes.** If a PR changes behavior and doesn't touch the docs, the PR is incomplete. No exceptions.

This applies equally to human contributors and AI agents working on the project. An agent that adds a feature without updating the relevant docs has done half the work.

### What must exist (committed to the repo)

| File | Purpose | When to update |
|---|---|---|
| `README.md` | What it does, who it's for, 60-second quickstart (`docker compose up`), links to deeper docs | Any user-visible change: new env var, new port, new command, new quickstart step |
| `docs/SETUP.md` | Full setup: prerequisites, install steps, configuration matrix, first-run verification, common setup pitfalls | Any change to install/deploy steps, dependencies, or `.env` vars |
| `docs/API.md` (or `/openapi.json`) | Every endpoint: method, path, request schema, response schema, error codes, example `curl`, rate limits | Any endpoint add/remove/rename, schema change, status code change, auth change |
| `docs/ARCHITECTURE.md` | Module map, data flow, key design decisions and *why*, trade-offs, what was considered and rejected | Any structural change, new module, new external dependency, changed data flow |
| `docs/KPI_SETUP.md` | How to wire `kpi.json` into the operator's monitoring stack | Shipped as a template; update when source types change |
| `CHANGELOG.md` | User-visible changes per release. Format: [Keep a Changelog](https://keepachangelog.com/) | Every PR that changes behavior gets a `CHANGELOG.md` entry in the same PR |
| `docs/EDGE_CASES.md` *(or inline in API.md)* | Known edge cases, failure modes, what input causes what behavior, what's explicitly out of scope | Any time you discover a surprising case or intentionally decide not to handle one |

### Inline code documentation

Code comments are part of the contract, not decoration. Rules:

1. **Document the WHY, not the WHAT.** `// increment counter` is noise. `// counter rolls over at 2^31 — upstream API truncates silently above this, see issue #42` is load-bearing.
2. **Every exported/public function has a docstring** describing: purpose, parameters (with units — `timeout_ms` not `timeout`), return value, raised exceptions, and at least one edge case or precondition.
3. **Non-obvious logic gets a `# Why:` comment** explaining the reasoning. If you had to think for 30 seconds to write it, someone will have to think for 30 seconds to read it.
4. **Edge cases get explicit comments** near the branch that handles them. Example: `# Empty body is valid per RFC — treat as no-op, not error.`
5. **Workarounds and hacks get a `# HACK:` or `# TODO:` comment** with a link to the issue and the conditions under which it can be removed.
6. **Don't touch docstrings for code you didn't change.** If you fix one line in a 100-line function, don't rewrite its docstring unless your fix changed the contract.

### What to document as you build

When you write a feature, in the *same* change you must:

- [ ] Update the **README** quickstart if the user-facing steps changed
- [ ] Update **`docs/API.md`** for every endpoint touched (including new error codes)
- [ ] Update **`docs/SETUP.md`** if you added an env var, dependency, or setup step
- [ ] Update **`.env.example`** for every new `os.environ.get(...)` or `process.env.*`
- [ ] Add an entry to **`CHANGELOG.md`** under `## [Unreleased]`
- [ ] Add a docstring to every new exported function, class, and endpoint handler
- [ ] Add inline `# Why:` comments where the logic is non-obvious
- [ ] Document **edge cases** you discovered while building (empty input, unicode, very large payloads, concurrent access, network failure, auth failure, etc.)
- [ ] Document **expectations** — what the function assumes about its inputs and its environment (e.g. "caller holds the write lock", "runs in the asyncio event loop")
- [ ] Add a new KPI to `kpi.json` if the change introduced a new measurable behavior
- [ ] Add a new check to `<qa_file>` if a new healthcheck makes sense
- [ ] Update `docs/ARCHITECTURE.md` if you added a new module, changed a data flow, or made a decision worth preserving

### Documenting expectations and edge cases

This is the part most often skipped and most valuable later. For every new function/endpoint/module, write down:

- **Happy path:** what this does when everything works.
- **Expected inputs:** what types, what ranges, what formats. Include units.
- **Preconditions:** what must be true before calling this (DB initialized? user authenticated? lock held?).
- **Postconditions:** what is true after this returns successfully.
- **Failure modes:** what can go wrong, what exception/status is raised, whether state is rolled back.
- **Out-of-scope:** what this explicitly does *not* handle, with a pointer to what does.
- **Concurrency:** is this thread-safe, reentrant, idempotent? Can it be called concurrently? What happens if it is?
- **Performance:** expected latency, memory, and cost per call. Note if complexity is worse than O(n).

### Documentation hygiene rules

- **Docs land in the same PR as the code.** Never "I'll document it later." Later never comes.
- **Stale docs are worse than no docs.** If you remove a feature, remove the doc entry. If you rename a function, grep for its old name across `docs/` and update.
- **Examples must be runnable.** Every `curl` example, every code snippet, every command in `README.md` must work as written against a fresh install. When docs drift from reality, fix the docs, not reality.
- **Link, don't duplicate.** `README.md` points to `docs/SETUP.md`; `docs/SETUP.md` points to `docs/API.md`. Don't maintain the same paragraph in three places.
- **Version-bump the docs.** When breaking changes land, add a `## Breaking changes` block in `CHANGELOG.md` with the migration steps.
- **If you found yourself confused while reading the code, that confusion is a doc bug.** Add the comment that would have helped you. The next reader will thank you.

---

## 8. Performance timing logs — MANDATORY

Every I/O call (HTTP, DB query, file read, subprocess) and every multi-step phase emits a structured timing log:

```
[<project>-perf] phase=<step_name> duration_ms=<elapsed> [key=value ...]
```

**Python:**
```python
import time, logging
_t = time.monotonic()
result = some_io_call()
logging.info(f"[<project>-perf] phase=fetch_x duration_ms={int((time.monotonic() - _t) * 1000)} status={result.status_code}")
```

**TypeScript / Node:**
```typescript
const _t = Date.now();
const data = await fetch(url);
logger.info(`[<project>-perf] phase=fetch_x duration_ms=${Date.now() - _t} status=${data.status}`);
```

These logs feed the KPI collector (see §17) to compute p50/p95/p99 without a separate metrics endpoint.

---

### Benchmarks — is it *worse* than it was?

Perf logs tell you what a run cost. They do not tell you whether that is worse than last week, and nothing else here does either.

```bash
make bench-baseline   # once, on a quiet machine — commit bench/baseline/
make bench            # after a change
make bench-compare    # the delta, as a table and a dated JSON report
```

Benchmarks are declared as data in `bench/benchmarks.json`, so adding one never means editing the runner. The shipped ones measure the scaffold, not your project — **replace them with the operations whose latency you would actually notice getting worse.** A benchmark that never moves teaches nobody anything.

`make bench-compare` **always exits 0.** A regression prints `⚠ WARN` and sets `"regression": true` in the report, but never fails the build: timings on shared runners are noisy enough that a hard gate fires on unrelated load within a week, and a check that cries wolf gets deleted rather than fixed. If you want enforcement, gate on the report JSON in a separate job tuned against real measured variance.

Re-capture the baseline deliberately, when a change is *meant* to move the numbers, and say so in the commit message.


## 9. Git workflow

- **Branch:** `main` is stable. Feature branches for non-trivial work.
- **Commits:** meaningful, present-tense, one logical change per commit. Conventional commits welcome (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`).
- **Never** force-push `main`. Never `git reset --hard` published commits. Never `--amend` after pushing.
- **Never skip hooks** (`--no-verify`, `--no-gpg-sign`) unless explicitly requested.
- **Never commit secrets.** Use `.env` (gitignored). If a secret is accidentally committed, rotate it immediately and rewrite history.
- **PRs require ALL of:**
  - **green `.gitlab-ci.yml` pipeline** (lint, secret-scan, build, e2e test — see §9.5)
  - passing `<qa_file>`
  - updated `kpi.json` if a new measurable behavior was added
  - updated `README.md` if user-visible behavior changed
  - updated `docs/API.md` if any endpoint changed (added, removed, renamed, new field, new status code)
  - updated `docs/SETUP.md` if install/env/deployment steps changed
  - updated `.env.example` for every new env var read
  - a `CHANGELOG.md` entry under `## [Unreleased]`
  - docstrings on every new exported function/class/endpoint
  - inline `# Why:` comments for non-obvious logic and edge cases
  - A PR that changes code but touches zero docs is almost always incomplete — reviewers should push back.

---

### Commit messages — Conventional Commits

```
type: short summary in the imperative
```

Types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert`. Add a `BREAKING CHANGE:` footer when the public surface changes incompatibly.

The summary should say what changed and where or why — `fix: reject empty upload before decode`, not `fix: bug`.

This is not ceremony. `make changelog` derives the `[Unreleased]` section from these commits, and `make version` derives the version from tags. A hand-maintained changelog decays — every project that has tried the rule "every PR adds an entry" has watched it stop happening. A derived one is merely occasionally imprecise, which is a far better failure mode.


## 9.5. CI / CD — automated pipeline

Every project ships a `.gitlab-ci.yml` AND a `.gitea/workflows/ci.yml` that run on every push and merge request. **A PR that breaks the pipeline is not ready to merge — no exceptions.**

### Bug-prevention division of labor (Reid pipeline philosophy)

The pipeline is structured so that each mistake is caught at the cheapest layer it can reasonably be caught at. Later layers only run when earlier ones pass, so you're never waiting on CI to find a formatting error.

| Layer | Tools | What it catches | Cost |
|---|---|---|---|
| **Save-time** | IDE plugins (ruff, mypy-vscode, eslint) | Syntax errors, unused imports, obvious type errors, format drift | milliseconds |
| **`git commit`** | `.pre-commit-config.yaml` → ruff check, ruff format, gitleaks, whitespace checks, JSON/YAML sanity | Lint failures, format drift, leaked secrets, trailing whitespace, broken JSON | 1-3s per commit |
| **`git push`** | pre-push hooks → `mypy --strict`, `pytest -q` | Type errors, test regressions | 5-30s before remote ever sees your code |
| **Runner pickup** | CI → lint → typecheck → secret-scan → unit-tests → build → integration-test | Full test suite, integration tests, container builds, shape-specific E2E (`<qa_file>`) | 1-5 minutes |
| **Manual** | `make profile` (py-spy) | Correct-but-slow code: pathological O(n²) sorts, allocation storms, GIL contention | ad-hoc |

The intent is Python-forgiving languages never surprise you in production. Most classes of bug are "code that's happy to run with the wrong data shape"; layering ruff + mypy + pytest + integration tests means every class of bug gets caught somewhere before it ships.

### Stages (per shape, in order of dependency)

1. **`lint`** — `ruff check` + `ruff format --check` (Python) or `eslint` + `prettier --check` (Node). **Blocking.** No `|| echo WARN` escape hatches — if the scaffold ships clean and your changes break this, fix them.
2. **`typecheck`** — `mypy` with `strict=true` per `pyproject.toml` (Python only). **Blocking.** Python's permissive runtime means most real-world bugs hide in bad assumptions about data shapes; mypy catches them before they reach CI, let alone prod.
3. **`unit-tests`** — `pytest -q tests/` (Python) or `node --test` (Node). **Blocking.**
4. **`secret-scan`** — `gitleaks detect` with the rules in `.gitleaks.toml`. **Blocks on any hit.** If something trips it, rotate the secret immediately and scrub history — don't just add it to the allowlist.
5. **`build`** — `docker build` the service image. Depends on lint + typecheck + unit-tests + secret-scan passing.
6. **`test`** (shape-specific) — start the Compose sandbox, wait for the shape's health/success signal, run `<qa_file>` inside the container, and tear down project-scoped resources.

The default local workflow uses Docker Compose. The optional Gitea Actions
runner is disabled until an operator explicitly accepts its Docker-socket trust
boundary with `make gitea-runner`.

### Rules

- **Do not disable or `allow_failure: true` a job to make a red pipeline go away.** Fix the underlying issue. The only job allowed to `allow_failure: true` is `lint` on fresh scaffolds (because there's no code to lint yet).
- **`<qa_file>` runs inside the container**, not from a host language runtime. This honors the `127.0.0.1` bind rule (§2).
- **Secrets in CI variables, never in the YAML.** GitLab CI variables (Settings → CI/CD → Variables) are the right place. Mask and protect them.
- **Cache is per-branch.** If a build gets weird, re-run it with "Clear runner cache" — don't debug phantom issues.
- **New test job?** Add it to the `test` stage and give it a `needs: [build:docker]` dependency so it reuses the built image.
- **Adding a new service (DB, Redis, etc.) to the e2e test?** Add it to `docker-compose.yml` with an appropriate healthcheck. The test job spins the whole compose stack up, not just the main service.

### Local equivalent — preflight every layer before pushing

The canonical local workflow is fully containerized:

```bash
make doctor
make setup
make lint
make typecheck
make test
make run
make qa
```

These targets do not install Python or Node packages on the host and do not
change global Git configuration. Pre-commit remains optional for contributors
who already use it.

### Profiling "correct but slow" code — the final layer

When a function is logically right but too slow, unit tests and type checks won't catch it. Use py-spy (bundled in `requirements-dev.txt`):

```bash
make profile              # live top-style view of running service (press ? for help)
make profile FLAME=1      # flamegraph SVG written to outputs/flame.svg
```

See Reid's advice: "performance advice gets vague very quickly. 'Make it faster' is not useful. 'Avoid sorting everything when I only need ten results' is useful. A profiler helps you get to that more precise level."

### When the pipeline is red

- **Read the job log top-to-bottom before touching anything.** Most failures are obvious from the log (missing env var, wrong port, broken compose file).
- **`docker compose logs` in `after_script`** is captured on every failure — that's where container-side errors show up. Look there before you look at the CI YAML.
- **If the failure only reproduces in CI and not locally**, it's almost always (a) a missing env var that `.env.example` provides a default for but CI doesn't, or (b) a race where `/health` takes longer than 30s to come up. Fix the root cause, not the retry count.

---

## 10. Logging & error handling

- Use the language's standard structured logger (Python `logging`, Node `pino` / built-in console).
- All HTTP calls have explicit timeouts (default: 10s for fast paths, 30s for LLM calls, 5min for slow batch ops).
- Catch external errors and degrade gracefully — return cached/stale data, return 503, or fall back to a secondary backend.
- **Never** swallow errors silently. Log them with context.

---

## 11. Service lifecycle

- The canonical way to run is `docker compose up -d`.
- Handle `SIGTERM` cleanly — close DB pools, flush buffers, finish in-flight work — don't hang on shutdown.
- For one-shot tasks (data sync, cache refresh), use a separate compose service with `restart: "no"`.

---

## 12. Background work & idempotency

- Long operations belong in background threads / task queues.
- HTTP handlers should never block on slow work — kick it off async and return.
- All sync/refresh scripts must be **idempotent** — safe to rerun without duplicating data.
- Cache aggressively but with TTLs. Use a monotonic clock for elapsed-time checks; wall-clock for timestamps.

---

## 13. Inter-service contracts

- Services communicate over HTTP (or gRPC where bandwidth matters).
- Always pass timeouts. Always retry transient failures with exponential backoff (max 3 retries).
- Document your service's API in `README.md` or `docs/api.md`. OpenAPI / `/openapi.json` is preferred.

---

## 14. Health endpoint

**Applies to: `service` and any other shape that listens on a port.** Workers use the heartbeat-file pattern instead; one-shot shapes (`analysis`, `backtest`, `report`, `pipeline`) use a success sentinel file (`results/metrics.json` or `outputs/manifest.json`) written by the entry point at the end of a successful run.

Every HTTP service **must** expose `/health` (preferred) returning `200` with at least `{"status":"ok"}`. The endpoint should verify upstream dependencies (DB, Redis, downstream APIs) and return `503` if any are down.

```python
@app.get("/health")
def health():
    checks = {}
    try:
        db.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        return {"status": "fail", "checks": {"db": str(exc)}}, 503
    return {"status": "ok", "checks": checks}, 200
```

---

## 15. Secrets

- **Never commit secrets.** Period.
- Real secrets live in `.env` (gitignored). Placeholders go in `.env.example`.
- Validate secret format at startup — fail loudly if missing or obviously fake.
- Rotate any secret that hits the wrong file. Use `git filter-repo` or BFG to scrub history if needed.
- Consider adding a pre-commit secret scanner like `gitleaks` (`.gitleaks.toml` in repo root).

---

## 16. Self-check before finishing a task

Before claiming work complete, verify:

**Universal (every shape):**

- [ ] `STRATEGY.md` is filled in and reflects the current strategy (problem, inputs, outputs, metric, out-of-scope).
- [ ] No hardcoded paths (`/home/...`, `~/...`, `/Users/...`) in committed code.
- [ ] No personal info, hostnames, or operator-specific values in committed code.
- [ ] Docker container has `mem_limit` and (if relevant) `cpus`.
- [ ] DB connections use a pool, not per-request.
- [ ] HTTP calls have explicit timeouts.
- [ ] Performance timing logs (`[<project>-perf]`) on all I/O and multi-step phases.
- [ ] `<qa_file>` exists, has shape-appropriate checks (see §6), and passes in CI.

**Service / worker / notebook (shapes that bind a port):**

- [ ] Service binds to `127.0.0.1`, not `0.0.0.0` (§2).
- [ ] `/health` endpoint exists and returns 200 when healthy (**service**) **OR** heartbeat file pattern in place (**worker**).

**Analysis / backtest / report / pipeline (one-shot shapes):**

- [ ] Success sentinel file (`results/metrics.json` or `outputs/manifest.json`) written LAST by the entry point, only on successful completion.
- [ ] Required artifact files documented in `<qa_file>` and verified to exist + non-empty.
- [ ] Project runs to completion against committed `fixtures/` with no external data required (so CI works).
- [ ] Real data path is controlled by a single env var (e.g. `DATA_PATH`) documented in `.env.example`.
- [ ] `outputs/` is gitignored; operator runs produce artifacts locally, CI uploads them as pipeline artifacts.
- [ ] No secrets in code or `.env` files committed.
- [ ] `.env.example` documents every required variable (including any new ones).
- [ ] `make setup && make run && make qa` works on a fresh clone.
- [ ] `.gitlab-ci.yml` pipeline passes end-to-end (lint, secret-scan, build, e2e test — §9.5). If you can't run it remotely, reproduce the `build` + `test` steps locally via the commands in §9.5.
- [ ] `git status` clean of untracked junk before pushing.

**Documentation (§7) — required, not optional:**

- [ ] `README.md` updated if user-visible behavior, quickstart, or env vars changed.
- [ ] `docs/API.md` (or OpenAPI spec) updated for every endpoint added/removed/changed, including request/response schemas and error codes.
- [ ] `docs/SETUP.md` updated if install steps, dependencies, or configuration changed.
- [ ] `docs/ARCHITECTURE.md` updated if a module was added, removed, or significantly refactored.
- [ ] `CHANGELOG.md` has an `## [Unreleased]` entry for this change.
- [ ] Every new exported function/class has a docstring with purpose, params (with units), return, raises, and at least one edge case or precondition.
- [ ] Non-obvious logic has inline `# Why:` comments.
- [ ] Edge cases (empty input, unicode, oversized payload, concurrent access, network/auth failure) are documented at the branch that handles them — or explicitly marked out-of-scope.
- [ ] Examples in the docs (curl calls, code snippets, commands) have been verified to still run against the current code.
- [ ] No doc references to removed/renamed functions, endpoints, or env vars (grep for the old name across `docs/`).

---

## 17. KPI tracking — measure everything that matters

Every project ships with `kpi.json` declaring the KPIs to track. **Goal:** drive data-driven decisions. Every change should be evaluated against numerical KPIs — never ship a "feels faster" optimization without proof.

### Minimum KPIs every project tracks — by shape

`qa_score` (qa_check pass ratio) is tracked by every shape. The other defaults depend on the shape:

| Shape | Default KPIs (shipped in `kpi.json`) |
|---|---|
| `service` | `health_up`, `health_latency_ms`, `qa_score` |
| `worker` | `heartbeat_fresh`, `jobs_completed_per_min`, `job_error_rate`, `p99_job_duration_ms`, `qa_score` |
| `analysis` | `last_run_success`, `output_freshness_s`, `row_count`, `run_duration_ms`, `qa_score` |
| `backtest` | **`win_rate`**, `sharpe_ratio`, `max_drawdown_pct`, `total_return_pct`, `trades_count`, `qa_score` |
| `report` | `last_build_success`, `pdf_size_bytes`, `build_freshness_s`, `build_duration_ms`, `qa_score` |
| `notebook` | `notebooks_passing`, `notebooks_failing`, `qa_score` |
| `pipeline` | `last_run_success`, `final_row_count`, `p99_stage_duration_ms`, `run_freshness_s`, `qa_score` |

Beyond the defaults, **track what's specific to YOUR project's success**:

- **API service:** request rate, p50/p95/p99 latency by endpoint, 4xx/5xx rate, queue depth, in-flight connections, downstream dependency latency
- **Worker / batch:** jobs completed/min, average job duration, failure rate, queue lag (oldest pending job age), retries
- **ML / inference:** tokens/sec, time-to-first-token, GPU utilization %, VRAM used, prompt cache hit rate, model swap rate
- **Database service:** queries/sec, slow query count, lock waits, connection pool utilization, replication lag
- **Scraper / crawler:** pages/min, bytes downloaded, parse errors, dedup ratio, robots.txt rejections
- **Analysis / backtest / report:** domain-specific accuracy, win rate, model score, cost per output, hallucination rate, quality judge score
- **Cost-sensitive:** $/request, tokens spent today, API quota remaining

**Be specific.** "Speed" is not a KPI. "p99 latency of POST /v1/embeddings under 200ms" is.

### kpi.json schema

```json
{
  "project": "<name>",
  "kpis": [
    {
      "name": "p99_latency_ms",
      "kpi_type": "gauge",
      "unit": "ms",
      "direction": "lower",
      "target": 200,
      "interval_s": 60,
      "source": {
        "type": "metric_log_grep",
        "log_file": "logs/<name>.log",
        "pattern": "duration_ms=(\\d+)",
        "window_s": 300,
        "aggregate": "p99"
      },
      "description": "p99 request latency over the last 5 minutes"
    }
  ]
}
```

The schema is consumed by an external collector (operator-specific). The `kpi.json` itself is portable — it just declares what to track. How it gets collected and visualized is up to the deployer.

### Setting targets

For every KPI, set a `target` value. Targets force you to commit to what "good enough" looks like. A target you constantly miss → either the target is wrong (raise the bar) or the project has a problem. A target you always hit easily → tighten it.

---

## 18. Autonomous iteration — autoresearch

The project ships an autoresearch loop config at `AUTORESEARCH.md` and a metric script at `metric.sh`. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), the loop iterates: **modify → measure → keep/discard → repeat** until a goal is reached or stopped.

- `metric.sh` — single-script ground-truth scoring. Prints a float to stdout. Defaults to `<qa_file>` pass rate.
- `AUTORESEARCH.md` — defines Goal, Scope, Metric, Direction, Verify gates.
- `results.tsv` — gitignored experiment log.
- `STOP_AUTORESEARCH` — touch this file to halt the loop after the current iteration.

The loop runs against a separate `autoresearch/<date>` git branch — `main` is never touched. Each kept iteration is its own commit. When done, `git diff main..autoresearch/<date>` shows what improved.

The runner is operator-specific (lives outside the repo). The repo just ships the config files so any compatible runner can iterate on it.

---

## 19. License & contribution

- Default license is **MIT** unless the operator chooses otherwise. The `LICENSE` file is committed.
- `CONTRIBUTING.md` documents how external contributors should engage: branch naming, PR template, code style, where to discuss.
- Issues and PRs should reference the relevant KPI if performance or behavior is changing.

---

## 20. When in doubt

- Read `README.md` first.
- Look at how similar functions/files in the repo are written and match their style.
- Prefer fewer dependencies over convenience.
- Smaller, more focused PRs over large ones.
- Ask in the project's discussion channel rather than guessing.

---

## 21. Branding and internationalization

**Every scaffolded project ships with two universal directories — `brand/` and `locales/` — that serve as the single source of truth for visual identity and translations.** Shapes that produce user-facing output (webapp, report, optionally service) consume them; headless shapes (worker, analysis, backtest, notebook, pipeline) ship them as stubs for future use.

### `brand/` — the brand kit

```
brand/
├── config.json       # colors, fonts, logo paths, contact info, legal
├── logo.svg          # primary logo (light backgrounds)
├── logo-dark.svg     # dark-mode variant
├── favicon.svg       # favicon / app icon
├── wordmark.svg      # text-only logo
├── assets/           # additional brand imagery (OG images, screenshots, patterns)
└── README.md         # how to override, what reads this directory
```

`brand/config.json` is the **schema-checked contract** between the brand kit and every shape that reads it. Required top-level fields:

| Field | Type | Purpose |
|---|---|---|
| `name` | string | Canonical project slug (kebab-case) |
| `display_name` | string | Human-friendly name used in titles, emails, footer |
| `tagline` | string | One-line marketing tagline |
| `colors` | object | `primary`, `secondary`, `accent`, `text`, `background`, `border`, etc. |
| `fonts` | object | `heading`, `body`, `mono` — CSS font-family strings |
| `logo` | object | `light`, `dark`, `favicon`, `wordmark`, `alt_text` (paths relative to repo root) |
| `contact` | object | `email`, `url`, `twitter`, `github`, `support_email` |
| `social` | object | `og_image`, `og_title`, `og_description` for social previews |
| `legal` | object | `company_name`, `copyright_year`, `terms_url`, `privacy_url` |

### White-labeling via `BRAND_CONFIG_PATH`

**Do not fork the repo to rebrand.** Operators point the `BRAND_CONFIG_PATH` env var at their own `brand/` directory and the project picks it up:

```bash
export BRAND_CONFIG_PATH=/path/to/acme-brand/config.json
docker compose up -d
```

This keeps the upstream public and lets the same scaffold serve multiple customers with different branding.

### Which shapes consume `brand/`

| Shape | How it reads `brand/` |
|---|---|
| `webapp` | Vite reads `brand/config.json` at build time → injects CSS variables into every page + replaces `__BRAND_TITLE__`/`__BRAND_TAGLINE__`/`__BRAND_FAVICON__` in `index.html`. At runtime, Fastify serves `/api/brand` so hot-swapping via a volume mount works without a rebuild. |
| `report` | `generate_report.py` loads `brand/config.json`, passes it as Jinja2 `brand` variable to `content/report.md`, and injects colors/fonts into Pandoc `-V` vars for the PDF title page + xelatex link colors. The generated `_brand.css` is also included in HTML outputs. |
| `service` | Optional — if the service renders HTML emails, landing pages, or error pages, load `brand/config.json` and pass it to the template engine. |
| `backtest` | Optional — `matplotlib` can pick up `brand.colors.primary` for equity curves and `brand.fonts.body` for axis labels. Nice to have; not mandatory. |
| `worker`, `analysis`, `notebook`, `pipeline` | Ship as stubs; most won't use them, but the directory is there if you later add reports or dashboards. |

### `locales/` — translation keys

```
locales/
├── en.json          # primary (required)
├── es.json          # example second language
├── <ISO>.json       # one file per supported language
└── README.md        # how to add a language
```

Keys are **namespaced** (not flat), matching the i18next convention:

```json
{
  "app": { "title": "...", "welcome": "Welcome to {{name}}" },
  "nav": { "home": "...", "about": "..." },
  "actions": { "submit": "...", "cancel": "..." },
  "errors": { "not_found": "..." },
  "footer": { "copyright": "© {{year}} {{company}}" }
}
```

- **Interpolation**: `{{var}}` double-braces — works in both `react-i18next` (frontend) and Jinja2 (reports).
- **Pluralization**: i18next plural keys — `item_one` / `item_other`.
- **HTML in values**: avoid. If unavoidable, suffix the key `_html` and render via `<Trans>` or `{{{triple-braces}}}`.

### Which shapes consume `locales/`

| Shape | How |
|---|---|
| `webapp` | i18next loads `locales/<lang>.json` via `i18next-http-backend` at runtime. Language is detected from URL (`?lang=es`) → browser → localStorage → default (en). Marketing links can pin a language with the query param. |
| `report` | `generate_report.py` loops over every `locales/*.json` and produces `outputs/report_<lang>.pdf`, `report_<lang>.html`, `slides_<lang>.html`, `summary_<lang>.xlsx` per language. Set `BUILD_LANGS=en,es` to limit for faster iteration. |
| `service` | Optional — if the service returns localized error messages, load based on `Accept-Language` header. |

### Documentation translation

Two patterns are supported; pick one:

- **Primary + translations**: `README.md` is primary (English). Add `README.es.md`, `README.de.md`, etc. Each translation opens with a link back to the primary.
- **`docs/<lang>/` subdirs**: `docs/SETUP.md` is primary at the top of `docs/`. Translations live at `docs/es/SETUP.md`, `docs/de/SETUP.md`, etc.

Translation is a **separate workflow** from development. The project ships `scripts/translate_docs.sh` which wraps an operator-supplied backend:

```bash
# Local LLM via an OpenAI-compatible endpoint (Ollama, llm-router, vLLM, ...)
TRANSLATOR=local-llm OPENAI_BASE_URL=http://127.0.0.1:11436/v1 TARGET_LANG=es \
    ./scripts/translate_docs.sh README.md README.es.md

# OpenAI API
TRANSLATOR=openai OPENAI_API_KEY=sk-... TARGET_LANG=de \
    ./scripts/translate_docs.sh locales/en.json locales/de.json

# DeepL
TRANSLATOR=deepl DEEPL_API_KEY=... TARGET_LANG=fr \
    ./scripts/translate_docs.sh docs/SETUP.md docs/fr/SETUP.md

# Manual (opens $EDITOR for human translation)
TRANSLATOR=manual TARGET_LANG=ja \
    ./scripts/translate_docs.sh docs/API.md docs/ja/API.md
```

The `scripts/translate_docs_impl.py` backend:
- Preserves markdown formatting and interpolation variables (`{{name}}`)
- Validates JSON output when translating `locales/*.json`
- Refuses DeepL for JSON files (DeepL doesn't preserve structure)
- Fails loudly if the configured `$TRANSLATOR` backend's env vars are missing

**Translation drift is not a build-blocker** — features land in English first and translations catch up later. CI warns (not fails) when translated locale files lag behind `en.json`.

### Rules

- **`en.json` is the source of truth.** All other `locales/*.json` files derive from it. If you add a key, add it to `en.json` first; translations follow.
- **Never hardcode user-facing strings in the frontend.** Every string must come from `useTranslation()` / `t('namespace.key')`. CI lint can catch this with an ESLint rule (opt-in).
- **Never hardcode colors, fonts, or logos in component code.** Read them from the brand CSS variables or `useBrand()`. Hardcoded values defeat white-labeling.
- **The brand kit ships with placeholder assets.** Replace `brand/logo.svg`, `brand/favicon.svg`, etc. with your real assets before public launch. The scaffold's defaults are generic placeholders, not your brand.
- **Bump `CHANGELOG.md`** on brand changes — users notice.
- **Don't commit translated docs that lag behind the primary by more than a minor version** without a warning banner at the top of the translated doc.

---

## 22. Project RAG + IRC bot

Every scaffolded project ships with **its own RAG index and its own IRC bot**. The bot is the agent that manages the project day-to-day: it answers questions about the codebase, watches for KPI changes, queries operator services for context, consults other bots for cross-cutting expertise, and dispatches coding agents (Cursor, Claude Code, Aider) when changes are required.

### `rag/` — the project's knowledge index

```
rag/
├── config.yml          # what to index, chunk size, backend
├── index.py            # indexer (walks project, chunks, embeds)
└── README.md
```

**What gets indexed** (defaults, customizable in `config.yml`):

- `README.md`, `STRATEGY.md`, `AGENTS.md`, `CHANGELOG.md` — project-level docs
- `docs/**/*.md` — long-form documentation
- `content/**/*.md` — report-shape content
- `kpi.json`, `locales/*.json`, `brand/config.json` — structured metadata
- Source code: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.sh`, `.sql`

**Two backends, selected via `RAG_BACKEND`:**

| Backend | When | Requires |
|---|---|---|
| `sqlite` (default) | Fresh clones, no infrastructure. Built on SQLite FTS5 — keyword-only, no embeddings. | Nothing |
| `remote` | Operator has a shared vector DB running. Gets semantic search via a dedicated collection `proj_<name>_code`. | `VECTOR_DB_URL` |
| `both` | Belt-and-suspenders — remote primary, SQLite fallback. | `VECTOR_DB_URL` |

**Incremental re-indexing** is cheap — `rag/index.py --incremental` hashes each file and skips unchanged ones. Run from the autoresearch loop, CI (non-blocking), and/or a cron/systemd timer on the operator side.

### `bot/` — the project's IRC agent

```
bot/
├── config.yml                 # channel, nick, tools, LLM, watch paths
├── bot.py                     # IRC client + tool-calling loop
├── requirements.txt
├── Dockerfile
├── docker-compose.bot.yml     # compose overlay: merge with main compose
├── README.md
├── tools/                     # each tool is a Python module with call(query, ctx)
│   ├── local_rag.py
│   ├── capability_broker.py
│   ├── remote.py
│   ├── memory_archive.py
│   ├── ask_agents.py          # asks bots in #agents
│   ├── ask_advisor.py         # asks the design advisor in #devs
│   └── dispatch_agent.py      # spawns coding agents
└── runners/                   # example coding-agent runners
    ├── cursor.sh
    ├── claude_code.sh
    ├── aider.sh
    └── custom.sh
```

### Identity + channel convention

- **Channel**: `#<name>` (override via `IRC_CHANNEL`) — slug matches the project directory, the Gitea URL prefix, and the memory/pr_reviews scope
- **Nick**: `<name>-bot` (override via `IRC_NICK`)
- **Peer channels the bot references** (but does not own):
  - `#agents` — subject-matter-expert RAG bots run by the operator (crypto, security, ML, law, etc.)
  - `#devs` — where the **design advisor** lives: a code-index-backed advisor with call graphs, execution flows and impact analyses for every indexed project. It can advise on this app's architecture *and* surface reusable patterns from the operator's other projects.

Each project gets a unique channel + unique bot name derived from the project slug. When operators run multiple projects on the same IRC network, they get N isolated channels automatically.

### Tool-calling loop

1. User mentions the bot: `<name>-bot: how's the win rate trending?`
2. Bot runs an LLM chat call (operator-configured endpoint via `LLM_ROUTER_URL`) with a system prompt containing compact project context + the list of available tools
3. LLM decides which tool (if any) to call and what to ask it
4. Bot executes the tool, feeds the result back to the LLM
5. Repeat up to `llm.max_iterations` (default 6) until the LLM produces a final answer
6. Bot posts the answer to IRC (word-wrapped to fit IRC line limits)

Every tool call emits a `[<name>-perf] phase=tool_<name> duration_ms=N` log line for auditability (AGENTS.md §8).

### Tool reference

| Tool | What it does | When LLM should use it |
|---|---|---|
| `local_rag` | Query the project's own RAG (vector DB or SQLite) | First port of call for any project-specific question |
| `capability_broker` | Call brokered data functions | Live operator-side data (stack health, dashboards, DB queries) |
| `remote` | Direct queries to vector collections outside this project | Cross-project code search, historical conversation indexes |
| `memory_archive` | Query the verbatim memory archive | "What did we decide about X", prior errors, past conversations |
| `ask_agents` | Post to `#agents`, wait briefly for SME bot replies | Cross-cutting domain expertise the project RAG lacks |
| `ask_advisor` | Post to `#devs`, wait for the design advisor's reply | Design-pattern advice, this app's architecture, cross-referencing patterns from the operator's other projects, blast-radius questions |
| `dispatch_agent` | Spawn a coding agent on a throwaway branch | When the task requires writing/changing code |

**Tools with unsatisfied `requires_env` (in `config.yml`) are skipped at startup with a warning.** A fresh clone with no operator infrastructure will still have `local_rag`, `ask_agents`, and `ask_advisor` loaded — the rest enable themselves when their env vars appear.

### Dispatching coding agents

When the LLM decides a task needs code changes, it calls `dispatch_agent` with a task description. The tool:

1. Creates a throwaway git branch (`bot/<slug>-<timestamp>`) on the host
2. **Launches a hard-isolated Docker sandbox** (see below) and runs `$AGENT_COMMAND` inside it
3. Caps concurrency at `$AGENT_MAX_CONCURRENT` (default 3) to prevent runaway forking
4. Times out after `$AGENT_TIMEOUT_S` (default 1800s / 30 min) per agent
5. Captures stdout/stderr to `logs/agent-<branch>.log` for later review
6. Returns a one-line summary with the branch name, diff stats, and log path
7. **Never auto-merges.** Humans always review the branch before merging.

**Operator picks the runner** via `$AGENT_DISPATCHER` + `$AGENT_COMMAND`. Example runners ship in `bot/runners/`:

```bash
# Cursor
AGENT_DISPATCHER=cursor
AGENT_COMMAND=./bot/runners/cursor.sh

# Claude Code
AGENT_DISPATCHER=claude-code
AGENT_COMMAND=./bot/runners/claude_code.sh

# Aider
AGENT_DISPATCHER=aider
AGENT_COMMAND=./bot/runners/aider.sh

# Custom — copy runners/custom.sh and edit
AGENT_DISPATCHER=custom
AGENT_COMMAND=./bot/runners/my_runner.sh
```

Each runner receives the same three env vars (`TASK`, `BRANCH`, `PROJECT`) — the contract is deliberately thin so operators can wire in whatever agent infrastructure they have.

### Sub-agent sandbox — hard isolation required

**Dispatched sub-agents are NOT trusted.** They are LLM-driven and can be fooled, hallucinate, or be prompt-injected into reading credentials, touching unrelated projects, or exfiltrating data. To bound the blast radius:

**Every dispatched sub-agent runs inside a locked-down Docker container** with the following properties:

- **Only the project root is mounted** (as `/workspace`, writable). Nothing else — no `$HOME`, no sibling project directories, no SSH keys, no `~/.aws`, no `~/.kube`, no `~/.docker`, no operator config files.
- **`--network=none` by default.** Sub-agents have zero outbound network access. If the agent needs to call an LLM, the operator either (a) bakes a local model into the sandbox image, (b) opens a restricted bridge network, or (c) proxies through the bot (future work).
- **`--read-only` rootfs** with only `/tmp` and `/workspace/.agent-home` as writable tmpfs mounts.
- **`--cap-drop=ALL`** + `--security-opt=no-new-privileges` — all Linux capabilities dropped.
- **CPU + memory caps** (`AGENT_SANDBOX_CPUS`, `AGENT_SANDBOX_MEMORY`, defaults 2 cpus / 2g) prevent resource exhaustion.
- **`--pids-limit=256`** — no fork bombs.
- **Env var whitelist**: only vars in `AGENT_SANDBOX_FORWARD_ENV` are forwarded (default: LLM provider keys only). Every other operator secret is stripped.

**The sandbox image** must contain the coding agent CLI the operator picked (Cursor, Claude Code, Aider, etc.) plus git and a minimal runtime. Operators build it once:

```bash
# Example: Cursor sandbox image
cat > sandbox.Dockerfile <<'EOF'
FROM alpine:latest
RUN apk add --no-cache git bash curl
# Install the coding agent CLI of your choice here.
# Example for a hypothetical cursor-agent binary:
# RUN curl -L https://... -o /usr/local/bin/cursor-agent && chmod +x /usr/local/bin/cursor-agent
EOF
docker build -f sandbox.Dockerfile -t ghcr.io/you/agent-sandbox:latest .
```

Then in `.env`:

```bash
AGENT_SANDBOX=docker
AGENT_SANDBOX_IMAGE=ghcr.io/you/agent-sandbox:latest
AGENT_SANDBOX_NETWORK=none          # strict default
AGENT_SANDBOX_CPUS=2
AGENT_SANDBOX_MEMORY=2g
```

**Escape hatch:** `AGENT_SANDBOX=none` runs the runner directly on the host with no isolation. **This is only acceptable for local development.** The scaffold defaults to `docker`; disabling it is an explicit opt-out.

### How sub-agents get "advanced" capabilities (brokering via a capability broker)

When a sub-agent needs something that isn't in the project root — data from another project, an external API call, a database query, a cross-project pattern — it **does not reach out directly**. The network is off; the filesystem is bounded. Instead, the brokering flow is:

1. **Sub-agent emits a structured request** in its workspace or output — e.g., writes a `REQUEST.json` file or prints a `REQUEST:` line with the capability it needs.
2. **The orchestration bot** (i.e., the project's IRC bot, running OUTSIDE the sandbox) sees the request. The bot has the privilege set the sub-agent lacks: network access, operator credentials, broker access.
3. **The orchestration bot composes a brokered solution** to fulfill the request — either invoking an existing brokered data function or composing a new one and deploying it. The broker is the policy enforcement point: every privileged capability goes through it, so there's one audited place for access control.
4. **The orchestration bot writes the result back** into the sub-agent's workspace (e.g., `data/request-result.json`) and lets the sub-agent resume.
5. **Everything is logged.** The operator sees the request in IRC, reviews what new capability was exposed, and can revoke it.

**Why a broker and not just "give the agent internet"?**

- Sub-agents never see operator credentials. The bot holds them.
- Every request is visible in IRC for human approval before the bot fulfills it.
- Composing a brokered function is itself logged — the operator can audit and revoke exposed capabilities later.
- The sandbox stays strict; advanced access is mediated, not granted wholesale.

The sub-agent's system prompt should tell it: *"If you need to do anything beyond the project root — query other projects, call external APIs, access databases — do NOT try to reach out directly. Your network is off and your filesystem is bounded. Instead, write a REQUEST.json describing what you need, and the orchestration bot will handle it through the broker."*

### Running the bot

**Standalone (for development + debugging):**

```bash
pip install -r bot/requirements.txt
python3 bot/bot.py
```

**Alongside the main project (compose overlay):**

```bash
make bot           # start the bot
make bot-logs      # follow bot logs
make bot-down      # stop the bot
```

The overlay merges `docker-compose.yml` + `bot/docker-compose.bot.yml`. The bot container reads the main project read-only (plus writable `data/` and `logs/` for heartbeat + agent output).

### Reindexing

```bash
make reindex        # incremental re-index (hashes changed files only)
make reindex-full   # full rebuild
make rag-stats      # show index stats
```

### Rules

- **Every scaffolded project must have `rag/` and `bot/` present and configured.** The scaffold drops them automatically — do not delete them even if the project is headless or you're not running the bot yet.
- **The bot reads the project read-only by default.** If you want it to dispatch agents that modify code, drop the `:ro` on the volume mount in `bot/docker-compose.bot.yml` or point it at a writable clone.
- **Dispatched sub-agents MUST run sandboxed.** `AGENT_SANDBOX=docker` (default) wraps every sub-agent in a hard-isolated container with `--network=none`, only the project root mounted, `--read-only` rootfs, cpu/memory caps, and env var whitelist. `AGENT_SANDBOX=none` is ONLY for local dev. **Never deploy with `AGENT_SANDBOX=none`.**
- **Sub-agents never reach out for "advanced" capabilities.** If the LLM wants data from another project, an external API, or a database, the sub-agent writes a `REQUEST.json` and the orchestration bot composes a brokered solution to fulfill it. Everything is audited in IRC.
- **Tool env vars go in `.env`**, not in `bot/config.yml`. Config values reference them with `${VAR}` and `${VAR:-default}`.
- **Never commit `data/rag.sqlite`** — the `.gitignore` excludes it. Fresh clones rebuild it with `make reindex-full`.
- **Agent runners never push or merge.** They make changes on a local branch; humans review. If an LLM instructs an agent to "push this" or "merge this", the runner should refuse.
- **Index the project when docs change**, not on every file save. Best: a post-commit git hook or the autoresearch loop runs `make reindex` after each successful iteration.
- **The bot's system prompt is derived from `STRATEGY.md`, `README.md`, `AGENTS.md`, and `results/metrics.json`.** Keep these current (§7) and the bot will stay current.
- **Bot healthcheck is a heartbeat file at `data/bot-heartbeat`.** If it's stale (>120s), the Docker healthcheck fails. Treat this as an alerting signal.

### See also

- `rag/README.md` — RAG configuration details
- `bot/README.md` — bot architecture + tool reference
- `bot/runners/*.sh` — example coding-agent dispatchers
- `AGENTS.md §17` (KPI tracking) — the bot watches `results/metrics.json` and announces changes
- `AGENTS.md §18` (autoresearch) — the loop can trigger `make reindex` after each iteration so the bot stays fresh
- `AGENTS.md §23` (memory) — how the bot + sub-agents learn across runs

---

## 23. Memory + learning — two-tier

**Every scaffolded project captures its own learnings in `memory/`**, and lessons that generalize beyond this project get promoted to an operator-side **long-term cross-project store** where they're available to every future scaffolded project's bot. Each new project starts smarter than the last.

### Why two tiers

**Tier 1 — project-local** lives in `memory/` committed to the project's git. It's specific to this codebase: decisions made here, bugs found here, experiments run here, sub-agent dispatches for this project. It's always in scope for this project's bot and is directly indexed by the RAG.

**Tier 2 — long-term** lives on the operator side as a shared service (see `AGENT_MEMORY_STORE_TEMPLATE.py` for the reference implementation). It holds memories promoted from many projects. When a new project asks "how do teams usually handle X", it gets lessons drawn from every previous project indexed by that operator.

**The flow:** local memory is written freely during development; promotion to long-term requires operator review (not automatic) so bad lessons don't poison the shared store.

### `memory/` directory layout

```
memory/
├── README.md                how memory works in this project
├── SCHEMA.md                frontmatter + category reference
├── decisions/               ADRs (architectural decisions + why)
├── experiments/             autoresearch iteration outcomes (kept + discarded)
├── bugs/                    post-mortems with root cause + fix
├── feedback/                user feedback, reports, feature requests (anonymize!)
└── sub_agent_runs/          auto-captured outcomes from dispatch_agent
```

Every memory file is markdown with YAML frontmatter. See `memory/SCHEMA.md` in the scaffolded project for the full field reference.

**Minimum frontmatter:**

```yaml
---
name: Short descriptive title
id: "0042"              # 4-digit, auto-incremented per category
type: decision | experiment | bug | feedback | sub_agent_run
date: 2026-04-10
project: <name>
shape: service | worker | analysis | backtest | report | notebook | pipeline | webapp
lang: python | node
tags: [auth, fastify, rate-limit]
confidence: high | medium | low
outcome: success | failure | neutral | abandoned
promote: yes | no | pending
---
```

`confidence` controls trust — over-confident `high` memories poison the long-term store, so default to `medium` or `low` unless you've reproduced the lesson multiple times. `promote: pending` is the bot's way of saying "this might generalize, operator should review." `promote: no` keeps it local.

### What goes in each category

| Category | Write one when… | Example |
|---|---|---|
| `decisions/` | A non-obvious choice was made, with alternatives considered | "Use SQLite FTS5 not chromadb" |
| `experiments/` | Something was tried and the outcome is informative (including failures) | "SMA 50/200 crossover lost to buy-and-hold" |
| `bugs/` | A bug took more than 30min to diagnose or reveals a pattern | "Race in worker.py::pull_batch" |
| `feedback/` | External input: users, reviewers, stakeholders | "User reports PDF font broken on Linux" |
| `sub_agent_runs/` | Auto-populated by `dispatch_agent.py` after every dispatched sub-agent run | "cursor fixed off-by-one in backtest.py" |

### Who writes memories

1. **Humans** — just create markdown files in the right subdirectory, or use `make memory-new CATEGORY=decision NAME="fastify-vs-express"` which scaffolds the frontmatter.
2. **The orchestration bot** — has a `write_memory` tool. When the LLM decides something's worth capturing, it calls the tool with the category + title + body.
3. **Automation** — `dispatch_agent.py` writes a `sub_agent_runs/` memory after every dispatched sub-agent finishes. The autoresearch loop writes `experiments/` memories on kept iterations.

### Who reads memories — and when

**Orchestration bot** reads memories on every tool-loop iteration:

- `rag/index.py` indexes `memory/**` alongside code + docs, so the `local_rag` tool automatically surfaces relevant lessons
- Dedicated `read_memory_local` tool for structured queries (filter by category / tags / confidence / outcome)
- Dedicated `read_memory_longterm` tool for cross-project wisdom (queries operator's `MEMORY_STORE_URL`)

**Sub-agents** receive a **pre-flight memory brief** before running:

Before `dispatch_agent.py` launches the sub-agent, the bot compiles `memory/_relevant-for-<branch>.md` with the top few relevant memories from both project-local and long-term stores. The sandbox has the project mounted, so the sub-agent's runner reads this file as its first step. The example runners (`cursor.sh`, `claude_code.sh`, `aider.sh`, `custom.sh`) all check for this brief and prepend it to the task prompt.

After the sub-agent finishes, `dispatch_agent.py` writes `memory/sub_agent_runs/<nnnn>-<runner>-<slug>.md` capturing: task, runner, sandbox config, duration, outcome, diff stats, and a placeholder `## Lesson` section for a human to fill in. Successful runs are marked `promote: pending` so the operator can review and decide if the pattern generalizes.

### Promotion — project → long-term

**Local memories never auto-promote.** The operator reviews `pending` memories, strips project-specific details, sets `promote: yes` + honest `confidence`, then runs `make memory-promote` which POSTs each approved memory to `$MEMORY_STORE_URL/submit`.

The long-term store indexes into per-category, per-shape, per-lang remote collections:

- `agent_learnings_common` — every promoted memory
- `agent_learnings_category_decision|experiment|bug|feedback|sub_agent_run`
- `agent_learnings_shape_service|worker|analysis|backtest|report|notebook|pipeline|webapp`
- `agent_learnings_lang_python|node`

So a query "how do backtest projects handle drawdown" filters to `agent_learnings_shape_backtest` and returns memories from every backtest project that ever ran on this operator.

### Provenance stays intact

Every promoted memory keeps its `origin_project`, `shape`, `lang`, `confidence`, and submission timestamp as metadata. When a future bot retrieves it, the query result says: *"this lesson came from rsi-backtest 3 months ago, tagged high confidence, referenced by 5 other projects since."* That's traceability — bad lessons get unpromoted via `DELETE /memories/<id>` on the store.

### Commands

```bash
# Create a new memory file with frontmatter pre-filled
make memory-new CATEGORY=decision NAME="sqlite-vs-chromadb"

# List pending promotions (for operator review)
make memory-promote-list

# Push approved memories to the long-term store
make memory-promote

# Validate all memory files have required frontmatter
make memory-lint

# RAG picks up memories on next reindex
make reindex
```

### Hard rules

- **`memory/` is committed.** It's part of the project's history. Exception: `memory/_relevant-for-*.md` (pre-flight briefs) is gitignored — transient per-dispatch files.
- **Promotion requires operator review** (`promote: yes` is set by a human, not the bot). The bot can set `promote: pending` when it thinks a lesson generalizes.
- **Never commit secrets / named individuals / customer data in memory files.** `.gitleaks.toml` scans the directory. Anonymize feedback with `<customer-A>`, `<reviewer-B>`, etc.
- **Be honest about `confidence`.** Over-confident memories poison the long-term store. When in doubt, pick `medium` or `low`.
- **Failures are valuable.** Don't only capture successes. A clear "we tried X and it failed because Y" is often more valuable than "we did Z and it worked" because it prevents future agents from re-trying the same dead ends.
- **Sub-agent runs auto-capture.** Don't turn this off — it's the feedback loop that makes dispatch smarter over time.
- **Pre-flight briefs feed sub-agents past lessons.** Every runner in `bot/runners/` reads `memory/_relevant-for-<branch>.md` before executing. If you write a custom runner, do the same.

### Operator-side store (`AGENT_MEMORY_STORE_TEMPLATE.py`)

Ship as a single-file FastAPI service the operator runs somewhere accessible to all project bots. Endpoints:

- `POST /submit` — accept a memory for promotion (called by `make memory-promote`)
- `POST /query` — return top-K relevant memories (called by `read_memory_longterm` tool)
- `GET /recent` — recent high-confidence memories across all projects
- `GET /stats` — counts per category/shape/lang/project
- `DELETE /memories/<id>` — unpromote a bad memory
- `GET /health` — liveness probe

Uses SQLite FTS5 as the source of truth (works standalone, no external deps) plus optional vector-database and memory-archive backends for semantic search and verbatim storage. Configure via `VECTOR_DB_URL`, `MEMORY_ARCHIVE_URL`, `MEMORY_STORE_DB`, `MEMORY_STORE_API_KEY`. See the file header for deployment notes.

### See also

- `memory/README.md` + `memory/SCHEMA.md` — project-side documentation
- `bot/tools/write_memory.py`, `read_memory_local.py`, `read_memory_longterm.py` — bot tools
- `bot/tools/dispatch_agent.py` — pre/post-flight memory integration for sub-agents
- `AGENT_MEMORY_STORE_TEMPLATE.py` — operator-side reference service
- `AGENTS.md §22` (RAG + IRC bot) — how memories fit into the bot's tool-calling loop
- `AGENTS.md §18` (autoresearch) — iteration outcomes become experiment memories
- `AGENTS.md §24` (Gitea + PR workflow) — PR review outcomes become pr_review memories

---

## 24. Per-project Gitea + PR workflow

**Every scaffolded project ships its own Gitea container.** Dispatched sub-agents push their branches to this private git server, the orchestration bot opens a pull request via the Gitea API, and a **PR review agent** reads the diff + memory + design-pattern advice and either merges, requests changes, or rejects.

This turns agent dispatch from "trust the sub-agent's commits blindly" into a real code-review workflow — where every automated change is visible, diff-inspectable, and subject to an LLM-plus-human review gate before it lands on `main`.

### Layout

```
gitea/
├── docker-compose.gitea.yml    compose overlay, merge with docker-compose.yml
├── bootstrap.sh                first-run: create bot user + API token + repo
├── README.md                   operator guide
└── data/                       SQLite db + git repos + logs (gitignored)
```

### Why per-project?

Each project gets its own Gitea so:

- Branches, tokens, and review history stay isolated
- Starting/stopping a project also starts/stops its git server
- No operator-wide shared state to configure
- The whole ecosystem (main service + bot + gitea + memory + RAG) ships and tears down together

**Resource cost:** ~300MB RAM per idle Gitea container; `mem_limit: 1g` in compose. Operators who want to consolidate can skip `make gitea` and point every project's `GITEA_URL` at a shared upstream Gitea — the scaffold doesn't hardcode the URL, so both patterns work.

### First-run setup

```bash
# 1. Start the Gitea container
make gitea

# 2. First-time automation: create bot user, generate API token, create repo, push main
make gitea-bootstrap
```

`gitea/bootstrap.sh` is **idempotent** — safe to rerun. It:

1. Waits for Gitea HTTP to come up
2. Creates a bot user (`<name>-bot`) with admin privileges via `gitea admin user create` (inside the container)
3. Generates an API token with `write:repository,write:issue,write:user,read:user` scopes
4. Writes `GITEA_TOKEN`, `GITEA_URL`, `GITEA_OWNER`, `GITEA_REPO`, etc. to `.env`
5. Creates the project repo in Gitea via the API
6. Adds a `gitea` git remote to the project: `git remote add gitea http://<bot>:<token>@127.0.0.1:3030/<owner>/<repo>.git`
7. Pushes the current main branch to seed Gitea

### Day-to-day commands

```bash
make gitea              # start the container
make gitea-logs         # follow logs
make gitea-down         # stop (data preserved in gitea/data/)
make gitea-nuke         # WIPE gitea/data/ (destructive, prompts for confirmation)
make prs                # list open PRs via the bot's gitea tool
make review PR=42       # trigger the review agent on PR #42
```

### Public access via central Caddy reverse proxy

By default the Gitea container binds to `127.0.0.1` only (per §2). To make PRs browsable from anywhere and IRC links clickable, expose each project's Gitea through the operator's **central Caddy reverse proxy** using this convention:

```
https://<slug>-git.<your-public-domain>
```

Where `<slug>` is the project name — **the same slug used for the IRC channel (`#<slug>`) and the project directory**. One slug across IRC, filesystem, and web so everything about the project is addressable the same way. If you scaffold `rsi-backtest`, its IRC channel is `#rsi-backtest` and its Gitea is at `https://rsi-backtest-git.<your-domain>`.

**Every scaffolded project ships `gitea/caddy.example`** — a Caddyfile snippet the operator copies into the central `Caddyfile` and replaces `<GITEA_PUBLIC_DOMAIN>` with their actual dev zone. Example snippet:

```
<name>-git.<GITEA_PUBLIC_DOMAIN> {
    reverse_proxy 127.0.0.1:<GITEA_HTTP_PORT>
    encode gzip
    request_body { max_size 512MB }
    header_up Host {host}
    header_up X-Forwarded-Proto {scheme}
    log {
        output file /var/log/caddy/<name>-git.log
    }
}
```

### How to expose a project's Gitea

1. **Wildcard DNS**: `*.<your-public-domain>` → host IP (or one A record per project)
2. **Paste** the `gitea/caddy.example` snippet into your central `Caddyfile`, replace the placeholders
3. **Set `.env`** in the project:
   ```bash
   GITEA_PUBLIC_DOMAIN=your-dev-zone.example
   GITEA_PUBLIC_URL=https://<name>-git.your-dev-zone.example
   ```
4. **Reload Caddy** + **restart Gitea**:
   ```bash
   caddy reload --config ~/caddy-proxy/Caddyfile
   make gitea-down && make gitea
   ```

When `GITEA_PUBLIC_URL` is set, the compose overlay propagates it to Gitea's `ROOT_URL` so clone URLs, web links, and webhook payloads all use the public address instead of `http://127.0.0.1:3030`.

### Bot URL resolution

`bot/tools/gitea.py::pr_url(index)` picks the best available URL for any link it posts to IRC:

1. **`GITEA_PUBLIC_URL`** — full URL, takes precedence when set
2. **`https://<repo>-git.${GITEA_PUBLIC_DOMAIN}`** — zone-only convention, composed from the slug
3. **`GITEA_URL`** — localhost fallback for standalone dev

So a PR announcement in the project's IRC channel looks like `PR #42: ... https://rsi-backtest-git.your-dev-zone.example/rsi-backtest-bot/rsi-backtest/pulls/42` — clickable from any reviewer's workstation.

### Public-safe rule

**Real domains never appear in committed files.** Committed templates always use placeholders (`<GITEA_PUBLIC_DOMAIN>`, `<your-public-domain>`) and the real zone lives only in `.env` and `LOCAL.md` (both gitignored). `yala.sh` runs a leak check after bootstrap and warns on any committed file containing operator-specific hostnames.

The convention documented here does not commit the operator's zone — the **structure** is committed (`<slug>-git.<zone>`), the **value** is operator-specific.

### How sub-agents push their work

The flow changes in `dispatch_agent.py`'s post-flight step:

1. Sub-agent finishes (inside the sandbox, working on `bot/<slug>-<timestamp>` branch)
2. Orchestration bot (OUTSIDE the sandbox — it has the token) captures the sub_agent_run memory as before
3. **NEW:** If `GITEA_URL` is set and the agent made commits, the bot runs `git push gitea <branch>`
4. **NEW:** The bot opens a PR via `POST /api/v1/repos/<owner>/<repo>/pulls` with the task description in the body
5. **NEW:** The sub_agent_run memory is updated with the PR URL
6. **NEW:** If `GITEA_AUTO_REVIEW=true`, the bot immediately calls `review_pr(pr_number)` in-process

**Sub-agents never see `GITEA_TOKEN`.** The sandbox env var whitelist (`AGENT_SANDBOX_FORWARD_ENV`) does NOT include Gitea credentials. All push/PR operations happen outside the sandbox in the orchestration bot's process.

### The review agent (`bot/tools/review_pr.py`)

The review agent is a bot tool the LLM can call or the bot triggers automatically. It:

1. **Fetches** the PR metadata + full diff + file list from Gitea
2. **Finds the source task** by matching the PR's head branch against `memory/sub_agent_runs/` entries (if the PR was opened by dispatch)
3. **Gathers context** from other tools:
   - `read_memory_local` for project-specific prior lessons matching the task
   - `read_memory_longterm` for cross-project lessons (if the long-term store is configured)
   - `ask_advisor` in `#devs` for design-pattern advice if the diff touches multiple source files
4. **Runs an LLM review** with a strict system prompt:
   - Diff must align with the original task
   - Out-of-scope changes get flagged
   - Missing tests trigger `request_changes` (§6)
   - Missing doc updates trigger `request_changes` (§7)
   - Security smells (SQL injection, command injection, secrets in code, disabled TLS) trigger `reject`
   - When uncertain, `request_changes` is always preferred over `merge`
5. **Parses the LLM output** into: `verdict` (merge/request_changes/reject), `confidence` (high/medium/low), `rationale`, `feedback`
6. **Enforces the merge policy**: if `verdict=merge` but `confidence < $GITEA_AUTO_MERGE_CONFIDENCE` (default `high`), the verdict is downgraded to `request_changes` with a policy note. **Auto-merge only happens for high-confidence approvals.**
7. **Executes** the verdict via the Gitea API:
   - **merge**: posts an APPROVED review, then calls `merge_pr` (squash by default), then deletes the branch
   - **request_changes**: posts a REQUEST_CHANGES review with the feedback
   - **reject**: posts a COMMENT review and closes the PR (never force-deletes)
8. **Captures** the decision to `memory/pr_reviews/<nnnn>-<pr-number>-<slug>.md` for audit
9. **Returns** a one-line summary (verdict + action + PR URL + memory path)

### Verdict rules (strict)

| Verdict | When | Confidence gate | Action |
|---|---|---|---|
| `merge` | Diff matches task, tests added, docs updated, no security smells, no out-of-scope changes | Must be `high` (or whatever `GITEA_AUTO_MERGE_CONFIDENCE` requires) | squash-merge + delete branch + memory |
| `request_changes` | Scope drift, missing tests, missing docs, style issues, unclear intent — OR any merge downgraded by the confidence gate | Any | review comment + memory |
| `reject` | Security issue, fundamentally wrong approach, task misinterpreted beyond repair | Any | close PR + memory |

**Downgrade rule:** `merge` with `confidence < high` → `request_changes`. The bot never auto-merges medium/low confidence reviews. This is the single most important safety gate — it means the agent has to be *sure* before it lets code into `main`.

### Safety boundary

| Actor | Credentials | Can do |
|---|---|---|
| Orchestration bot (outside sandbox) | `GITEA_TOKEN`, `GITEA_BOT_PASSWORD`, `LLM_API_KEY`, full project write | Push branches, open/merge/close PRs, write memory, dispatch agents |
| Sub-agent (inside sandbox) | None | Edit files in `/workspace` only, no network |
| Review agent (in-process, called from bot) | Same as orchestration bot, but its LLM prompt forbids dispatching further sub-agents or editing files directly | Only: fetch PR, call LLM, post review, merge/close via API |

The review agent runs **in-process inside the orchestration bot** — not in a new sandbox and not as a separate container. It's a read-plus-approve tool, not a code-modification tool. It should never write to `/workspace`, never push new commits, never touch `main` directly. The only state it produces is the Gitea review action and the `memory/pr_reviews/` file.

### Config

```bash
# .env
GITEA_HTTP_PORT=3030
GITEA_SSH_PORT=2222

# Populated by gitea/bootstrap.sh on first run:
GITEA_URL=http://127.0.0.1:3030
GITEA_API_URL=http://127.0.0.1:3030/api/v1
GITEA_TOKEN=<bot-token>
GITEA_OWNER=<name>-bot
GITEA_REPO=<name>
GITEA_BOT_USER=<name>-bot
GITEA_BOT_PASSWORD=<auto-generated>

# Review agent behavior
GITEA_AUTO_REVIEW=false              # auto-trigger review after each dispatch
GITEA_AUTO_MERGE_CONFIDENCE=high     # min confidence for auto-merge
REVIEW_MAX_DIFF_CHARS=40000          # cap diff size sent to LLM reviewer
```

### Rules

- **`make gitea` + `make gitea-bootstrap` must be run once** before the bot can push dispatched branches. If Gitea isn't up and the bot tries to push, the dispatch still succeeds but the PR step fails gracefully (with a clear error in the summary) and the branch stays local for human review.
- **`GITEA_AUTO_MERGE_CONFIDENCE` never goes below `high` in production.** Lowering it means medium-confidence LLM reviews can auto-merge to `main`, which defeats the review gate.
- **Never commit `.env`** — it holds `GITEA_TOKEN` and `GITEA_BOT_PASSWORD`. The scaffold's `.gitignore` excludes it and `gitleaks` scans for leakage.
- **`gitea/data/` is gitignored** — it holds the SQLite DB + repos + logs. Backing it up is the operator's job.
- **The review agent never modifies files.** If a PR needs code changes, the review verdict is `request_changes` with actionable feedback — the human or a new dispatch handles the fix.
- **Every review lands in `memory/pr_reviews/`** as an audit trail. Review the agent's decisions periodically and unpromote any it got wrong.
- **Operators can disable auto-review** by setting `GITEA_AUTO_REVIEW=false` (the default). In that mode, PRs sit in Gitea until `make review PR=<n>` is run manually or a human asks the bot `@<name>-bot: review PR 42` in IRC.
- **The review agent can be disabled entirely** by unsetting `GITEA_URL` or `GITEA_TOKEN`. The scaffold degrades gracefully — dispatched agents just leave branches local like before.
- **If the review agent starts misbehaving**, flip `GITEA_AUTO_REVIEW=false`, audit `memory/pr_reviews/`, and revert problematic merges with `git revert`. The whole decision history is in the memory directory.

### Gitea Actions CI + pipeline self-awareness — §24.5

**Every scaffolded project ships a `.gitea/workflows/ci.yml`** alongside the existing `.gitlab-ci.yml`. The workflow uses GitHub-Actions-compatible syntax and runs on the optional per-project **act_runner** container (`gitea/act_runner:latest`). Because the runner mounts the host Docker socket, it starts only after the operator explicitly runs `make gitea-runner`.

The CI stages mirror the GitLab pipeline:
- **lint** — ruff / eslint (non-blocking on fresh scaffolds)
- **secret-scan** — gitleaks
- **build** — `docker build` the project image
- **test** — shape-appropriate end-to-end (hit `/health`, run `qa_check`, run unit tests, assert outputs exist, etc.)

Uploads shape-specific artifacts: `outputs/` for analysis / backtest / report / pipeline, `dist/` for webapp, etc.

**Bootstrap automatically generates the act_runner token** via `gitea/bootstrap.sh` step 5a. After `make gitea-bootstrap`, enable the trusted runner explicitly with `make gitea-runner`.

### Self-aware pipeline loop in `dispatch_agent.py`

After the dispatch-opened PR is pushed, the bot runs `watch_pipeline.py` which:

1. Polls Gitea Actions for the workflow run on the PR's head SHA
2. Waits up to `PIPELINE_WAIT_TIMEOUT` (default 600s) for the run to finish
3. On **success**: the summary includes `pipeline: success (N s)` and the review agent (if `GITEA_AUTO_REVIEW=true`) takes over
4. On **failure**: downloads the failed job logs, classifies the error (`lint` / `test` / `build` / `dependency` / `runtime` / `unknown`), writes `memory/pipeline_failures/<nnnn>-<pr-num>-<class>-<slug>.md` with the log tail
5. Checks the **circuit breaker**: reads `fix_attempts` from the root `sub_agent_run` memory frontmatter
6. If under `AUTOFIX_MAX_ATTEMPTS` (default 3): dispatches a new sub-agent with the failure details as the task, which recurses through the full flow (sandbox → commits → push → open new PR → watch pipeline again)
7. The new PR gets its own pipeline run; if IT passes, the review agent merges it; if IT fails, the circuit breaker increments and eventually stops
8. When attempts are exhausted: posts to IRC and stops — human intervention required

**The `fix_attempts` counter lives in the root sub_agent_run memory** so every new dispatch in the same chain shares one budget. Restart the root task (new IRC mention) to reset.

### Review agent pipeline + test_quality gates

`review_pr.py` enforces two hard gates that override the LLM's verdict:

1. **Pipeline gate**: if the Gitea pipeline is failing when the review runs, the verdict is forced to `request_changes` with high confidence and the failure report is cited in the rationale. There's no way to auto-merge a red pipeline.
2. **Test-quality gate**: `test_quality.py` scans changed test files and computes a 0.0-1.0 meaningfulness score. If `score < 0.8`, any `merge` verdict is downgraded to `request_changes` with the specific anti-patterns (tautologies, empty tests, mock-only tests, missing source coverage) cited.

Both gates happen in `_gather_context()` before the LLM is called, and again as post-LLM overrides. The LLM's system prompt is also instructed about both rules — but the code enforces them regardless of whether the LLM plays along.

### Pipeline classification heuristics

`watch_pipeline.py`'s `classify_failure()` runs the downloaded logs through regex patterns to categorize the failure:

- **lint**: `ruff.*error`, `eslint.*error`, `E\d{3}:`, `format.*would.*rewrite`
- **test**: `FAILED.*test_`, `AssertionError`, `\d+ failed.*in \d+\.\d+s`, `tests? failed`, `expect(.*).to`, `not ok`
- **build**: `docker build.*failed`, `failed to solve`, `Cannot find module`, `No module named`, `gcc.*error`
- **dependency**: `package-lock.*out of sync`, `ERESOLVE`, `Could not find a version`, `pip install.*ERROR`
- **runtime**: `Traceback`, `Unhandled.*exception`, `segmentation fault`, `OOMKilled`
- **unknown**: catches the rest

The classification drives the memory file name and the tags on the `pipeline_failures` entry, so later queries like `read_memory_local category=pipeline_failure tags=test` return targeted results.

### Rules

- **Every project MUST have `.gitea/workflows/ci.yml`** committed. The scaffold drops it; do not delete it.
- **Every coding-agent runner MUST run `make test` before declaring success.** All shipped runners (cursor, claude_code, aider, custom) do this; custom runners must follow suit.
- **`AUTOFIX_MAX_ATTEMPTS` should be ≥ 1 and ≤ 5.** Zero disables autofix (you get manual "your pipeline failed" alerts instead). More than 5 risks runaway fix loops.
- **`fix_attempts` is reset only by starting a new root task** — editing the memory frontmatter bypasses the circuit breaker, which is an intentional escape hatch for operators who need to unblock a stuck loop.
- **Pipeline failures that are flaky (infra / runner / network) should be classified as `unknown` and marked `promote: no`** after the operator investigates. Don't let flaky failures poison the long-term memory store.
- **`review_pr.py` waits up to `PIPELINE_WAIT_TIMEOUT` for a pipeline.** If it times out, the verdict is forced to `request_changes` because we can't confirm green. Operators whose runners are slow should raise the timeout, not lower the gate.
- **Test-quality score gate is 0.8 for auto-merge.** Lowering this is an explicit choice and should be captured as a `decisions/` memory explaining why.

### See also

- `.gitea/workflows/ci.yml` — per-shape workflow file (dropped by scaffold)
- `gitea/docker-compose.gitea.yml` — includes `<name>-act-runner` service
- `gitea/bootstrap.sh` step 5a — generates Actions runner token
- `bot/tools/watch_pipeline.py` — pipeline polling + failure classification
- `bot/tools/test_quality.py` — test meaningfulness analyzer
- `bot/tools/review_pr.py` — pipeline + test-quality gates
- `bot/tools/dispatch_agent.py` — pipeline watcher + autofix loop
- `memory/pipeline_failures/` — CI failure audit trail
- `memory/sub_agent_runs/*.md` frontmatter `fix_attempts` — circuit breaker state

### See also

- `gitea/README.md` — per-project Gitea setup details
- `gitea/bootstrap.sh` — first-run automation script
- `bot/tools/gitea.py` — Gitea REST API client
- `bot/tools/review_pr.py` — LLM-based review agent
- `bot/tools/dispatch_agent.py` — pushes to Gitea and opens PRs after each dispatch
- `memory/pr_reviews/` — audit trail of every automated review
- `AGENTS.md §22` (RAG + IRC bot) — the bot that holds the Gitea token
- `AGENTS.md §23` (Memory + learning) — how review outcomes become memories

---

> **Operator-specific notes** (deployment paths, internal services, monitoring URLs, etc.) live in `LOCAL.md`, which is gitignored. Don't put any of that here.

<!-- scaffold:end -->

## Project-specific conventions

*(Anything below this line is yours and is never regenerated. Domain rules,
naming conventions the team has agreed, things that surprised someone once and
should not surprise anyone again.)*
