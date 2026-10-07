#!/usr/bin/env python3
"""Fail if any CI template has a script item that YAML does not read as a string.

GitLab rejects the whole pipeline (no jobs run) when a `script:` entry is not a
string. The classic trap is an unquoted line containing ": ", e.g.
    - ruff check . || echo "WARN: ruff found issues"
which YAML parses as the mapping {'ruff check . || echo "WARN': ...}. Quote
such lines:  - 'ruff check . || echo "WARN: ruff found issues"'

Usage: tests/check_ci_yaml.py [ROOT ...]   (default: the kit root)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SCRIPT_KEYS = ("script", "before_script", "after_script")
# Keys at the top level of .gitlab-ci.yml that are not jobs.
RESERVED = {"stages", "variables", "default", "include", "workflow", "image", "services", "cache", "before_script", "after_script"}
DEFAULT_STAGES = ["build", "test", "deploy"]  # GitLab's implicit list when `stages` is absent


def _strings_only(items: object) -> bool:
    if isinstance(items, str):
        return True
    return isinstance(items, list) and all(_strings_only(i) for i in items)


def check(path: Path) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse error: {str(exc).splitlines()[0]}"]
    problems = []
    doc = doc or {}
    # Fragments (e.g. addons/review/ci.gitlab-ci.yml) are `include`d into a
    # project's main file and inherit its stages and default.tags.
    fragment = path.name not in {".gitlab-ci.yml", "GITLAB_CI_TEMPLATE.yml"}
    stages = set(doc.get("stages") or DEFAULT_STAGES) | {".pre", ".post"}
    for job, spec in doc.items():
        if not isinstance(spec, dict) or job in RESERVED:
            continue
        for key in SCRIPT_KEYS:
            if key in spec and not _strings_only(spec[key]):
                problems.append(f"{path}: job {job!r} {key} has a non-string item (unquoted ': '?)")
        # GitLab rejects the whole file when a job names an undeclared stage.
        if not fragment and not job.startswith(".") and spec.get("stage", "test") not in stages:
            problems.append(f"{path}: job {job!r} uses stage {spec.get('stage')!r}, not in stages {sorted(stages - {'.pre', '.post'})}")
    # Every job must be routable to a runner whose executor matches the file.
    tags = (doc.get("default") or {}).get("tags")
    if not fragment and (tags != ["$YALA_CI_TAG"] or "YALA_CI_TAG" not in (doc.get("variables") or {})):
        problems.append(f"{path}: missing variables.YALA_CI_TAG + default.tags ['$YALA_CI_TAG']")
    return problems


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path(__file__).resolve().parent.parent]
    files = sorted(
        p for root in roots for p in root.rglob("*.yml")
        if (".gitlab-ci" in p.name or "GITLAB_CI" in p.name) and ".git" not in p.parts
    )  # fmt: skip
    problems = [msg for f in files for msg in check(f)]
    for msg in problems:
        print(msg, file=sys.stderr)
    print(f"check_ci_yaml: {len(files)} files, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
