#!/usr/bin/env python3
"""Project RAG indexer for <name>.

Walks the project (respecting .gitignore + rag/config.yml ignore patterns),
chunks files, and writes them to a RAG backend for later semantic or
full-text retrieval by the project's IRC bot.

Two backends:
    sqlite   — SQLite FTS5 full-text search. No external deps beyond
               Python stdlib. Ships with the project, works on any clone.
    remote — A self-hosted HTTP vector database. Uses a dedicated collection
               per project so bots get semantic search without polluting
               other projects' embeddings.

Set RAG_BACKEND=sqlite|remote|both to pick. Defaults to sqlite so fresh
clones work with zero infrastructure.

Usage:
    python3 rag/index.py                 # full index
    python3 rag/index.py --incremental   # only re-index changed files (by hash)
    python3 rag/index.py --stats         # show index stats, don't re-index
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Optional dependencies — fail with a friendly message if missing
try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


CONFIG_PATH = Path(os.environ.get("RAG_CONFIG", "rag/config.yml"))


def _expand_env(value):
    """Expand ${VAR} and ${VAR:-default} in strings, recursively for dicts/lists."""
    if isinstance(value, str):
        def _sub(s):
            import re
            def repl(m):
                expr = m.group(1)
                if ":-" in expr:
                    var, default = expr.split(":-", 1)
                    return os.environ.get(var, default)
                return os.environ.get(expr, "")
            return re.sub(r"\$\{([^}]+)\}", repl, s)
        return _sub(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    return _expand_env(raw)


def read_gitignore(root: Path) -> list[str]:
    """Return a list of .gitignore patterns. Used in addition to config ignore."""
    gi = root / ".gitignore"
    if not gi.exists():
        return []
    patterns = []
    for line in gi.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def should_ignore(path: Path, root: Path, ignore_patterns: list[str]) -> bool:
    rel = str(path.relative_to(root))
    for pat in ignore_patterns:
        # Directory pattern (ends with /)
        if pat.endswith("/"):
            if rel.startswith(pat) or f"/{pat[:-1]}/" in f"/{rel}/":
                return True
        # Simple fnmatch
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat):
            return True
    return False


def discover_files(config: dict, root: Path) -> list[tuple[Path, str]]:
    """Return [(abs_path, type), ...] for every file to index."""
    ignore = list(config.get("ignore", [])) + read_gitignore(root)
    seen: set[Path] = set()
    out: list[tuple[Path, str]] = []

    for entry in config.get("sources", []):
        kind = entry.get("type", "text")
        if "path" in entry:
            p = root / entry["path"]
            if p.exists() and p.is_file() and p not in seen:
                if not should_ignore(p, root, ignore):
                    out.append((p, kind))
                    seen.add(p)
        elif "pattern" in entry:
            for p in root.glob(entry["pattern"]):
                if not p.is_file() or p in seen:
                    continue
                if should_ignore(p, root, ignore):
                    continue
                out.append((p, kind))
                seen.add(p)
    return out


def chunk_text(text: str, max_chars: int, overlap: int, respect_headings: bool) -> list[str]:
    """Split text into overlapping chunks. If respect_headings is set and the
    text is markdown, try to align chunk boundaries with `##` / `###` headings.
    """
    if len(text) <= max_chars:
        return [text]

    if respect_headings:
        # Split on top-level headings; merge small sections back together
        import re
        parts = re.split(r"(?m)^(#{1,3} .+)$", text)
        # re.split gives us alternating [before, heading, after, heading, ...]
        # Reassemble as heading-aware chunks
        chunks = []
        buf = ""
        for p in parts:
            if not p:
                continue
            if len(buf) + len(p) > max_chars and buf:
                chunks.append(buf)
                # Carry over the last overlap chars for continuity
                buf = buf[-overlap:] if overlap else ""
            buf += p
        if buf:
            chunks.append(buf)
        if chunks:
            return chunks

    # Plain sliding window fallback
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


# ── SQLite FTS5 backend ────────────────────────────────────────────────────


def init_sqlite(db_path: Path, table: str):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5("
        f"source_path, chunk_index UNINDEXED, content, type UNINDEXED, "
        f"hash UNINDEXED, tokenize='porter unicode61')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS file_hashes (path TEXT PRIMARY KEY, hash TEXT)"
    )
    return conn


def sqlite_upsert(conn, table: str, source_path: str, chunks: list[str], kind: str, h: str):
    # Clear old chunks for this file
    conn.execute(f"DELETE FROM {table} WHERE source_path = ?", (source_path,))
    # Insert new chunks
    conn.executemany(
        f"INSERT INTO {table} (source_path, chunk_index, content, type, hash) VALUES (?, ?, ?, ?, ?)",
        [(source_path, i, c, kind, h) for i, c in enumerate(chunks)],
    )
    conn.execute(
        "INSERT INTO file_hashes (path, hash) VALUES (?, ?) "
        "ON CONFLICT(path) DO UPDATE SET hash = excluded.hash",
        (source_path, h),
    )


def sqlite_search(db_path: Path, table: str, query: str, top_k: int) -> list[dict]:
    """Full-text search the index.

    An index you cannot read is a write-only database. This lives in index.py,
    not in the bot's tool, so `--with-rag` is self-sufficient: the add-on is
    documented as independent of the bot, and it has to actually be.

    FTS5 `MATCH` is keyword search, not semantic — it finds documents sharing
    words with the query. Good enough to locate the right file; it will not
    match "how do I authenticate" against a page that only says "login".
    Switch to the remote backend when you need meaning rather than words.
    """
    if not db_path.is_file():
        return [{"error": f"no index at {db_path} — run `make reindex` first"}]

    conn = sqlite3.connect(db_path)
    try:
        # Quote the query as a single FTS5 string: an unescaped user query
        # containing a bare '-' or '"' is a syntax error, not a search.
        escaped = '"' + query.replace('"', '""') + '"'
        rows = conn.execute(
            f"SELECT source_path, chunk_index, content, type, "
            f"       snippet({table}, 2, '>>', '<<', ' … ', 24) AS excerpt "
            f"FROM {table} WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
            (escaped, top_k),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        return [{"error": f"search failed: {exc}"}]
    finally:
        conn.close()

    return [
        {
            "source_path": row[0],
            "chunk_index": row[1],
            "content": row[2],
            "type": row[3],
            "excerpt": " ".join(row[4].split()),
        }
        for row in rows
    ]


def sqlite_known_hash(conn, source_path: str) -> str | None:
    row = conn.execute("SELECT hash FROM file_hashes WHERE path = ?", (source_path,)).fetchone()
    return row[0] if row else None


# ── remote vector backend ────────────────────────────────────────────────


def remote_upsert(url: str, collection: str, model: str, dim: int, items: list[dict]):
    """Push embedded chunks to the vector database. Embeddings are computed
    itself if it supports server-side embedding; otherwise the caller must
    provide pre-computed vectors. This reference implementation posts text
    server-side — adapt this to your vector database's actual API.
    """
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed (required for the remote backend). Run: pip install httpx", file=sys.stderr)
        sys.exit(1)

    # Ensure collection exists (create if not). Exact API shape depends on
    # your vector database — this is a best-effort reference.
    try:
        r = httpx.post(
            f"{url.rstrip('/')}/collections",
            json={"name": collection, "dim": dim, "embedding_model": model},
            timeout=10,
        )
        # 409 = already exists, which is fine
        if r.status_code not in (200, 201, 204, 409):
            print(f"WARN: vector DB create collection returned {r.status_code}: {r.text[:200]}", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR: vector DB unreachable at {url}: {exc}", file=sys.stderr)
        print("Falling back to sqlite only. Set RAG_BACKEND=sqlite to silence this warning.", file=sys.stderr)
        return False

    # Upsert chunks. Again, adapt to your actual API.
    try:
        r = httpx.post(
            f"{url.rstrip('/')}/collections/{collection}/upsert",
            json={"items": items},
            timeout=60,
        )
        if r.status_code >= 300:
            print(f"WARN: vector DB upsert returned {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"ERROR: vector DB upsert failed: {exc}", file=sys.stderr)
        return False
    return True


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Index and search project files for RAG")
    ap.add_argument("--incremental", action="store_true", help="Only re-index changed files")
    ap.add_argument("--stats", action="store_true", help="Show index stats and exit")
    ap.add_argument("--search", metavar="QUERY", help="Search the index and exit")
    ap.add_argument("--top-k", type=int, default=0, help="Results for --search (default: from config)")
    ap.add_argument("--json", action="store_true", help="Machine-readable output for --search")
    args = ap.parse_args()

    if args.search:
        cfg = load_config()
        sq = cfg["backend"]["sqlite"]
        db_path = Path(sq["path"])  # same resolution as indexing: relative to CWD
        top_k = args.top_k or int(cfg.get("retrieval", {}).get("top_k", 5))
        _t = time.monotonic()
        results = sqlite_search(db_path, sq["fts_table"], args.search, top_k)
        elapsed = int((time.monotonic() - _t) * 1000)

        if args.json:
            print(json.dumps({"query": args.search, "results": results}, indent=2))
        else:
            error = next((r["error"] for r in results if "error" in r), None)
            if error:
                print(f"ERROR: {error}", file=sys.stderr)
            elif not results:
                # Reporting "no results" as success would be indistinguishable
                # from a broken index. Say which it is.
                print(f"no matches for {args.search!r} in {db_path.name}")
            else:
                for hit in results:
                    print(f"{hit['source_path']}#{hit['chunk_index']}  [{hit['type']}]")
                    print(f"    {hit['excerpt']}")
        print(
            f"[<name>-perf] phase=rag_search duration_ms={elapsed} "
            f"results={len([r for r in results if 'error' not in r])}",
            file=sys.stderr,
        )
        return 1 if any("error" in r for r in results) else 0

    config = load_config()
    root = Path.cwd()
    backend_type = config["backend"]["type"]
    chunk_cfg = config.get("chunk", {})

    if args.stats:
        db_path = Path(config["backend"]["sqlite"]["path"])
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            table = config["backend"]["sqlite"]["fts_table"]
            try:
                chunks = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                files = conn.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0]
                print(json.dumps({"backend": "sqlite", "files": files, "chunks": chunks, "db": str(db_path)}, indent=2))
            except sqlite3.OperationalError:
                print(json.dumps({"backend": "sqlite", "error": "not initialized"}))
        else:
            print(json.dumps({"backend": "sqlite", "error": "no index at " + str(db_path)}))
        return

    files = discover_files(config, root)
    print(f"[rag] found {len(files)} files to consider (project: {config['project']})")

    # Initialize backends
    conn = None
    use_sqlite = backend_type in ("sqlite", "both")
    use_remote = backend_type in ("remote", "both")

    if use_sqlite:
        db_path = Path(config["backend"]["sqlite"]["path"])
        table = config["backend"]["sqlite"]["fts_table"]
        conn = init_sqlite(db_path, table)

    remote_items: list[dict] = []
    indexed = skipped = 0
    t_start = time.monotonic()

    for path, kind in files:
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(errors="replace")
        except Exception as exc:
            print(f"  skip {rel}: {exc}")
            continue

        h = file_hash(path)
        if args.incremental and conn:
            known = sqlite_known_hash(conn, rel)
            if known == h:
                skipped += 1
                continue

        chunks = chunk_text(
            text,
            max_chars=chunk_cfg.get("max_chars", 1200),
            overlap=chunk_cfg.get("overlap", 200),
            respect_headings=chunk_cfg.get("respect_headings", True),
        )

        if use_sqlite:
            sqlite_upsert(conn, table, rel, chunks, kind, h)

        if use_remote:
            for i, chunk in enumerate(chunks):
                remote_items.append({
                    "id": f"{rel}#{i}",
                    "text": chunk,
                    "metadata": {"source_path": rel, "type": kind, "chunk_index": i, "hash": h},
                })

        indexed += 1

    if conn:
        conn.commit()
        conn.close()

    if use_remote and remote_items:
        rv_cfg = config["backend"]["remote"]
        if not rv_cfg.get("url"):
            print("[rag] VECTOR_DB_URL unset — skipping remote upsert", file=sys.stderr)
        else:
            remote_upsert(
                rv_cfg["url"],
                rv_cfg["collection"],
                rv_cfg["embedding_model"],
                rv_cfg["dim"],
                remote_items,
            )

    elapsed = int((time.monotonic() - t_start) * 1000)
    print(
        f"[<name>-perf] phase=rag_index duration_ms={elapsed} indexed={indexed} "
        f"skipped={skipped} backend={backend_type}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
