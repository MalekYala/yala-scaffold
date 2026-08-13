#!/usr/bin/env python3
"""Validate .gitlab-ci.yml with the GitLab server that will run it.

    make ci-lint          # GITLAB_TOKEN (or GITLAB_ACCESS_TOKEN) in env

A file that is valid YAML can still be rejected by GitLab (a script item that
parses as a mapping, a job in an undeclared stage), and then the pipeline fails
with no jobs and no log. This asks the project's own GitLab instead of guessing,
as a dry run so variables (e.g. the runner tag) are expanded as in a real
pipeline.

Project and server come from the `origin` remote; override with GITLAB_URL and
CI_LINT_PROJECT (e.g. "group/name"). Stdlib only: runs on the host.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _remote() -> tuple[str | None, str | None]:
    """(server base URL, project path) parsed from `git remote get-url origin`."""
    try:
        url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    m = re.match(r"^(https?)://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}://{m.group(2)}", m.group(3)
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", url)
    if m:
        return f"https://{m.group(1)}", m.group(2)
    return None, None


def main(argv: list[str]) -> int:
    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_ACCESS_TOKEN")
    server, project = _remote()
    server = os.environ.get("GITLAB_URL") or server
    project = os.environ.get("CI_LINT_PROJECT") or project
    if not token or not server or not project:
        print("ci-lint: need GITLAB_TOKEN plus a GitLab `origin` remote (or GITLAB_URL and CI_LINT_PROJECT).", file=sys.stderr)
        return 2

    body = {"content": (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"), "dry_run": True, "include_jobs": True}
    req = urllib.request.Request(
        f"{server.rstrip('/')}/api/v4/projects/{urllib.parse.quote(project, safe='')}/ci/lint",
        data=json.dumps(body).encode(),
        headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
        method="POST",
    )
    _t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f"ci-lint: GitLab answered {exc.code} for {project} — {exc.read()[:200]!r}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"ci-lint: cannot reach {server}: {exc.reason}", file=sys.stderr)
        return 2
    print(f"[<project>-perf] phase=ci_lint duration_ms={int((time.monotonic() - _t) * 1000)} valid={str(result.get('valid')).lower()}")

    for warning in result.get("warnings") or []:
        print(f"warning: {warning}")
    if not result.get("valid"):
        for error in result.get("errors") or ["(no error text returned)"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    jobs = result.get("jobs") or []
    tags = sorted({t for j in jobs for t in (j.get("tag_list") or [])})
    print(f"ci-lint: valid — {len(jobs)} jobs, runner tags {tags or 'none (any runner)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
