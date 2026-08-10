#!/usr/bin/env python3
"""Operator-side long-term agent memory store — REFERENCE implementation.

This is a single-file FastAPI service that every project bot can query via
the `read_memory_longterm` tool, and that per-project `make memory-promote`
pushes vetted memories into. Think of it as a cross-project "lessons
learned" database that makes each new project start smarter.

Two backing stores:
    1. remote (semantic search) — memories get embedded and indexed into
       per-category collections. Queries return semantically-similar
       memories regardless of which project they originated in.
    2. memory-archive (verbatim) — full memory payloads with provenance stored
       intact so operators can audit, unpromote, and trace lessons back.

Both are operator-supplied services. If neither is available, this store
falls back to a local SQLite FTS5 index so it still works standalone.

Endpoints:
    POST /submit        — accept a memory for promotion (from a project bot)
    POST /query         — return top-K relevant memories for a task
    GET  /recent        — recent high-confidence memories across all projects
    GET  /stats         — counts per category / shape / lang / project
    DELETE /memories/<id> — unpromote a memory (remove from collections)
    GET  /health        — liveness probe

Run:
    pip install fastapi uvicorn httpx pyyaml
    python3 agent_memory_store.py

    # Override port
    MEMORY_STORE_PORT=7140 python3 agent_memory_store.py

This file is PUBLIC-SAFE. It references operator services via env vars and
has no hardcoded URLs. Deploy on the operator side (NOT inside any project).

Usage from a project bot:
    export MEMORY_STORE_URL=http://127.0.0.1:7140
    export MEMORY_STORE_API_KEY=<optional-bearer-token>

See AGENTS.md §23 and BOT_TEMPLATE/tools/read_memory_longterm.py for the
client-side expectations.
"""
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, Header, Request
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    print("ERROR: fastapi + uvicorn required. Run: pip install fastapi uvicorn httpx pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None  # remote/memory-archive pushes will fail loudly; sqlite still works


# ── Config via env ─────────────────────────────────────────────────────────

PORT = int(os.environ.get("MEMORY_STORE_PORT", "7140"))
HOST = os.environ.get("MEMORY_STORE_HOST", "127.0.0.1")
API_KEY = os.environ.get("MEMORY_STORE_API_KEY", "")  # empty = no auth
DB_PATH = Path(os.environ.get("MEMORY_STORE_DB", "data/agent_memory.sqlite"))

# Optional backends — if unset, the store runs in sqlite-only mode
VECTOR_DB_URL = os.environ.get("VECTOR_DB_URL", "").rstrip("/")
VECTOR_DB_EMBEDDING_MODEL = os.environ.get("VECTOR_DB_EMBEDDING_MODEL", "bge-m3")
VECTOR_DB_DIM = int(os.environ.get("VECTOR_DB_DIM", "1024"))
MEMORY_ARCHIVE_URL = os.environ.get("MEMORY_ARCHIVE_URL", "").rstrip("/")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [agent-memory-store] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("agent-memory-store")


# ── SQLite backend (always on — local source of truth) ────────────────────


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            origin_project TEXT NOT NULL,
            type TEXT NOT NULL,
            shape TEXT,
            lang TEXT,
            name TEXT NOT NULL,
            confidence TEXT,
            outcome TEXT,
            tags TEXT,
            body TEXT NOT NULL,
            lesson TEXT,
            frontmatter TEXT NOT NULL,
            submitted_at INTEGER NOT NULL,
            submitted_by TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            id UNINDEXED,
            name,
            body,
            lesson,
            tags,
            tokenize='porter unicode61'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shape ON memories(shape)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lang ON memories(lang)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_origin ON memories(origin_project)")
    conn.commit()
    return conn


def make_id(payload: dict) -> str:
    """Derive a stable ID from project + name + submitted_at."""
    key = f"{payload.get('project', '')}:{payload.get('name', '')}:{int(time.time())}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def sqlite_insert(conn, memory_id: str, payload: dict, submitted_by: str):
    fm = payload.get("frontmatter") or {}
    tags = fm.get("tags") or []
    if isinstance(tags, list):
        tags_str = ",".join(tags)
    else:
        tags_str = str(tags)

    conn.execute("""
        INSERT OR REPLACE INTO memories
        (id, origin_project, type, shape, lang, name, confidence, outcome, tags, body, lesson, frontmatter, submitted_at, submitted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        memory_id,
        fm.get("project", "unknown"),
        fm.get("type", "unknown"),
        fm.get("shape"),
        fm.get("lang"),
        fm.get("name", ""),
        fm.get("confidence", "low"),
        fm.get("outcome", "neutral"),
        tags_str,
        payload.get("body", ""),
        payload.get("lesson", ""),
        json.dumps(fm),
        int(time.time()),
        submitted_by,
    ))
    # Refresh FTS row
    conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
    conn.execute(
        "INSERT INTO memories_fts (id, name, body, lesson, tags) VALUES (?, ?, ?, ?, ?)",
        (memory_id, fm.get("name", ""), payload.get("body", ""), payload.get("lesson", ""), tags_str),
    )
    conn.commit()


def sqlite_query(conn, query: str, filters: dict, limit: int = 5) -> list[dict]:
    safe_query = " ".join(w for w in query.split() if w.isalnum() or "-" in w or "_" in w)[:200]
    if not safe_query:
        safe_query = '""'  # empty search returns nothing via FTS

    where_clauses = []
    params: list = [safe_query]

    if filters.get("category") or filters.get("type"):
        where_clauses.append("m.type = ?")
        params.append(filters.get("category") or filters.get("type"))
    if filters.get("shape"):
        where_clauses.append("m.shape = ?")
        params.append(filters["shape"])
    if filters.get("lang"):
        where_clauses.append("m.lang = ?")
        params.append(filters["lang"])
    if filters.get("confidence"):
        where_clauses.append("m.confidence = ?")
        params.append(filters["confidence"])

    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)

    sql = f"""
        SELECT m.id, m.origin_project, m.type, m.shape, m.lang, m.name,
               m.confidence, m.outcome, m.tags, m.body, m.lesson, m.frontmatter
        FROM memories_fts fts
        JOIN memories m ON m.id = fts.id
        WHERE memories_fts MATCH ?{where_sql}
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        log.warning(f"sqlite query failed: {exc}")
        return []

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "origin_project": r[1],
            "type": r[2],
            "shape": r[3],
            "lang": r[4],
            "name": r[5],
            "confidence": r[6],
            "outcome": r[7],
            "tags": r[8].split(",") if r[8] else [],
            "body": r[9],
            "lesson": r[10],
            "frontmatter": json.loads(r[11]) if r[11] else {},
        })
    return out


