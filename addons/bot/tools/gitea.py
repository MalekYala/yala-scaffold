"""gitea — common Gitea REST API client used by dispatch_agent + review_pr.

Thin wrapper over the Gitea v1 API plus a few git-subprocess helpers.
No LLM calls happen here — this is pure plumbing. The tool-calling flow
that uses this module is in dispatch_agent.py (auto-push + open PR) and
review_pr.py (fetch diff, post review, merge/close).

This module is ALSO exposed as a bot tool so the LLM can directly ask
"list open PRs" or "what's in PR #42" during a conversation.

Env vars:
    GITEA_URL              http://127.0.0.1:3030
    GITEA_API_URL          http://127.0.0.1:3030/api/v1  (derived if unset)
    GITEA_TOKEN            bearer token
    GITEA_OWNER            <name>-bot (the bot user)
    GITEA_REPO             <name>
"""
import os
import re
import subprocess
import time
from typing import Any

NAME = "gitea"
DESCRIPTION = (
    "Query and manipulate this project's Gitea instance: list open pull "
    "requests, fetch PR details/diffs, open/merge/close PRs, post comments. "
    "Use for: 'what PRs are open', 'show me PR 42', 'merge PR 7'. "
    "The LLM can call this tool directly with a command like 'list_prs', "
    "'get_pr 42', 'merge_pr 42', 'comment_pr 42 <body>', or 'open_pr <title>::<body>::<head>'."
)

GITEA_URL = os.environ.get("GITEA_URL", "").rstrip("/")
GITEA_API_URL = os.environ.get("GITEA_API_URL", "").rstrip("/") or (f"{GITEA_URL}/api/v1" if GITEA_URL else "")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
GITEA_OWNER = os.environ.get("GITEA_OWNER", "")
GITEA_REPO = os.environ.get("GITEA_REPO", "")
GITEA_BOT_USER = os.environ.get("GITEA_BOT_USER", GITEA_OWNER)
GITEA_HTTP_PORT = os.environ.get("GITEA_HTTP_PORT", "3030")
# Public-facing URL via the operator's central Caddy reverse proxy. When
# set, pr_url() prefers this so IRC messages link to a reachable URL
# instead of localhost. Convention: `<slug>-git.<your-public-domain>`.
GITEA_PUBLIC_URL = os.environ.get("GITEA_PUBLIC_URL", "").rstrip("/")
GITEA_PUBLIC_DOMAIN = os.environ.get("GITEA_PUBLIC_DOMAIN", "").strip().strip("/")


class GiteaError(Exception):
    pass


def _require_config():
    missing = []
    if not GITEA_API_URL:
        missing.append("GITEA_URL or GITEA_API_URL")
    if not GITEA_TOKEN:
        missing.append("GITEA_TOKEN")
    if not GITEA_OWNER:
        missing.append("GITEA_OWNER")
    if not GITEA_REPO:
        missing.append("GITEA_REPO")
    if missing:
        raise GiteaError(f"missing env vars: {', '.join(missing)}")


