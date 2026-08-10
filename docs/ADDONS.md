# Add-ons

The core scaffold produces a project that runs on its own. Add-ons wire it into
infrastructure that must **already exist** on your machine or network — which is
why none of them is on by default. Scaffolding your first project with
`--with-all` is the fastest way to be confused.

Add one when you have a reason, not in advance.

---

## `--with-bot` — project IRC bot

Adds `bot/`: a bot that joins an IRC channel, answers questions about the
project, and can dispatch coding agents (Claude Code, Cursor, Aider) to work on
it.

**You need:** an IRC server the bot can reach, and an LLM endpoint (local
Ollama, a router, or a hosted API key).

**Configure** in `.env`:

```bash
IRC_SERVER=127.0.0.1
IRC_PORT=6667
IRC_NICK=my-project-bot
IRC_CHANNEL=#my-project
IRC_NETWORK=irc-server_default     # DOCKER NETWORK name, not a hostname
LLM_ROUTER_URL=http://127.0.0.1:11434
```

`IRC_NETWORK` trips people up: it is the name of the Docker network your IRC
container is attached to. Find it with `docker network ls`. If it is wrong the
stack fails to start with `network irc_default declared as external, but could
not be found`.

**Run:** `docker compose -f bot/docker-compose.bot.yml up -d`

**Security:** agents dispatched by the bot run in `--network=none` containers
with only the project directory mounted. Read `bot/README.md` before enabling
anything that writes.

---

## `--with-gitea` — per-project git server

Adds `gitea/`: a self-hosted git server scoped to this one project, with CI
runners, so the project has its own review and pipeline without depending on a
central forge.

**You need:** Docker and two spare ports (web + SSH).

**Run:** `make gitea && make gitea-bootstrap` — starts the server and creates an
admin user and repository. The Actions runner is separate: `make
gitea-runner`.

The runner is disabled by default because it mounts the host Docker socket,
which grants host-level Docker control. Enable it only for trusted repositories,
workflow files, and actions.

Useful when a project should be independently hostable. Overkill if you already
push everything to one GitLab or GitHub.

---

## `--with-rag` — local document index

Adds `rag/`: indexes the project's own docs and source into a local vector
store so the bot (or you) can ask questions over them semantically.

**You need:** nothing, for the default backend. It uses SQLite FTS5, which
ships with Python — keyword search, no embeddings, nothing to run. An embeddings
model (a local Ollama one is enough) is only needed for the `remote` backend,
which adds semantic matching.

**Run:**

```bash
make reindex                      # build the index
make rag-search Q="how does auth work"
make rag-stats                    # files, chunks, backend
```

The index is a snapshot, not a live view — rebuild after the docs change.

Search is part of the add-on itself (`rag/index.py --search`), so `--with-rag`
is self-sufficient. The bot's `local_rag` tool uses the same index when both
add-ons are enabled, but you do not need the bot to query it.

Worth it once the docs outgrow what fits in an LLM context window.

---

## `--with-kpi` — metrics collector and dashboard

Adds `scripts/kpi_collector.py` and `scripts/kpi_dashboard.py`, which read
`kpi.json`, gather each metric on its interval, store the history, and serve a
dashboard with sparklines and percentiles.

**You need:** somewhere to store history (defaults to a local file; point it at
Postgres for a shared view).

Note `kpi.json` and `metric.sh` are written for **every** project regardless of
this flag — the declaration is always there. This add-on only supplies the
machinery that collects and displays them.

**Run:** `python3 scripts/kpi_collector.py` (usually under cron or systemd),
then `python3 scripts/kpi_dashboard.py`.

---

## Adding an add-on later

Add-ons are self-contained directories. To add one after the fact, scaffold a
throwaway project with the flag and copy the directory over:

```bash
cd /tmp && yala.sh tmp-addon --type service --with-bot
cp -r tmp-addon/bot ~/code/my-project/
rm -rf /tmp/tmp-addon
```

Then merge the relevant block from the throwaway's `.env.example` into your
project's, and re-read the add-on section above for what it needs.

## `--with-vault` — secrets from HashiCorp Vault

**You need:** a reachable, unsealed Vault with a KV v2 engine, and an AppRole
this project can authenticate as.

Replaces "copy `.env.example` to `.env` and paste your keys in" with:

```bash
make secrets-pull     # fetch every mapped secret into .env at mode 0600
make secrets-check    # verify each resolves — prints names, never values
make secrets-diff     # which local values differ from Vault, by key name
```

