"""watch_pipeline — self-aware pipeline-failure detection for <name>.

A bot tool the LLM (or dispatch_agent) can call to wait for a PR's Gitea
Actions pipeline to finish, then report the result. On failure, it
downloads the failed job logs, classifies the failure, and returns a
structured report the LLM can reason about — or feeds to an auto-fix
dispatch.

This is ALSO used by the bot's background pipeline_watcher thread to
catch failures on PRs that weren't directly opened by dispatch_agent
(e.g. a human pushed a commit to an existing PR branch).

Usage:
    call("42")                           # wait for PR #42's pipeline
    call("pr=42; timeout=300")           # custom timeout
    call("pr=42; quick")                 # quick check, don't wait
"""
import os
import re
import sys
import time
from pathlib import Path

NAME = "watch_pipeline"
DESCRIPTION = (
    "Wait for a pull request's Gitea Actions pipeline to finish and report "
    "the result (success, failure, timeout). On failure, downloads the "
    "failed job logs, classifies the error (lint / test / build / runtime / "
    "dependency / unknown), and returns a structured report so you can "
    "reason about or fix the failure. Query format: '<pr-number>' or "
    "'pr=<n>; timeout=<seconds>; quick' (quick = one-shot check, no wait)."
)

PIPELINE_WAIT_TIMEOUT = int(os.environ.get("PIPELINE_WAIT_TIMEOUT", "600"))
PIPELINE_POLL_INTERVAL = int(os.environ.get("PIPELINE_POLL_INTERVAL", "15"))


# ── Failure classification ────────────────────────────────────────────────

_CLASSIFIERS = [
    ("lint", [
        r"ruff.*(error|warning)",
        r"eslint.*error",
        r"E\d{3}:",
        r"Parsing error:",
        r"format.*would.*rewrite",
    ]),
    ("test", [
        r"FAILED.*test_",
        r"AssertionError",
        r"(\d+) (failed|error)s? in \d+\.\d+s",  # pytest summary
        r"npm test.*failed",
        r"tests? failed",
        r"expect\(.*\)\.to",
        r"not ok \d+",                            # TAP
        r"✗",
    ]),
    ("build", [
        r"docker build.*failed",
        r"failed to solve",
        r"npm.*ERR.*build",
        r"vite.*build.*error",
        r"error.*Cannot find module",
        r"error.*No module named",
        r"gcc.*error",
        r"compilation terminated",
    ]),
    ("dependency", [
        r"package-lock.json.*out of sync",
        r"ERESOLVE could not resolve",
        r"Could not find a version that satisfies",
        r"pip install.*ERROR",
        r"permission denied.*(pull|login)",
    ]),
    ("runtime", [
        r"Traceback \(most recent call last\)",
        r"Unhandled.*exception",
        r"segmentation fault",
        r"OOMKilled",
        r"container.*exited.*code [1-9]",
    ]),
]


def classify_failure(log_text: str) -> str:
    """Return the first-matching classification or 'unknown'."""
    for category, patterns in _CLASSIFIERS:
        for pat in patterns:
            if re.search(pat, log_text, re.IGNORECASE | re.MULTILINE):
                return category
    return "unknown"


def extract_error_lines(log_text: str, max_lines: int = 40) -> list[str]:
    """Pull out the last few lines with error signals."""
    lines = log_text.splitlines()
    # Strategy: look for lines with "error", "FAIL", "Traceback", then
    # include some context around them
    error_indices = []
    for i, line in enumerate(lines):
        if re.search(r"error|FAIL|Traceback|✗|assertion", line, re.IGNORECASE):
            error_indices.append(i)
    if not error_indices:
        return lines[-max_lines:]
    # Return window around the last error
    last = error_indices[-1]
    start = max(0, last - 10)
    end = min(len(lines), last + 30)
    return lines[start:end][:max_lines]


# ── Memory writer ─────────────────────────────────────────────────────────


