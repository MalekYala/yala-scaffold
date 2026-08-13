"""read_memory_local — search project-local memory files.

Returns the top-N memories matching a query, filtered by optional
category / tags / confidence / outcome. Uses keyword matching (fast, no
embeddings needed) against frontmatter + body. For semantic matching
against cross-project wisdom, use read_memory_longterm.

Query format (either):
    - plain text: "how did we handle rate limiting"
    - with filters: "category=experiment; confidence=high; query=sma crossover"
"""
import os
import re
from pathlib import Path

NAME = "read_memory_local"
DESCRIPTION = (
    "Search this project's memory/ directory for past learnings. Returns "
    "top relevant decisions, experiments, bugs, feedback, and sub-agent "
    "run outcomes. Use BEFORE starting a new experiment or dispatching a "
    "sub-agent to avoid repeating past mistakes. Supports filters: "
    "'category=<cat>; confidence=<h|m|l>; outcome=<s|f|n|a>; query=<text>'."
)

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


def _parse_query(raw: str) -> dict:
    filters: dict = {}
    query_text = raw.strip()
    if ";" in raw and "=" in raw:
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        text_parts = []
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if k == "query":
                    text_parts.append(v)
                else:
                    filters[k] = v
            else:
                text_parts.append(p)
        query_text = " ".join(text_parts)
    return {"text": query_text, **filters}


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 4)
    if end < 0:
        return {}, content
    raw_fm = content[4:end].strip()
    body = content[end + 4:].strip()
    fm: dict = {}
    for line in raw_fm.splitlines():
        line = line.rstrip()
        if not line or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"')
        if v.startswith("[") and v.endswith("]"):
            v = [t.strip() for t in v[1:-1].split(",") if t.strip()]
        fm[k] = v
    return fm, body


def _score(fm: dict, body: str, query_words: list[str]) -> float:
    if not query_words:
        return 1.0
    text = (fm.get("name", "") + " " + " ".join(fm.get("tags", [])) + " " + body).lower()
    hits = sum(1 for w in query_words if w.lower() in text)
    if hits == 0:
        return 0.0
    # Boost by confidence
    conf_boost = {"high": 1.5, "medium": 1.0, "low": 0.7}.get(fm.get("confidence", "low"), 1.0)
    return (hits / len(query_words)) * conf_boost


def call(query: str, ctx: dict) -> str:
    if not MEMORY_ROOT.exists():
        return "(no memory/ directory — nothing indexed yet)"

    parsed = _parse_query(query)
    q_text = parsed.get("text", "")
    filter_cat = parsed.get("category")
    filter_conf = parsed.get("confidence")
    filter_out = parsed.get("outcome")
    filter_tags = parsed.get("tags")
    if filter_tags:
        filter_tags = [t.strip().lower() for t in filter_tags.split(",") if t.strip()]

    query_words = re.findall(r"\w+", q_text)

    results: list[tuple[float, Path, dict]] = []
    for p in MEMORY_ROOT.rglob("*.md"):
        if p.name in ("README.md", "SCHEMA.md"):
            continue
        if p.name.startswith("_"):
            continue  # skip _relevant-for-<branch>.md scratchpads
        try:
            fm, body = _parse_frontmatter(p.read_text())
        except Exception:
            continue

        if filter_cat and fm.get("type", "").lower() != filter_cat.lower():
            continue
        if filter_conf and fm.get("confidence", "").lower() != filter_conf.lower():
            continue
        if filter_out and fm.get("outcome", "").lower() != filter_out.lower():
            continue
        if filter_tags:
            mem_tags = [t.lower() for t in fm.get("tags", [])] if isinstance(fm.get("tags"), list) else []
            if not any(t in mem_tags for t in filter_tags):
                continue

        score = _score(fm, body, query_words)
        if score > 0:
            results.append((score, p, fm))

    if not results:
        return f"(no memories matched: {query})"

    results.sort(key=lambda x: x[0], reverse=True)
    top = results[:5]

    lines = [f"Top {len(top)} project memories for: {q_text}"]
    for score, path, fm in top:
        name = fm.get("name", path.stem)
        mem_type = fm.get("type", "?")
        conf = fm.get("confidence", "?")
        outcome = fm.get("outcome", "?")
        tags = ", ".join(fm.get("tags", [])) if isinstance(fm.get("tags"), list) else ""
        rel = path.relative_to(Path.cwd()) if Path.cwd() in path.parents else path
        lines.append(
            f"• {rel} · {mem_type} · conf={conf} · outcome={outcome}"
            + (f" · tags={tags}" if tags else "")
            + f" · score={score:.2f}"
        )
        lines.append(f"  → {name}")

    return "\n".join(lines)