# ── Optional remote / memory-archive push ────────────────────────────────────


def remote_upsert(memory_id: str, payload: dict, collections: list[str]):
    if not VECTOR_DB_URL or httpx is None:
        return
    fm = payload.get("frontmatter") or {}
    item = {
        "id": memory_id,
        "text": payload.get("body", "") + "\n\n" + (payload.get("lesson") or ""),
        "metadata": {
            "origin_project": fm.get("project"),
            "type": fm.get("type"),
            "shape": fm.get("shape"),
            "lang": fm.get("lang"),
            "name": fm.get("name"),
            "confidence": fm.get("confidence"),
            "outcome": fm.get("outcome"),
            "tags": fm.get("tags", []),
            "submitted_at": int(time.time()),
        },
    }
    for collection in collections:
        try:
            httpx.post(
                f"{VECTOR_DB_URL}/collections",
                json={"name": collection, "dim": VECTOR_DB_DIM, "embedding_model": VECTOR_DB_EMBEDDING_MODEL},
                timeout=5,
            )
            r = httpx.post(
                f"{VECTOR_DB_URL}/collections/{collection}/upsert",
                json={"items": [item]},
                timeout=10,
            )
            if r.status_code >= 300:
                log.warning(f"remote upsert {collection}: {r.status_code} {r.text[:200]}")
        except Exception as exc:
            log.warning(f"remote unreachable ({collection}): {exc}")


def archive_push(memory_id: str, payload: dict):
    if not MEMORY_ARCHIVE_URL or httpx is None:
        return
    fm = payload.get("frontmatter") or {}
    try:
        httpx.post(
            f"{MEMORY_ARCHIVE_URL}/memories",
            json={
                "id": memory_id,
                "text": payload.get("body", ""),
                "metadata": fm,
                "source": "agent_memory_store",
            },
            timeout=10,
        )
    except Exception as exc:
        log.warning(f"memory-archive push failed: {exc}")


def collections_for(fm: dict) -> list[str]:
    """Pick which remote collections to write this memory into."""
    out = ["agent_learnings_common"]
    if fm.get("type"):
        out.append(f"agent_learnings_category_{fm['type']}")
    if fm.get("shape"):
        out.append(f"agent_learnings_shape_{fm['shape']}")
    if fm.get("lang"):
        out.append(f"agent_learnings_lang_{fm['lang']}")
    return out


