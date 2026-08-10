# Contributing to <name>

Thanks for taking the time to contribute. This project is open to issues and pull requests from anyone.

## Quickstart

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in any required values
3. Run `make doctor && make setup`
4. Run `make run`
5. Run `make test && make qa`

If the Docker-only test and QA targets pass on a fresh clone, you're good to
go. They do not install Python or Node packages on the host.

## Reporting issues

Please include:

- What you tried to do
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Docker version, relevant `.env` values with secrets redacted)
- Logs (`docker compose logs`)

## Pull requests

- Branch from `main`
- One logical change per PR
- Include tests when fixing a bug or adding a feature
- Update `README.md` if user-visible behavior changes
- Update `kpi.json` if you're tracking new metrics
- Run `make lint typecheck test qa` and confirm every target passes
- The PR description should answer: what changed, why, how was it tested

## Code conventions

This project follows the conventions in [`AGENTS.md`](AGENTS.md). Highlights:

- **Localhost only:** services bind to `127.0.0.1`, never `0.0.0.0`
- **No hardcoded paths or secrets:** everything via `.env`
- **Performance timing logs:** every I/O call emits `[<project>-perf] phase=X duration_ms=N`
- **Resource limits:** Docker containers always have `mem_limit`
- **Least privilege:** containers run non-root, drop capabilities, set
  `no-new-privileges`, and use read-only root filesystems
- **Connection pools:** never one DB connection per request
- **Health endpoint:** `/health` must work and reflect dependency status
- **No commits with secrets:** ever

Read `AGENTS.md` in full before submitting a non-trivial PR.

## Code of conduct

Be respectful. Disagree about the code, not the person. We're all here to ship something useful.