def _write_pipeline_failure_memory(
    pr_number: int,
    pr_url: str,
    failed_jobs: list[dict],
    classification: str,
    log_tail: list[str],
    elapsed_s: int,
) -> Path | None:
    """Capture the failure as a memory file for later analysis + learning."""
    try:
        mem_dir = Path("memory/pipeline_failures")
        mem_dir.mkdir(parents=True, exist_ok=True)

        existing = [int(m.group(1)) for p in mem_dir.glob("*.md")
                    if (m := re.match(r"^(\d{4})-", p.name))]
        mem_id = f"{(max(existing) + 1 if existing else 1):04d}"

        job_name = (failed_jobs[0].get("name") if failed_jobs else classification)[:40]
        slug = re.sub(r"[^a-z0-9-]+", "-", job_name.lower()).strip("-") or "failure"
        filename = f"{mem_id}-{pr_number}-{classification}-{slug}.md"
        path = mem_dir / filename

        project = os.environ.get("PROJECT_NAME", Path.cwd().name)
        shape = os.environ.get("PROJECT_SHAPE", "unknown")
        lang = os.environ.get("PROJECT_LANG", "unknown")

        frontmatter = [
            "---",
            f"name: PR #{pr_number} pipeline failure — {classification} in {job_name}",
            f'id: "{mem_id}"',
            "type: pipeline_failure",
            f"date: {time.strftime('%Y-%m-%d')}",
            f"project: {project}",
            f"shape: {shape}",
            f"lang: {lang}",
            f"tags: [pipeline, {classification}, ci]",
            "confidence: medium",
            "outcome: failure",
            "promote: pending",
            "author: bot",
            f"pr_number: {pr_number}",
            f"pr_url: {pr_url}",
            f"classification: {classification}",
            f"elapsed_s: {elapsed_s}",
            "---",
            "",
        ]
        body = [
            f"## Failed jobs ({len(failed_jobs)})",
            "",
        ]
        for j in failed_jobs[:5]:
            body.append(
                f"- `{j.get('name', '?')}` in workflow `{j.get('workflow', '?')}` "
                f"(run {j.get('run_id', '?')}, conclusion {j.get('conclusion', '?')})"
            )
        body.extend([
            "",
            f"## Classification: **{classification}**",
            "",
            "(Heuristic classification based on log patterns. Edit if wrong.)",
            "",
            "## Log tail",
            "",
            "```",
            *log_tail[:40],
            "```",
            "",
            "## Resolution",
            "",
            "*(filled in by the auto-fix dispatch or a human when the failure is resolved)*",
            "",
            "## Lesson",
            "",
            "*(edit: what pattern does this failure teach? What should future agents do "
            "differently? High-confidence lessons here are prime long-term promotion candidates.)*",
        ])
        path.write_text("\n".join(frontmatter) + "\n".join(body) + "\n")
        return path
    except Exception:
        return None


# ── Main entry ────────────────────────────────────────────────────────────


def _parse_query(query: str) -> dict:
    q = query.strip()
    out: dict = {"quick": False, "timeout": PIPELINE_WAIT_TIMEOUT}
    if q.isdigit():
        out["pr"] = int(q)
        return out
    if "=" in q or ";" in q:
        for pair in q.split(";"):
            pair = pair.strip()
            if pair == "quick":
                out["quick"] = True
            elif "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        if "pr" in out:
            try:
                out["pr"] = int(out["pr"])
            except ValueError:
                pass
        if "timeout" in out:
            try:
                out["timeout"] = int(out["timeout"])
            except ValueError:
                pass
        return out
    m = re.search(r"\d+", q)
    if m:
        out["pr"] = int(m.group())
    return out


def call(query: str, ctx: dict) -> str:
    parsed = _parse_query(query)
    pr_number = parsed.get("pr")
    if not pr_number:
        return "(watch_pipeline: need a PR number — try '42' or 'pr=42; timeout=300')"

    try:
        sys.path.insert(0, "bot")
        from tools import gitea
    except ImportError as exc:
        return f"(watch_pipeline: gitea module missing: {exc})"

    timeout = parsed.get("timeout", PIPELINE_WAIT_TIMEOUT)
    if parsed.get("quick"):
        timeout = 0  # single poll

    try:
        result = gitea.wait_for_checks(
            pr_index=pr_number,
            timeout_s=timeout,
            poll_interval_s=PIPELINE_POLL_INTERVAL,
        )
    except Exception as exc:
        return f"(watch_pipeline: wait_for_checks failed: {exc})"

    status = result.get("status", "unknown")
    elapsed = result.get("elapsed_s", 0)
    pr_url = gitea.pr_url(pr_number)

    if status == "success":
        return f"PR #{pr_number} pipeline: **success** ({elapsed}s) · {pr_url}"

    if status == "timeout":
        return (
            f"PR #{pr_number} pipeline: **timeout** after {timeout}s · {pr_url} "
            f"(still pending — try again or increase PIPELINE_WAIT_TIMEOUT)"
        )

    if status == "no_runs":
        return (
            f"PR #{pr_number}: no workflow runs found for head SHA. "
            f"Is .gitea/workflows/ci.yml present? Is the act_runner running? · {pr_url}"
        )

    if status == "error":
        return f"PR #{pr_number} pipeline: error — {result.get('error')}"

    # Failure path — download logs, classify, write memory
    failed_jobs = result.get("failed_jobs") or []
    all_logs: list[str] = []
    for j in failed_jobs[:3]:  # cap on log fetches
        try:
            log_text = gitea.get_job_logs(j.get("id"))
            all_logs.append(f"### {j.get('name', '?')}\n{log_text}")
        except Exception as exc:
            all_logs.append(f"### {j.get('name', '?')}\n(log fetch failed: {exc})")

    combined_log = "\n\n".join(all_logs)
    classification = classify_failure(combined_log)
    log_tail = extract_error_lines(combined_log)

    memory_path = _write_pipeline_failure_memory(
        pr_number=pr_number,
        pr_url=pr_url,
        failed_jobs=failed_jobs,
        classification=classification,
        log_tail=log_tail,
        elapsed_s=elapsed,
    )

    # Return a structured-ish summary for the LLM
    summary = (
        f"PR #{pr_number} pipeline: **failure** ({classification}, {elapsed}s) · "
        f"{len(failed_jobs)} failed jobs · {pr_url}"
    )
    if memory_path:
        summary += f" · memory: {memory_path}"
    if log_tail:
        # Include the last 10 error lines in the tool return so the LLM
        # can immediately start reasoning about the fix
        summary += "\n\nFailing lines:\n" + "\n".join(log_tail[-10:])[:1500]
    return summary
