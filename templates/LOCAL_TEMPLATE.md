# LOCAL.md — Operator notes (NOT committed)

> This file is **gitignored**. It contains environment-specific operational notes that should never be in the public repo. Use it for paths, hostnames, monitoring URLs, internal service references, and any operator workflow that depends on the host environment.
>
> Project conventions that apply to ANY contributor live in `AGENTS.md`. Anything in this file is unique to the operator's setup.

---

## Where this lives

- Project path: `<PROJECT_PATH>`
- Started: <DATE>

## Operator services this project integrates with

- **Caddy reverse proxy:** add a block to `<CADDY_CONFIG>` mapping `<name>.<domain>` → `127.0.0.1:<PORT>`
- **Gitea frontend via Caddy:** add a SECOND block mapping `<name>-git.<dev-zone>` → `127.0.0.1:${GITEA_HTTP_PORT}`. Copy the snippet from `gitea/caddy.example` into `<CADDY_CONFIG>`, replace `<GITEA_PUBLIC_DOMAIN>` with the operator's dev zone, reload Caddy. Then set `GITEA_PUBLIC_URL` in `.env` and restart Gitea (`make gitea-down && make gitea`) so `ROOT_URL` propagates. See AGENTS.md §24.
- **Capability broker auto-discovery:** picks up the service automatically once it's in Caddy and `/health` is live (every 5 minutes)
- **KPI collector:** the systemd `kpi-collector.service` reads this project's `kpi.json` every 60 seconds and writes values to the capability broker's Postgres
- **KPI dashboard:** `http://127.0.0.1:7133/dashboard?project=<name>`
- **Code index:** indexes this repo on the next analyze cycle
- **Memory archive:** mines this repo on the next mining cycle
- **code_index_sync:** embeds symbols/processes/clusters into the vector database hourly
- **autoresearch runner:** `python3 <SCRIPTS>/autoresearch_runner.py` from this directory
- **IRC channels:**
  - `#autoresearch-logs` — iteration progress posted here
  - `#index-logs` — index updates
  - `#hq` — the operations agent for queries
  - `#devs` — the design advisor bot (a local model + code-index RAG) for code questions

## Local commands I run

```bash
# Start the service
docker compose up -d

# Watch logs
docker compose logs -f

# Run autoresearch loop
make iterate-bg
tail -f autoresearch.log

# Stop the loop
make stop-iterate

# View KPIs
make dashboard
# or directly:
curl http://127.0.0.1:7133/dashboard?project=<name>

# Push to internal GitLab
git remote add gitlab git@gitlab-local:your-org/<name>.git
git push -u gitlab main
```

## Secrets in use

Secrets come from Vault. Never source `~/.secrets.env` directly.

- **Services:** wrap the start command with `vault-exec --secrets "VAR1 VAR2" -- <cmd>`
  (e.g. `vault-exec --secrets "OPENAI_API_KEY" -- docker compose up -d`)
- **Interactive / one-off:** run `secrets-load` first to populate the shell, then run the command.

Variables used by this project (fill in):

- TODO: list each env var, which Vault path it lives at, and what subsystem it talks to

## Known operator gotchas for this project

- TODO: anything specific to how this project runs in this environment

---

> When pushing this project public, this file is automatically excluded by `.gitignore`. If you ever need to share operator notes, copy them into a private wiki, never into AGENTS.md or README.md.
