# Project RAG

This directory holds the project-specific **retrieval-augmented generation**
(RAG) setup. The project's IRC bot uses it to answer questions about this
codebase without needing to ingest everything into every LLM call.

## What gets indexed

See `config.yml`. The default set is:

- `README.md`, `STRATEGY.md`, `AGENTS.md`, `CHANGELOG.md` — project-level docs
- `docs/**/*.md` — everything under `docs/`
- `content/**/*.md` — for report-shape projects
- `kpi.json`, `locales/*.json`, `brand/config.json` — structured metadata
- Source code: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.sh`, `.sql`

Ignored: `.git/`, `.venv/`, `node_modules/`, `outputs/`, `dist/`, `state/`,
`results/`, `.env`, `LOCAL.md`, `data/rag.sqlite*`, plus everything in
`.gitignore`.

Adjust the `sources` and `ignore` lists in `config.yml` to fit your project.

## Backends

| Backend | When to use | Requires |
|---|---|---|
| `sqlite` | Default. No infrastructure. Ships with Python (FTS5 full-text search). Keyword-only — no semantic match. | Nothing |
| `remote` | You run a vector database. Semantic search across the project. Each project gets a dedicated collection so embeddings don't mix. | `VECTOR_DB_URL` set in `.env`, a reachable vector database |
| `both` | You have a vector database but want a local fallback when it is unreachable. | Same as `remote` |

Pick with the `RAG_BACKEND` env var (defaults to `sqlite`):

```bash
RAG_BACKEND=sqlite python3 rag/index.py           # local only
RAG_BACKEND=remote python3 rag/index.py           # vector DB only
RAG_BACKEND=both python3 rag/index.py             # both
```

## Commands

```bash
# Full (re)index — walks the project, writes every chunk
python3 rag/index.py

# Incremental — only re-embeds files whose content hash changed
python3 rag/index.py --incremental

# Stats — how many files and chunks are currently indexed
python3 rag/index.py --stats

# From the Makefile:
make reindex
```

## Where the bot reads from

Query it directly — the add-on is self-sufficient and does not need the bot:

```bash
make rag-search Q="how does auth work"
python3 rag/index.py --search "auth" --json    # machine-readable
```

The bot's `local_rag` tool reads the same index when both add-ons are enabled.
See `bot/tools/local_rag.py`; its tool loop calls `local_rag.call(query)`
which queries the same backend `config.yml` declares. If you switch backends,
both the indexer and the tool use the new backend consistently — no config
drift.

## Vector database API contract (reference)

The `index.py` remote integration is a **reference implementation** that
assumes:

1. `POST /collections` creates a collection. Body: `{"name", "dim", "embedding_model"}`. Returns 200/201 on success, 409 if it already exists.
2. `POST /collections/<name>/upsert` upserts chunks. Body: `{"items": [{"id", "text", "metadata"}, ...]}`. The server computes embeddings from `text`.
3. Collection name per project: `proj_<name>_code`

Adapt `remote_upsert()` in `index.py` to match your vector database's API
shape — the important part is the data model (chunks with `id`, `text`,
`metadata`), not the HTTP details.

## Keeping the index fresh

Recommended: run `make reindex` from the autoresearch loop, from the CI
pipeline (not blocking), and from a cron/systemd timer on the operator side.
The indexer is idempotent and incremental, so frequent runs are cheap.

For projects that generate a lot of new content (analysis/backtest/report
shapes with autoresearch loops), add a post-commit hook or a file watcher
that triggers `python3 rag/index.py --incremental`.