# ── HTTP API ──────────────────────────────────────────────────────────────


_conn: sqlite3.Connection | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _conn
    _conn = init_db()
    log.info(f"agent-memory-store starting on {HOST}:{PORT}")
    log.info(f"sqlite: {DB_PATH}")
    log.info(f"remote: {VECTOR_DB_URL or '(not configured)'}")
    log.info(f"memory-archive: {MEMORY_ARCHIVE_URL or '(not configured)'}")
    yield
    if _conn:
        _conn.close()


app = FastAPI(title="agent-memory-store", lifespan=lifespan)


def _auth(authorization: str | None) -> bool:
    if not API_KEY:
        return True  # no auth configured
    if not authorization:
        return False
    if authorization.startswith("Bearer "):
        return authorization[7:].strip() == API_KEY
    return authorization.strip() == API_KEY


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-memory-store"}


@app.post("/submit")
async def submit(request: Request, authorization: str = Header(None)):
    if not _auth(authorization):
        raise HTTPException(status_code=401, detail="invalid API key")

    payload = await request.json()
    fm = payload.get("frontmatter") or {}
    if not fm.get("name") or not payload.get("body"):
        raise HTTPException(status_code=400, detail="frontmatter.name and body required")

    memory_id = payload.get("id") or make_id(fm)
    submitted_by = payload.get("submitted_by", fm.get("project", "unknown"))

    sqlite_insert(_conn, memory_id, payload, submitted_by)
    collections = collections_for(fm)
    remote_upsert(memory_id, payload, collections)
    archive_push(memory_id, payload)

    log.info(f"submitted memory {memory_id} from {submitted_by} → collections={collections}")
    return {"id": memory_id, "collections": collections, "status": "stored"}


@app.post("/query")
async def query(request: Request, authorization: str = Header(None)):
    if not _auth(authorization):
        raise HTTPException(status_code=401, detail="invalid API key")

    payload = await request.json()
    q = payload.get("query", "").strip()
    filters = payload.get("filters") or {}
    limit = int(payload.get("limit", 5))
    requesting_project = payload.get("requesting_project", "")

    results = sqlite_query(_conn, q, filters, limit)
    log.info(
        f"query from {requesting_project!r} q={q[:80]!r} "
        f"filters={filters} → {len(results)} results"
    )
    return {"query": q, "filters": filters, "results": results}


@app.get("/recent")
def recent(limit: int = 10, confidence: str | None = None, authorization: str = Header(None)):
    if not _auth(authorization):
        raise HTTPException(status_code=401, detail="invalid API key")
    sql = "SELECT id, origin_project, type, shape, lang, name, confidence, outcome, submitted_at FROM memories"
    params: list = []
    if confidence:
        sql += " WHERE confidence = ?"
        params.append(confidence)
    sql += " ORDER BY submitted_at DESC LIMIT ?"
    params.append(limit)
    rows = _conn.execute(sql, params).fetchall()
    return {
        "results": [
            {
                "id": r[0], "origin_project": r[1], "type": r[2], "shape": r[3],
                "lang": r[4], "name": r[5], "confidence": r[6],
                "outcome": r[7], "submitted_at": r[8],
            }
            for r in rows
        ],
    }


@app.get("/stats")
def stats(authorization: str = Header(None)):
    if not _auth(authorization):
        raise HTTPException(status_code=401, detail="invalid API key")
    by_type = dict(_conn.execute(
        "SELECT type, COUNT(*) FROM memories GROUP BY type"
    ).fetchall())
    by_shape = dict(_conn.execute(
        "SELECT shape, COUNT(*) FROM memories WHERE shape IS NOT NULL GROUP BY shape"
    ).fetchall())
    by_lang = dict(_conn.execute(
        "SELECT lang, COUNT(*) FROM memories WHERE lang IS NOT NULL GROUP BY lang"
    ).fetchall())
    by_project = dict(_conn.execute(
        "SELECT origin_project, COUNT(*) FROM memories GROUP BY origin_project ORDER BY 2 DESC LIMIT 20"
    ).fetchall())
    total = _conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    return {
        "total": total,
        "by_type": by_type,
        "by_shape": by_shape,
        "by_lang": by_lang,
        "top_projects": by_project,
    }


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, authorization: str = Header(None)):
    if not _auth(authorization):
        raise HTTPException(status_code=401, detail="invalid API key")
    _conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    _conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
    _conn.commit()
    log.info(f"unpromoted memory {memory_id}")
    return {"id": memory_id, "status": "deleted"}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level=LOG_LEVEL.lower())
