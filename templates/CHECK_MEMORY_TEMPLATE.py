#!/usr/bin/env python3
"""Validate memory/ frontmatter and report promotion candidates.

Invoked by `make memory-lint` and `make memory-promote-list`. Walks
memory/**/*.md (excluding README.md, SCHEMA.md, and _relevant-for-*.md
pre-flight briefs), parses YAML frontmatter, and checks:

    - Required fields present (name, id, type, date, confidence, outcome)
    - type value matches containing directory
    - confidence / outcome / promote values are from the allowed enums

Usage:
    python3 scripts/check_memory.py           # lint (exit 1 on errors)
    python3 scripts/check_memory.py --pending # list memories with promote: pending
"""
import argparse
import pathlib
import sys

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REQUIRED = ["name", "id", "type", "date", "confidence", "outcome"]
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_OUTCOME = {"success", "failure", "neutral", "abandoned"}
VALID_PROMOTE = {"yes", "no", "pending"}
DIR_TO_TYPE = {
    "decisions": "decision",
    "experiments": "experiment",
    "bugs": "bug",
    "feedback": "feedback",
    "sub_agent_runs": "sub_agent_run",
    "pr_reviews": "pr_review",
    "pipeline_failures": "pipeline_failure",
}
SKIP_FILES = {"README.md", "SCHEMA.md", ".gitkeep"}


def _parse(path: pathlib.Path) -> tuple[dict, str] | None:
    try:
        text = path.read_text()
    except Exception as exc:
        print(f"  {path}: read error {exc}", file=sys.stderr)
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except Exception as exc:
        print(f"  {path}: yaml error {exc}", file=sys.stderr)
        return None
    body = text[end + 4:].strip()
    return fm, body


def lint(root: pathlib.Path) -> int:
    errors = 0
    files_checked = 0
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP_FILES or path.name.startswith("_relevant-for-"):
            continue

        parsed = _parse(path)
        if parsed is None:
            print(f"  {path}: missing or malformed frontmatter")
            errors += 1
            continue
        fm, _body = parsed
        files_checked += 1

        # Required fields
        for field in REQUIRED:
            if field not in fm:
                print(f"  {path}: missing required field `{field}`")
                errors += 1

        # Enum validation
        if fm.get("confidence") and str(fm["confidence"]).lower() not in VALID_CONFIDENCE:
            print(f"  {path}: invalid confidence `{fm['confidence']}` (must be high|medium|low)")
            errors += 1
        if fm.get("outcome") and str(fm["outcome"]).lower() not in VALID_OUTCOME:
            print(f"  {path}: invalid outcome `{fm['outcome']}` (must be success|failure|neutral|abandoned)")
            errors += 1
        if fm.get("promote") and str(fm["promote"]).lower() not in VALID_PROMOTE:
            print(f"  {path}: invalid promote `{fm['promote']}` (must be yes|no|pending)")
            errors += 1

        # Type matches directory
        parent_name = path.parent.name
        expected_type = DIR_TO_TYPE.get(parent_name)
        if expected_type and fm.get("type") != expected_type:
            print(
                f"  {path}: type `{fm.get('type')}` "
                f"does not match directory `{parent_name}` (expected `{expected_type}`)"
            )
            errors += 1

    print(f"memory lint: checked {files_checked} files, {errors} errors")
    return errors


def list_pending(root: pathlib.Path) -> int:
    count = 0
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP_FILES or path.name.startswith("_relevant-for-"):
            continue
        parsed = _parse(path)
        if parsed is None:
            continue
        fm, _body = parsed
        if str(fm.get("promote", "")).lower() == "pending":
            name = fm.get("name", path.stem)
            conf = fm.get("confidence", "?")
            outcome = fm.get("outcome", "?")
            print(f"  {path}")
            print(f"    → {name}  [confidence={conf} outcome={outcome}]")
            count += 1
    if count == 0:
        print("  (no memories pending promotion)")
    else:
        print(f"{count} memories pending promotion — edit `promote: yes` to approve, then `make memory-promote`")
    return 0


def promote(root: pathlib.Path, store_url: str, project: str, api_key: str = "") -> int:
    """Push memories with `promote: yes` to the long-term store."""
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
        return 1

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    promoted = 0
    failed = 0
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP_FILES or path.name.startswith("_relevant-for-"):
            continue
        parsed = _parse(path)
        if parsed is None:
            continue
        fm, body = parsed
        if str(fm.get("promote", "")).lower() != "yes":
            continue

        payload = {
            "frontmatter": fm,
            "body": body,
            "submitted_by": project,
        }
        try:
            r = httpx.post(
                f"{store_url.rstrip('/')}/submit",
                json=payload,
                headers=headers,
                timeout=15,
            )
            if r.status_code < 300:
                memory_id = r.json().get("id", "?")
                print(f"  promoted {path.relative_to(root.parent)} → id={memory_id}")
                promoted += 1
            else:
                print(f"  FAILED {path}: {r.status_code} {r.text[:200]}")
                failed += 1
        except Exception as exc:
            print(f"  ERROR {path}: {exc}")
            failed += 1

    print(f"promoted {promoted} memories to long-term store ({failed} failed)")
    return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="Validate memory/ files + list + promote")
    ap.add_argument("--pending", action="store_true", help="List memories with promote: pending")
    ap.add_argument("--promote", action="store_true", help="Push memories with promote: yes to the long-term store")
    ap.add_argument("--store", default="", help="MEMORY_STORE_URL for --promote")
    ap.add_argument("--api-key", default="", help="Bearer API key for --promote (optional)")
    ap.add_argument("--project", default="", help="Project slug used as submitted_by in promotions")
    ap.add_argument("--root", default="memory", help="Memory directory root (default: memory)")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    if args.promote:
        if not args.store:
            print("ERROR: --promote requires --store <MEMORY_STORE_URL>", file=sys.stderr)
            sys.exit(1)
        sys.exit(promote(root, args.store, args.project or "unknown", args.api_key))
    elif args.pending:
        sys.exit(list_pending(root))
    else:
        errors = lint(root)
        sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
