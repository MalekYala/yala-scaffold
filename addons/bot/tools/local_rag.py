"""local_rag — semantic and full-text search over this project's code, docs, and strategy.

The bot's first stop for any question about how the project works. Reads
rag/config.yml to determine the backend (remote semantic or SQLite FTS5),
then queries it and returns a compact text summary for the LLM to reason over.

Query format:
  "<natural language question>"    — semantic or keyword search

Examples:
  "how does the health endpoint work"    -> matching code/doc snippets
  "what's the deployment strategy"       -> STRATEGY.md excerpts
  "rate limiting implementation"         -> relevant source code

Required environment:
  None — always loaded. Uses rag/config.yml to find the backend.

Error modes:
  - "(RAG not indexed — run 'make reindex')" — no rag/config.yml or empty index
  - "(vector DB unreachable)" — semantic backend is down (falls back to FTS5 if available)

Dependencies:
  pyyaml (optional — needed to read rag/config.yml)
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # tool will return an error if called without pyyaml


NAME = "local_rag"
DESCRIPTION = (
    "Semantic/full-text search over this project's code + docs + strategy. "
    "Use first for any question about how this project works, its modules, "
    "its strategy, or its metrics."
)

RAG_CONFIG_PATH = Path(os.environ.get("RAG_CONFIG", "rag/config.yml"))


def _expand_env(value):
    if isinstance(value, str):
        def repl(m):
            expr = m.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var, default)
            return os.environ.get(expr, "")
        return re.sub(r"\$\{([^}]+)\}", repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _load_config() -> dict | None:
    if yaml is None:
        return None
    if not RAG_CONFIG_PATH.exists():
        return None
    return _expand_env(yaml.safe_load(RAG_CONFIG_PATH.read_text()))


def _query_sqlite(db_path: Path, table: str, query: str, top_k: int) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        # FTS5 MATCH — sanitize the query to avoid syntax errors from user text
        safe_query = " ".join(w for w in re.findall(r"\w+", query)[:12])
        if not safe_query:
            return []
        rows = conn.execute(
            f"SELECT source_path, chunk_index, content, type FROM {table} "
            f"WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
            (safe_query, top_k),
        ).fetchall()
        return [
            {"source": r[0], "chunk": r[1], "content": r[2][:600], "type": r[3]}
            for r in rows
        ]
    except sqlite3.OperationalError as exc:
        return [{"error": f"sqlite query failed: {exc}"}]
    finally:
        conn.close()


def _query_remote(url: str, collection: str, query: str, top_k: int, min_score: float) -> list[dict]:
    try:
        import httpx
    except ImportError:
        return [{"error": "httpx not installed"}]
    try:
        r = httpx.post(
            f"{url.rstrip('/')}/collections/{collection}/search",
            json={"query": query, "top_k": top_k, "min_score": min_score},
            timeout=10,
        )
        if r.status_code >= 300:
            return [{"error": f"vector DB returned {r.status_code}: {r.text[:200]}"}]
        data = r.json()
        return [
            {
                "source": item.get("metadata", {}).get("source_path", "?"),
                "content": (item.get("text") or "")[:600],
                "score": item.get("score"),
            }
            for item in data.get("results", [])
        ]
    except Exception as exc:
        return [{"error": f"vector DB error: {exc}"}]


def _format_results(results: list[dict], backend: str) -> str:
    if not results:
        return f"(no results from {backend})"
    if len(results) == 1 and "error" in results[0]:
        return f"({backend} error: {results[0]['error']})"
    lines = [f"Top {len(results)} results from {backend}:"]
    for r in results:
        if "error" in r:
            lines.append(f"  ERROR: {r['error']}")
            continue
        src = r.get("source", "?")
        score = r.get("score")
        score_str = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
        content = (r.get("content") or "").strip().replace("\n", " ")
        lines.append(f"• {src}{score_str}: {content[:300]}")
    return "\n".join(lines)


def call(query: str, ctx: dict) -> str:
    cfg = _load_config()
    if cfg is None:
        return (
            "the RAG add-on is not installed in this project (no rag/config.yml), "
            "or pyyaml is missing. Re-scaffold with --with-rag, then run `make reindex`."
        )

    backend_type = cfg["backend"]["type"]
    top_k = cfg.get("retrieval", {}).get("top_k", 5)

    # Prefer remote if configured and reachable; fall back to sqlite
    if backend_type in ("remote", "both"):
        rv = cfg["backend"]["remote"]
        if rv.get("url"):
            min_score = cfg.get("retrieval", {}).get("min_score", 0.35)
            results = _query_remote(rv["url"], rv["collection"], query, top_k, min_score)
            if results and not (len(results) == 1 and "error" in results[0]):
                return _format_results(results, "remote")

    # SQLite path (default and fallback)
    sq = cfg["backend"]["sqlite"]
    db_path = Path(sq["path"])
    table = sq["fts_table"]
    results = _query_sqlite(db_path, table, query, top_k)
    return _format_results(results, "sqlite-fts5")
