"""write_memory — create a project-local memory file.

The LLM calls this tool when it decides something is worth capturing — an
experiment outcome, a bug fix rationale, an architectural decision, a
sub-agent run lesson. The tool writes a well-formed markdown file with
YAML frontmatter under memory/<category>/ and returns the path.

Memory files are picked up by:
    - rag/index.py on the next `make reindex` — queryable via local_rag
    - bot/tools/read_memory_local — direct category / tag queries
    - dispatch_agent pre-flight brief compilation
    - (optionally) the long-term memory store if promoted

See AGENTS.md §23 for the full schema + promotion rules, and
memory/SCHEMA.md in the project for the frontmatter reference.

Query format (free-text natural language; the LLM structures it):
    "<category>: <title> :: <body markdown>"
or
    "category=<cat>; title=<title>; tags=<a,b,c>; confidence=<h|m|l>;
     outcome=<s|f|n|a>; promote=<y|n|p>; body=<markdown>"
"""
import json
import os
import re
import time
from pathlib import Path

NAME = "write_memory"
DESCRIPTION = (
    "Capture a project learning or experience as a persistent memory file. "
    "Use when something worth remembering happened: an experiment taught "
    "us something, a bug fix revealed a pattern, a decision had non-obvious "
    "trade-offs, a dispatched sub-agent did something noteworthy. The memory "
    "lands in memory/<category>/ with YAML frontmatter, gets picked up by "
    "the RAG on next reindex, and is eligible for promotion to the long-term "
    "cross-project store. Categories: decision, experiment, bug, feedback, "
    "sub_agent_run. Input format: pass a JSON dict with at minimum "
    "{category, name, body} plus optional tags/confidence/outcome/promote."
)

VALID_CATEGORIES = {"decision", "experiment", "bug", "feedback", "sub_agent_run"}
CATEGORY_DIRS = {
    "decision": "decisions",
    "experiment": "experiments",
    "bug": "bugs",
    "feedback": "feedback",
    "sub_agent_run": "sub_agent_runs",
}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_OUTCOME = {"success", "failure", "neutral", "abandoned"}
VALID_PROMOTE = {"yes", "no", "pending"}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", text.lower()).strip("-")
    return s[:50] or "untitled"


def _next_id(directory: Path) -> str:
    """Return the next 4-digit ID string for a category directory."""
    existing_ids = []
    if directory.exists():
        for p in directory.glob("*.md"):
            m = re.match(r"^(\d{4})-", p.name)
            if m:
                existing_ids.append(int(m.group(1)))
    n = max(existing_ids) + 1 if existing_ids else 1
    return f"{n:04d}"


def _parse_input(query: str) -> dict:
    """Accept either JSON, semicolon-separated key=value, or free-form text.

    Free-form text is parsed as '<category>: <title> :: <body>'.
    """
    query = query.strip()

    # 1. JSON object
    if query.startswith("{"):
        try:
            return json.loads(query)
        except json.JSONDecodeError:
            pass

    # 2. Semicolon-separated key=value pairs
    if ";" in query and "=" in query:
        d: dict = {}
        for pair in query.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "tags":
                d[k] = [t.strip() for t in v.split(",") if t.strip()]
            else:
                d[k] = v
        if d.get("category") or d.get("title") or d.get("name"):
            return d

    # 3. Free-form "<category>: <title> :: <body>"
    m = re.match(r"^(\w+)\s*:\s*(.+?)\s*::\s*(.*)$", query, re.DOTALL)
    if m:
        return {"category": m.group(1), "name": m.group(2), "body": m.group(3)}

    # 4. Last resort — treat everything as body under an "untitled" decision
    return {"category": "decision", "name": "untitled note", "body": query}


def call(query: str, ctx: dict) -> str:
    try:
        data = _parse_input(query)
    except Exception as exc:
        return f"(could not parse memory input: {exc})"

    category = (data.get("category") or data.get("type") or "").strip().lower()
    if category not in VALID_CATEGORIES:
        return (
            f"(invalid category '{category}' — valid: {sorted(VALID_CATEGORIES)})"
        )

    title = (data.get("name") or data.get("title") or "").strip()
    if not title:
        return "(missing required field: name/title)"

    body = (data.get("body") or "").strip()
    if not body:
        body = "*(no body provided)*"

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    confidence = (data.get("confidence") or "low").strip().lower()
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"

    outcome = (data.get("outcome") or "neutral").strip().lower()
    if outcome not in VALID_OUTCOME:
        outcome = "neutral"

    promote = (data.get("promote") or "no").strip().lower()
    if promote not in VALID_PROMOTE:
        promote = "no"

    dir_name = CATEGORY_DIRS[category]
    memory_dir = Path(f"memory/{dir_name}")
    memory_dir.mkdir(parents=True, exist_ok=True)

    mem_id = _next_id(memory_dir)
    filename = f"{mem_id}-{_slug(title)}.md"
    path = memory_dir / filename

    project = ctx.get("project", "unknown")
    shape = os.environ.get("PROJECT_SHAPE", "unknown")
    lang = os.environ.get("PROJECT_LANG", "unknown")
    date = time.strftime("%Y-%m-%d")

    # Build frontmatter
    frontmatter_lines = [
        "---",
        f"name: {title}",
        f'id: "{mem_id}"',
        f"type: {category}",
        f"date: {date}",
        f"project: {project}",
        f"shape: {shape}",
        f"lang: {lang}",
    ]
    if tags:
        frontmatter_lines.append(f"tags: [{', '.join(tags)}]")
    frontmatter_lines.extend([
        f"confidence: {confidence}",
        f"outcome: {outcome}",
        f"promote: {promote}",
        "author: bot",
    ])

    # Optional fields
    if data.get("references"):
        frontmatter_lines.append("references:")
        for ref in data["references"]:
            if isinstance(ref, dict):
                frontmatter_lines.append(f"  - type: {ref.get('type', 'url')}")
                frontmatter_lines.append(f"    ref: {ref.get('ref', '')}")
    if data.get("agent_task"):
        frontmatter_lines.append(f"agent_task: {json.dumps(data['agent_task'])}")
    if data.get("agent_branch"):
        frontmatter_lines.append(f"agent_branch: {data['agent_branch']}")
    frontmatter_lines.append("---")

    content = "\n".join(frontmatter_lines) + "\n\n" + body + "\n"
    path.write_text(content)

    return (
        f"wrote memory/{dir_name}/{filename} "
        f"(id={mem_id} confidence={confidence} outcome={outcome} promote={promote})"
    )