def _headers() -> dict:
    return {
        "Authorization": f"token {GITEA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _api(method: str, path: str, **kwargs) -> "httpx.Response":
    import httpx

    _require_config()
    url = f"{GITEA_API_URL}{path}"
    r = httpx.request(method, url, headers=_headers(), timeout=30, **kwargs)
    return r


# ── Git subprocess helpers (push the branch) ──────────────────────────────


def _git(*args, cwd: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def ensure_remote(repo_root: str | None = None) -> str:
    """Ensure the project has a `gitea` git remote pointing at the configured
    Gitea repo. Returns the remote URL used.

    The URL embeds the bot token, which is gitignored and never committed.

    Uses GITEA_URL (env) as the base so that a bot running inside docker
    pushes to the gitea service by its compose hostname (e.g.
    http://<name>-gitea:3000), while a bot running on the host pushes to
    the host-facing URL (http://127.0.0.1:3030). bootstrap.sh writes the
    host URL into .env; docker-compose.bot.yml overrides GITEA_URL in the
    bot container's environment to use the compose hostname. Either way,
    GITEA_URL is the single source of truth — do NOT hardcode 127.0.0.1.
    """
    _require_config()
    # Parse GITEA_URL (e.g. http://<name>-gitea:3000) and inject the bot
    # user + token between the scheme and the host. Falls back to
    # 127.0.0.1:GITEA_HTTP_PORT only if GITEA_URL wasn't set.
    import urllib.parse
    if GITEA_URL:
        parts = urllib.parse.urlparse(GITEA_URL)
        netloc = parts.netloc  # e.g. "<name>-gitea:3000"
        remote_url = (
            f"{parts.scheme}://{GITEA_BOT_USER}:{GITEA_TOKEN}@{netloc}"
            f"/{GITEA_OWNER}/{GITEA_REPO}.git"
        )
    else:
        remote_url = (
            f"http://{GITEA_BOT_USER}:{GITEA_TOKEN}@127.0.0.1:{GITEA_HTTP_PORT}"
            f"/{GITEA_OWNER}/{GITEA_REPO}.git"
        )
    code, out = _git("remote", "get-url", "gitea", cwd=repo_root)
    if code == 0:
        # Remote exists — update URL in case the token or base URL changed
        _git("remote", "set-url", "gitea", remote_url, cwd=repo_root)
    else:
        _git("remote", "add", "gitea", remote_url, cwd=repo_root)
    return remote_url


def push_branch(branch: str, repo_root: str | None = None, force: bool = False) -> tuple[bool, str]:
    """Push a local branch to the `gitea` remote. Returns (ok, output)."""
    try:
        ensure_remote(repo_root)
    except GiteaError as exc:
        return False, str(exc)

    args = ["push", "gitea", branch]
    if force:
        args.insert(1, "--force")
    code, out = _git(*args, cwd=repo_root)
    return code == 0, out


# ── Gitea API operations ──────────────────────────────────────────────────


def open_pr(title: str, body: str, head: str, base: str = "main") -> dict:
    """Open a pull request on Gitea. Returns the parsed PR dict."""
    r = _api(
        "POST",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls",
        json={
            "title": title[:255],
            "body": body[:60_000],
            "head": head,
            "base": base,
        },
    )
    if r.status_code >= 300:
        raise GiteaError(f"open_pr failed: {r.status_code} {r.text[:400]}")
    return r.json()


def list_prs(state: str = "open", limit: int = 20) -> list[dict]:
    r = _api(
        "GET",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls",
        params={"state": state, "limit": limit},
    )
    if r.status_code >= 300:
        raise GiteaError(f"list_prs failed: {r.status_code} {r.text[:400]}")
    return r.json()


def get_pr(index: int) -> dict:
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}")
    if r.status_code >= 300:
        raise GiteaError(f"get_pr({index}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


def get_pr_files(index: int) -> list[dict]:
    """Return the list of files changed in a PR with diff stats."""
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}/files")
    if r.status_code >= 300:
        raise GiteaError(f"get_pr_files({index}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


def get_pr_diff(index: int) -> str:
    """Fetch the unified diff of a PR as plain text."""
    import httpx

    _require_config()
    url = f"{GITEA_URL}/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}.diff"
    r = httpx.get(url, headers={"Authorization": f"token {GITEA_TOKEN}"}, timeout=30)
    if r.status_code >= 300:
        raise GiteaError(f"get_pr_diff({index}) failed: {r.status_code}")
    return r.text


def merge_pr(index: int, method: str = "squash", title: str | None = None, message: str | None = None) -> dict:
    """Merge a PR. method: merge | squash | rebase | rebase-merge."""
    payload: dict = {"Do": method}
    if title:
        payload["MergeTitleField"] = title
    if message:
        payload["MergeMessageField"] = message
    r = _api(
        "POST",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}/merge",
        json=payload,
    )
    if r.status_code >= 300:
        raise GiteaError(f"merge_pr({index}) failed: {r.status_code} {r.text[:400]}")
    return {"index": index, "status": "merged", "method": method}


def close_pr(index: int) -> dict:
    r = _api(
        "PATCH",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}",
        json={"state": "closed"},
    )
    if r.status_code >= 300:
        raise GiteaError(f"close_pr({index}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


def post_review(index: int, body: str, event: str = "COMMENT") -> dict:
    """Post a review on a PR. event: APPROVED | REQUEST_CHANGES | COMMENT."""
    r = _api(
        "POST",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}/reviews",
        json={"body": body[:60_000], "event": event},
    )
    if r.status_code >= 300:
        raise GiteaError(f"post_review({index}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


def post_comment(index: int, body: str) -> dict:
    """Post an issue-level comment on a PR (not a review)."""
    r = _api(
        "POST",
        f"/repos/{GITEA_OWNER}/{GITEA_REPO}/issues/{index}/comments",
        json={"body": body[:60_000]},
    )
    if r.status_code >= 300:
        raise GiteaError(f"post_comment({index}) failed: {r.status_code} {r.text[:400]}")
    return r.json()


def delete_branch(branch: str) -> bool:
    r = _api("DELETE", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/branches/{branch}")
    return r.status_code < 300


def pr_url(index: int) -> str:
    """Return a human-facing URL for a PR.

    Prefers the public URL exposed via Caddy so IRC links work from
    anywhere; falls back to the public-domain convention (slug-git.<zone>);
    finally falls back to the localhost Gitea URL for standalone dev.
    """
    base = _public_base_url()
    return f"{base}/{GITEA_OWNER}/{GITEA_REPO}/pulls/{index}"


def _public_base_url() -> str:
    """Resolve the most public URL available for the Gitea web UI.

    Priority:
        1. GITEA_PUBLIC_URL (operator set the full URL explicitly)
        2. https://<GITEA_REPO>-git.<GITEA_PUBLIC_DOMAIN> (domain-only convention)
        3. GITEA_URL (localhost fallback for dev)
    """
    if GITEA_PUBLIC_URL:
        return GITEA_PUBLIC_URL
    if GITEA_PUBLIC_DOMAIN and GITEA_REPO:
        return f"https://{GITEA_REPO}-git.{GITEA_PUBLIC_DOMAIN}"
    return GITEA_URL


# ── Gitea Actions workflow API (AGENTS.md §24.5) ──────────────────────────


def list_workflow_runs(
    branch: str | None = None,
    head_sha: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List workflow runs filtered by branch / head_sha / status.

    status: queued | in_progress | completed | waiting | failure | success
    """
    params: dict = {"limit": limit}
    if branch:
        params["branch"] = branch
    if head_sha:
        params["head_sha"] = head_sha
    if status:
        params["status"] = status
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/actions/runs", params=params)
    if r.status_code >= 300:
        raise GiteaError(f"list_workflow_runs failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if isinstance(data, dict):
        return data.get("workflow_runs") or data.get("runs") or []
    return data if isinstance(data, list) else []


def get_workflow_run(run_id: int) -> dict:
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/actions/runs/{run_id}")
    if r.status_code >= 300:
        raise GiteaError(f"get_workflow_run({run_id}) failed: {r.status_code}")
    return r.json()


def get_run_jobs(run_id: int) -> list[dict]:
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/actions/runs/{run_id}/jobs")
    if r.status_code >= 300:
        raise GiteaError(f"get_run_jobs({run_id}) failed: {r.status_code}")
    data = r.json()
    if isinstance(data, dict):
        return data.get("jobs") or []
    return data if isinstance(data, list) else []


def get_job_logs(job_id: int) -> str:
    """Download the log text of a specific workflow job."""
    import httpx

    _require_config()
    r = httpx.get(
        f"{GITEA_API_URL}/repos/{GITEA_OWNER}/{GITEA_REPO}/actions/jobs/{job_id}/logs",
        headers=_headers(),
        timeout=30,
    )
    if r.status_code >= 300:
        raise GiteaError(f"get_job_logs({job_id}) failed: {r.status_code}")
    return r.text


def get_commit_statuses(sha: str) -> list[dict]:
    """Return status checks posted against a commit (fallback when the
    Actions API isn't exposed the way we expect).
    """
    r = _api("GET", f"/repos/{GITEA_OWNER}/{GITEA_REPO}/statuses/{sha}")
    if r.status_code >= 300:
        raise GiteaError(f"get_commit_statuses({sha}) failed: {r.status_code}")
    data = r.json()
    return data if isinstance(data, list) else []


def wait_for_checks(
    pr_index: int,
    timeout_s: int = 600,
    poll_interval_s: int = 15,
) -> dict:
    """Block until the pipeline for a PR's head SHA finishes or times out.

    Returns:
        {
            "status": "success" | "failure" | "timeout" | "no_runs" | "error",
            "elapsed_s": int,
            "runs": [list of run dicts],
            "failed_jobs": [list of failed job dicts] (on failure),
            "head_sha": "...",
        }
    """
    import time as _t

    try:
        pr = get_pr(pr_index)
    except GiteaError as exc:
        return {"status": "error", "error": str(exc), "elapsed_s": 0}

    head_sha = (pr.get("head") or {}).get("sha", "")
    head_ref = (pr.get("head") or {}).get("ref", "")
    if not head_sha:
        return {"status": "error", "error": "no head sha", "elapsed_s": 0}

    start = _t.monotonic()
    last_runs: list[dict] = []
    while _t.monotonic() - start < timeout_s:
        elapsed = int(_t.monotonic() - start)
        try:
            runs = list_workflow_runs(head_sha=head_sha, limit=20)
        except GiteaError:
            # Fall back to branch-scoped query
            try:
                runs = list_workflow_runs(branch=head_ref, limit=20)
            except GiteaError:
                runs = []

        if not runs:
            # Fall back to plain commit statuses
            try:
                statuses = get_commit_statuses(head_sha)
            except GiteaError:
                statuses = []
            if statuses:
                state = statuses[0].get("status") or statuses[0].get("state")
                if state == "success":
                    return {"status": "success", "elapsed_s": elapsed, "runs": [], "head_sha": head_sha}
                if state in ("failure", "error"):
                    return {
                        "status": "failure",
                        "elapsed_s": elapsed,
                        "runs": [],
                        "failed_jobs": [],
                        "head_sha": head_sha,
                        "statuses": statuses,
                    }
            _t.sleep(poll_interval_s)
            continue

        last_runs = runs
        matching = [r for r in runs if r.get("head_sha") == head_sha] or runs

        pending = [r for r in matching if r.get("status") not in ("completed", "success", "failure")]
        if pending:
            _t.sleep(poll_interval_s)
            continue

        failed = [
            r for r in matching
            if r.get("conclusion") in ("failure", "cancelled", "timed_out")
            or r.get("status") == "failure"
        ]
        if failed:
            failed_jobs: list[dict] = []
            for run in failed:
                try:
                    jobs = get_run_jobs(run.get("id"))
                    for j in jobs:
                        if j.get("conclusion") in ("failure", "cancelled", "timed_out") or j.get("status") == "failure":
                            failed_jobs.append({**j, "run_id": run.get("id"), "workflow": run.get("name")})
                except GiteaError:
                    continue
            return {
                "status": "failure",
                "elapsed_s": elapsed,
                "runs": matching,
                "failed_jobs": failed_jobs,
                "head_sha": head_sha,
            }

        return {"status": "success", "elapsed_s": elapsed, "runs": matching, "head_sha": head_sha}

    return {"status": "timeout", "elapsed_s": timeout_s, "runs": last_runs, "head_sha": head_sha}


# ── Bot tool entry point ──────────────────────────────────────────────────


def call(query: str, ctx: dict) -> str:
    """Entry point for the bot's tool-calling loop.

    Parses a simple command format and dispatches to the right function.
    """
    try:
        _require_config()
    except GiteaError as exc:
        return f"(gitea tool unavailable: {exc})"

    q = query.strip()
    if not q:
        return "(gitea: empty query — try 'list_prs' or 'get_pr <n>')"

    # Parse: "<command> <args>"
    parts = q.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    try:
        if cmd in ("list_prs", "list", "prs"):
            prs = list_prs(state="open", limit=20)
            if not prs:
                return "no open PRs"
            lines = [f"{len(prs)} open PRs:"]
            for pr in prs[:10]:
                title = pr.get("title", "")[:80]
                num = pr.get("number")
                author = (pr.get("user") or {}).get("login", "?")
                head = (pr.get("head") or {}).get("ref", "?")
                lines.append(f"  #{num} {title} · {author} · {head}")
            return "\n".join(lines)

        if cmd in ("get_pr", "pr", "show"):
            m = re.search(r"\d+", rest)
            if not m:
                return "(need a PR number: 'get_pr <n>')"
            n = int(m.group())
            pr = get_pr(n)
            files = get_pr_files(n)
            out = [
                f"PR #{n}: {pr.get('title')}",
                f"  author: {(pr.get('user') or {}).get('login', '?')}",
                f"  branch: {(pr.get('head') or {}).get('ref', '?')} → {(pr.get('base') or {}).get('ref', '?')}",
                f"  state: {pr.get('state')}  mergeable: {pr.get('mergeable')}",
                f"  files changed: {len(files)}",
                f"  url: {pr_url(n)}",
            ]
            if pr.get("body"):
                out.append(f"  body: {pr['body'][:300]}")
            return "\n".join(out)

        if cmd in ("merge_pr", "merge"):
            m = re.search(r"\d+", rest)
            if not m:
                return "(need a PR number)"
            n = int(m.group())
            result = merge_pr(n)
            return f"merged PR #{n} via {result['method']} · {pr_url(n)}"

        if cmd in ("close_pr", "close", "reject"):
            m = re.search(r"\d+", rest)
            if not m:
                return "(need a PR number)"
            n = int(m.group())
            close_pr(n)
            return f"closed PR #{n} · {pr_url(n)}"

        if cmd in ("comment_pr", "comment"):
            m = re.match(r"\s*(\d+)\s+(.+)", rest, re.DOTALL)
            if not m:
                return "(format: 'comment_pr <n> <body>')"
            n = int(m.group(1))
            body = m.group(2)
            post_comment(n, body)
            return f"commented on PR #{n}"

        if cmd == "open_pr":
            # Format: "open_pr <title>::<body>::<head>[::<base>]"
            segments = rest.split("::")
            if len(segments) < 3:
                return "(format: 'open_pr <title>::<body>::<head>[::<base>]')"
            title = segments[0].strip()
            body = segments[1].strip()
            head = segments[2].strip()
            base = segments[3].strip() if len(segments) > 3 else "main"
            pr = open_pr(title, body, head, base)
            n = pr.get("number")
            return f"opened PR #{n}: {title} · {pr_url(n)}"

        return (
            f"(unknown gitea command: {cmd}. "
            f"Try: list_prs | get_pr <n> | merge_pr <n> | close_pr <n> | "
            f"comment_pr <n> <body> | open_pr <title>::<body>::<head>)"
        )

    except GiteaError as exc:
        return f"(gitea error: {exc})"
    except Exception as exc:
        return f"(gitea unexpected error: {exc})"