`vault/secret-map.tsv` maps `ENV_VAR → path → field` and **is committed** — it
holds names and paths, never values, so every change to what this project may
read shows up in a diff.

Design rules worth knowing before extending it:

- **Discovery is by environment variable** (`VAULT_ADDR`, `VAULT_ROLE`,
  `VAULT_KV_MOUNT`, `VAULT_CREDS_DIR`), never a hardcoded path. An absolute
  path into somebody's home directory works on one machine and makes the
  project unpublishable.
- **Fail-closed, never partial.** The whole file is built in memory and written
  only if every secret resolved. A half-written `.env` starts the service in a
  broken state that surfaces somewhere unrelated.
- **Sealed and unreachable are different errors**, because they have different
  fixes, and get different messages.
- **No value is ever printed** — not on success, not in an error, not under
  `set -x`. `make secrets-check` is safe to run in a screen share.
- **CI never authenticates to Vault.** Pipelines use their own injected
  variables. This is a workstation and deploy-host tool.

With `--with-vault` enabled, `make check-env` also cross-checks the secret map
against the config schema: a mapping for a variable nothing declares, or a
required variable with no mapping, fails the build.

Full setup walkthrough, including provisioning a least-privilege project-scoped
AppRole, is in the generated `vault/README.md`.

## `--with-monitor` — scheduled health and KPI prober

**You need:** somewhere to run it on a schedule (cron, a systemd timer, a CI
schedule).

```bash
make monitor    # probe once, now
```

Probes `/health` plus every KPI in `kpi.json` with an HTTP source, appending one
JSON line per run to `data/probes.jsonl`. Exits non-zero when any probe fails,
so `--quiet` under cron means silence when healthy and mail when broken.

This is a local smoke check, not real monitoring: no alerting, no
deduplication, no escalation. If you need those, use a hosted synthetic
monitoring service and keep this as the cheap local signal.

## `--with-review` — AI code review on merge requests

**You need:** an OpenAI- or Anthropic-compatible LLM endpoint and a token.
Anything speaking that protocol works, including a local vLLM or Ollama
server — which keeps your code on your own hardware.

Wires [OpenCodeReview](https://github.com/alibaba/open-code-review) (`ocr`)
into the pipeline. It reads the MR diff, sends changed files to the model, and
returns structured findings with file and line numbers.

```bash
make code-review                 # review the working tree
make code-review FROM=main       # review this branch against main
make code-review FAIL_ON=none    # report everything, never fail
```

Runs in a container, so no host Node install.

### The gate is the point

`review/gate.py` (ours, dependency-free) turns the JSON into a readable
summary and decides pass/fail. It defaults to failing **only on `critical`**.

That default is deliberate. An AI reviewer produces a lot of reasonable
low-severity opinion, and a job that goes red on all of it gets disabled
within a week — after which the critical findings stop being read too.
Failing on `critical` means red always means something, while everything else
is still printed and still in the artifact. Raise the threshold once you have
seen what your model actually produces on your codebase.

One deliberate detail: an **unrecognised severity ranks as high**, not low. A
new severity name introduced upstream makes the gate noisier rather than
silently letting findings through.

### Inline MR comments are opt-in

Set `OCR_POST_COMMENTS=true` and the job posts each finding as an inline
discussion on the line it refers to.

That needs upstream's GitLab publisher, which is **not vendored**.
`review/fetch_poster.sh` fetches it at a pinned release tag and verifies a
recorded SHA-256 first, writing a `NOTICE` recording source, version and
licence. Three reasons: it is Apache-2.0 and generated projects are MIT, so
the boundary stays explicit; a vendored copy goes stale silently while a
pinned fetch is a version number you can see; and code that runs in CI with an
API token in scope should not come from an unverified download. Requesting a
version with no recorded checksum fails closed.

Without it, the job still reviews the diff, prints every finding, uploads the
JSON artifact, and gates on severity — you just read findings in the job log
rather than on the MR.

### Cost and privacy

Every MR sends changed files to whatever `OCR_LLM_URL` points at. Know where
that is and what the provider retains before enabling it on anything
sensitive. The job triggers on merge request events only, not every push,
because reviews cost tokens per run and reviewing work-in-progress trains
people to ignore the output.

### What it is not

An LLM reading a diff finds real bugs and invents confident nonsense, in the
same output, with the same tone. Treat findings as suggestions from a
reviewer, not as results: `make test`, `make qa` and `make audit` are the
checks that actually know whether the code works.
