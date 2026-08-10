"""dispatch_agent — spawn SANDBOXED coding agents (Cursor, Claude, Aider, custom).

When the LLM decides a task requires code changes, it calls this tool with
a task description. The tool:

    1. Creates a throwaway git branch (`bot/<slug>-<timestamp>`)
    2. Launches a Docker container with HARD isolation:
         - Only the project root is mounted (as /workspace)
         - --network=none by default (no outbound access)
         - --read-only rootfs with tmpfs /tmp
         - cpu + memory limits
         - No host credentials, no ~/.ssh, no ~/.aws, no /etc secrets
       The container has access to NOTHING outside the project folder.
    3. Inside the container, runs the operator-configured $AGENT_COMMAND
       (e.g., bot/runners/cursor.sh) which invokes the coding agent.
    4. Caps concurrency at $AGENT_MAX_CONCURRENT (default 3).
    5. Times out after $AGENT_TIMEOUT_S (default 1800s).
    6. Captures stdout/stderr to logs/agent-<branch>.log.
    7. Returns the branch name for human review — NEVER auto-merges.

Why the sandbox: sub-agents are LLM-driven and cannot be trusted with the
operator's whole project tree. A bad prompt, a hallucination, or a prompt-injection
could let them read credentials, touch unrelated projects, or exfiltrate
data. The Docker sandbox bounds the blast radius to the project root and
a throwaway branch. See AGENTS.md §22 for the full rules.

If the sub-agent needs capabilities beyond the project root (querying
another project, hitting an external API, reading a database), it must emit
a structured request that the ORCHESTRATION bot (running outside the
sandbox, i.e. bot/bot.py) can pick up and fulfill via a brokered function
call. The sub-agent never reaches out directly.

Escape hatch for local dev:
    AGENT_SANDBOX=none
disables the Docker wrapper entirely and runs the runner in a plain
subprocess on the host. Never use this in production.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

NAME = "dispatch_agent"
DESCRIPTION = (
    "Dispatch a coding agent (Cursor, Claude Code, Aider, or custom runner) "
    "to complete a task that requires writing or changing code. The agent "
    "runs inside a hard-isolated Docker sandbox (no network, only the "
    "project root mounted, read-only rootfs, cpu/memory capped). Works on "
    "a throwaway git branch — never touches main, never auto-merges. Use "
    "for: implementing a feature, fixing a bug, refactoring, writing tests. "
    "If the task needs capabilities beyond the project root (external APIs, "
    "other projects), DO NOT dispatch an agent — instead use capability_broker or "
    "available tools to compose the needed capability first."
)

AGENT_COMMAND = os.environ.get("AGENT_COMMAND", "")
AGENT_DISPATCHER = os.environ.get("AGENT_DISPATCHER", "")
MAX_CONCURRENT = int(os.environ.get("AGENT_MAX_CONCURRENT", "3"))
TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_S", "1800"))
BRANCH_PREFIX = os.environ.get("AGENT_BRANCH_PREFIX", "bot/")

# Sandbox config (see AGENTS.md §22)
SANDBOX_MODE = os.environ.get("AGENT_SANDBOX", "docker").lower()  # docker | none
SANDBOX_IMAGE = os.environ.get("AGENT_SANDBOX_IMAGE", "")
SANDBOX_NETWORK = os.environ.get("AGENT_SANDBOX_NETWORK", "none")
SANDBOX_CPUS = os.environ.get("AGENT_SANDBOX_CPUS", "2")
SANDBOX_MEMORY = os.environ.get("AGENT_SANDBOX_MEMORY", "2g")
# Comma-separated list of env vars to pass INTO the sandbox. Only these are
# forwarded — everything else is stripped. Defaults cover the common LLM keys.
SANDBOX_FORWARD_ENV = os.environ.get(
    "AGENT_SANDBOX_FORWARD_ENV",
    "OPENAI_API_KEY,ANTHROPIC_API_KEY,OPENAI_BASE_URL,LLM_ROUTER_URL,LLM_MODEL",
).split(",")

_active_agents = 0
_lock = threading.Lock()


def _slug(text: str) -> str:
    """Turn a free-text task into a git-branch-safe slug."""
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", text.lower()).strip("-")
    return s[:40] or "task"


def _git(*args, cwd: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _validate_sandbox_config() -> str | None:
    """Return an error message if the sandbox config is invalid, else None."""
    if SANDBOX_MODE == "none":
        # Explicit opt-out — allowed only with a clear warning
        return None
    if SANDBOX_MODE != "docker":
        return (
            f"AGENT_SANDBOX={SANDBOX_MODE} is not supported (valid: docker|none). "
            f"Use 'docker' for production or 'none' ONLY for local dev."
        )
    # Docker mode — need the docker binary and a sandbox image
    if shutil.which("docker") is None:
        return (
            "docker binary not found on PATH. Either install Docker, "
            "or set AGENT_SANDBOX=none (ONLY for local dev — unsafe)."
        )
    if not SANDBOX_IMAGE:
        return (
            "AGENT_SANDBOX_IMAGE is not set. Build or pull a sandbox image "
            "that contains your coding agent (Cursor CLI, Claude Code CLI, "
            "Aider, etc.), then set:\n"
            "    AGENT_SANDBOX_IMAGE=ghcr.io/you/agent-sandbox:latest\n"
            "Or set AGENT_SANDBOX=none for local dev (no isolation — unsafe)."
        )
    return None


def call(query: str, ctx: dict) -> str:
    global _active_agents

    if not AGENT_COMMAND:
        return (
            "(AGENT_COMMAND not set — configure an operator-supplied runner "
            "like bot/runners/cursor.sh, runners/claude_code.sh, or "
            "runners/aider.sh, then set AGENT_DISPATCHER and AGENT_COMMAND "
            "in .env)"
        )

    err = _validate_sandbox_config()
    if err:
        return f"(sandbox config error: {err})"

    with _lock:
        if _active_agents >= MAX_CONCURRENT:
            return (
                f"(agent dispatch refused — {_active_agents}/{MAX_CONCURRENT} "
                f"agents already running; wait or raise AGENT_MAX_CONCURRENT)"
            )
        _active_agents += 1

    try:
        return _dispatch(query, ctx)
    finally:
        with _lock:
            _active_agents -= 1


def _compile_memory_brief(task: str, branch: str, repo_root: Path) -> Path | None:
    """Build a pre-flight memory brief for the sub-agent.

    Queries the project's local memory and (if MEMORY_STORE_URL is set) the
    long-term store for memories relevant to the task, then writes a compact
    markdown file to memory/_relevant-for-<branch>.md that the sandbox has
    mounted. The sub-agent's runner is expected to read this file first.

    Returns the path written (relative to repo_root) or None on failure.
    """
    try:
        # Reuse the existing tool modules to avoid duplicating logic.
        # These imports are guarded because dispatch_agent may be imported
        # without the full bot/tools sys.path setup.
        sys.path.insert(0, str(repo_root / "bot"))
        from tools import read_memory_local  # type: ignore
        try:
            # Optional: only present when an operator has wired a shared
            # cross-project memory store. Absent in a default install.
            from tools import read_memory_longterm  # type: ignore
            have_lt = bool(os.environ.get("MEMORY_STORE_URL"))
        except ImportError:
            read_memory_longterm = None
            have_lt = False

        mem_dir = repo_root / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        brief_name = f"_relevant-for-{branch.replace('/', '_')}.md"
        brief_path = mem_dir / brief_name

        project = repo_root.name
        lines = [
            f"# Relevant memories for task: {task}",
            f"",
            f"> Auto-compiled by bot/tools/dispatch_agent.py before dispatch.",
            f"> Delete after the agent finishes — it's gitignored.",
            f"",
            f"**Task:** {task}",
            f"**Branch:** {branch}",
            f"**Compiled:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            f"",
            f"## Instructions to the sub-agent",
            f"",
            f"Read this file FIRST, before editing any code. It summarizes past",
            f"project experience + cross-project wisdom that's relevant to your",
            f"task. Adapt your approach based on what worked and failed before.",
            f"",
            f"You are running inside a sandboxed Docker container:",
            f"- Only the project root is mounted",
            f"- No outbound network",
            f"- If you need ANYTHING beyond the project root (other projects,",
            f"  external APIs, databases), write a REQUEST.json at the project",
            f"  root describing what you need — the orchestration bot will",
            f"  compose a brokered solution and write the result back.",
            f"- Do NOT try to reach out directly; you will fail and leak your",
            f"  attempt to the audit log.",
            f"",
            f"## Project-local lessons",
            f"",
        ]

        local_ctx = {"project": project, "config": {}}
        try:
            local_result = read_memory_local.call(task, local_ctx)
        except Exception as exc:
            local_result = f"(local memory query failed: {exc})"
        lines.append(local_result)
        lines.append("")

        if have_lt and read_memory_longterm is not None:
            lines.append("## Cross-project lessons (long-term store)")
            lines.append("")
            try:
                lt_result = read_memory_longterm.call(task, local_ctx)
            except Exception as exc:
                lt_result = f"(long-term memory query failed: {exc})"
            lines.append(lt_result)
            lines.append("")
        else:
            lines.append("## Cross-project lessons")
            lines.append("")
            lines.append("(MEMORY_STORE_URL not set — no long-term memories available)")
            lines.append("")

        lines.append("## Past sub-agent runs on similar tasks")
        lines.append("")
        sar_ctx = {"project": project, "config": {}}
        try:
            sar_result = read_memory_local.call(
                f"category=sub_agent_run; query={task}", sar_ctx
            )
        except Exception as exc:
            sar_result = f"(sub_agent_run query failed: {exc})"
        lines.append(sar_result)

        brief_path.write_text("\n".join(lines) + "\n")
        return brief_path
    except Exception as exc:
        # Brief compilation is best-effort — don't fail the dispatch
        return None


def _capture_sub_agent_run(
    task: str,
    branch: str,
    runner: str,
    sandbox_mode: str,
    elapsed: int,
    ok: bool,
    diff_stat: str,
    log_path: Path,
    repo_root: Path,
) -> Path | None:
    """Write a memory file capturing the outcome of the dispatched sub-agent.

    Lands in memory/sub_agent_runs/. Marked promote=pending by default for
    successful novel-looking runs so the operator can review + promote to
    the long-term store.
    """
    try:
        mem_dir = repo_root / "memory" / "sub_agent_runs"
        mem_dir.mkdir(parents=True, exist_ok=True)

        # Auto-increment ID
        existing = []
        for p in mem_dir.glob("*.md"):
            if p.name in ("README.md", ".gitkeep"):
                continue
            m = re.match(r"^(\d{4})-", p.name)
            if m:
                existing.append(int(m.group(1)))
        mem_id = f"{(max(existing) + 1 if existing else 1):04d}"

        slug = _slug(task)
        filename = f"{mem_id}-{runner}-{slug}.md"
        path = mem_dir / filename

        project = repo_root.name
        shape = os.environ.get("PROJECT_SHAPE", "unknown")
        lang = os.environ.get("PROJECT_LANG", "unknown")
        date = time.strftime("%Y-%m-%d")
        outcome = "success" if ok else "failure"
        # Promote only successful runs for review; failures are usually
        # project-specific noise unless the operator decides otherwise.
        promote = "pending" if ok else "no"
        # Confidence: low by default — one run isn't enough to generalize.
        confidence = "low"

        # Pull any REQUEST.json that the sub-agent might have written (see
        # the brokering pattern in AGENTS.md §22)
        request_path = repo_root / "REQUEST.json"
        broker_request = None
        if request_path.exists():
            try:
                broker_request = json.loads(request_path.read_text())
            except Exception:
                broker_request = {"raw": request_path.read_text()[:500]}

        frontmatter = [
            "---",
            f"name: {runner} · {task[:70]}",
            f'id: "{mem_id}"',
            "type: sub_agent_run",
            f"date: {date}",
            f"project: {project}",
            f"shape: {shape}",
            f"lang: {lang}",
            f"tags: [{runner}, {outcome}, sub-agent]",
            f"confidence: {confidence}",
            f"outcome: {outcome}",
            f"promote: {promote}",
            f"author: bot",
            f"agent_task: {json.dumps(task)}",
            f"agent_branch: {branch}",
            "references:",
            "  - type: branch",
            f"    ref: {branch}",
            "  - type: log",
            f"    ref: {log_path.relative_to(repo_root) if repo_root in log_path.parents else log_path}",
            "---",
            "",
        ]

        body_lines = [
            "## Task",
            "",
            "```",
            task,
            "```",
            "",
            "## Runner",
            "",
            f"- Runner: `{runner}`",
            f"- Sandbox mode: `{sandbox_mode}`",
            f"- Duration: {elapsed}s",
            "",
            "## Outcome",
            "",
            f"- Status: **{outcome}**",
            f"- Diff stat: {diff_stat.strip() or '(no changes)'}",
            "",
        ]

        if broker_request is not None:
            body_lines.extend([
                "## Broker request",
                "",
                "The sub-agent wrote a REQUEST.json asking for capabilities",
                "beyond the project sandbox:",
                "",
                "```json",
                json.dumps(broker_request, indent=2)[:2000],
                "```",
                "",
            ])

        body_lines.extend([
            "## Lesson",
            "",
            "*(auto-capture — review and edit to describe what this run teaches.",
            "If nothing to learn, set `promote: no` and leave this section as-is.",
            "If the lesson generalizes, set `promote: yes` after editing.)*",
            "",
        ])

        path.write_text("\n".join(frontmatter) + "\n".join(body_lines) + "\n")
        return path
    except Exception:
        return None


def _dispatch(task: str, ctx: dict) -> str:
    # Verify we're in a git worktree before trying to branch
    code, out = _git("rev-parse", "--show-toplevel")
    if code != 0:
        return f"(not a git repo — cannot branch: {out})"
    repo_root_str = out.strip()
    repo_root = Path(repo_root_str)

    # Fresh branch off current HEAD (created on the host, inside the mount)
    branch = f"{BRANCH_PREFIX}{_slug(task)}-{int(time.time())}"
    code, out = _git("checkout", "-b", branch, cwd=repo_root_str)
    if code != 0:
        return f"(branch creation failed: {out})"

    # Pre-flight: compile the memory brief into memory/_relevant-for-<branch>.md
    # (best-effort; don't fail the dispatch if this errors out)
    brief_path = _compile_memory_brief(task, branch, repo_root)

    log_path = repo_root / "logs" / f"agent-{branch.replace('/', '_')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    sandbox_mode_used = SANDBOX_MODE

    try:
        with log_path.open("w") as log_file:
            log_file.write(
                f"# dispatched: {task}\n"
                f"# branch: {branch}\n"
                f"# sandbox: {sandbox_mode_used}\n"
                f"# image: {SANDBOX_IMAGE or '(none)'}\n"
                f"# network: {SANDBOX_NETWORK}\n"
                f"# cpus: {SANDBOX_CPUS}\n"
                f"# memory: {SANDBOX_MEMORY}\n"
                f"# at: {time.ctime()}\n\n"
            )
            log_file.flush()

            if SANDBOX_MODE == "docker":
                cmd = _build_docker_command(task, branch, ctx, repo_root_str)
                log_file.write(f"# sandbox command:\n# {shlex.join(cmd)}\n\n")
                if brief_path:
                    log_file.write(f"# memory brief: {brief_path.relative_to(repo_root)}\n\n")
                log_file.flush()
                env = os.environ.copy()
                # Host-side env vars needed by docker client itself
                r = subprocess.run(
                    cmd,
                    cwd=repo_root_str,
                    env=env,
                    timeout=TIMEOUT_S,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            else:
                # AGENT_SANDBOX=none — direct subprocess on the host (unsafe)
                log_file.write("# WARNING: running unsandboxed on the host (AGENT_SANDBOX=none)\n\n")
                if brief_path:
                    log_file.write(f"# memory brief: {brief_path.relative_to(repo_root)}\n\n")
                log_file.flush()
                env = os.environ.copy()
                env["TASK"] = task
                env["BRANCH"] = branch
                env["PROJECT"] = ctx.get("project", "")
                r = subprocess.run(
                    ["sh", "-c", AGENT_COMMAND],
                    cwd=repo_root_str,
                    env=env,
                    timeout=TIMEOUT_S,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )

        elapsed = int(time.monotonic() - start)
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        # Capture the timeout as a memory so the bot learns which tasks run long
        _capture_sub_agent_run(
            task, branch, AGENT_DISPATCHER or "custom", sandbox_mode_used,
            TIMEOUT_S, False, "(timed out)", log_path, repo_root,
        )
        return (
            f"(agent timed out after {TIMEOUT_S}s on branch {branch}; "
            f"log: {log_path.relative_to(repo_root)})"
        )
    except Exception as exc:
        return f"(agent dispatch error on branch {branch}: {exc})"

    # Check what the agent actually changed
    _code, diff_stat = _git("diff", "--stat", "HEAD", cwd=repo_root_str)
    if not diff_stat.strip():
        _code, diff_stat = _git("diff", "--stat", "main..HEAD", cwd=repo_root_str)

    # Post-flight step 1: capture the run as a memory for future reference
    memory_path = _capture_sub_agent_run(
        task, branch, AGENT_DISPATCHER or "custom", sandbox_mode_used,
        elapsed, ok, diff_stat, log_path, repo_root,
    )

    # Post-flight step 2: push to Gitea and open a PR (if Gitea is configured
    # AND the sub-agent made commits). The orchestration bot — NOT the sandbox
    # — holds the Gitea token and performs these operations.
    pr_info = _push_and_open_pr(task, branch, ok, diff_stat, repo_root_str, memory_path)

    # Post-flight step 3: wait for Gitea Actions pipeline. If it fails,
    # capture a memory and (within the circuit breaker limit) dispatch a
    # new sub-agent to fix the failing tests / lints / build.
    pipeline_info = ""
    autofix_info = ""
    if pr_info.get("pr_number") and os.environ.get("GITEA_URL"):
        pipeline_info = _watch_pipeline_post_dispatch(pr_info["pr_number"])
        if "failure" in pipeline_info.lower() and _should_autofix(memory_path):
            autofix_info = _autofix_loop(
                pr_info["pr_number"], task, branch, ctx, memory_path, pipeline_info
            )

    # Post-flight step 4: optionally trigger an automatic review of the PR
    review_info = ""
    if pr_info.get("pr_number") and os.environ.get("GITEA_AUTO_REVIEW", "false").lower() == "true":
        review_info = _auto_review(pr_info["pr_number"], ctx)

    summary = (
        f"agent ({AGENT_DISPATCHER or 'custom'}, sandbox={sandbox_mode_used}) "
    )
    summary += "succeeded" if ok else "exited with error"
    summary += f" in {elapsed}s on branch {branch}"
    if diff_stat.strip():
        last_line = diff_stat.splitlines()[-1] if diff_stat.splitlines() else "no changes"
        summary += f" · {last_line}"
    summary += f" · log: {log_path.relative_to(repo_root)}"
    if memory_path:
        summary += f" · memory: {memory_path.relative_to(repo_root)}"
    if pr_info.get("pr_url"):
        summary += f" · PR: {pr_info['pr_url']}"
    elif pr_info.get("error"):
        summary += f" · PR: ({pr_info['error']})"
    if pipeline_info:
        summary += f" · pipeline: {pipeline_info.splitlines()[0][:100]}"
    if autofix_info:
        summary += f" · autofix: {autofix_info}"
    if review_info:
        summary += f" · review: {review_info}"
    if not pr_info.get("pr_url"):
        summary += " · human review required before merge"
    return summary


def _push_and_open_pr(
    task: str,
    branch: str,
    ok: bool,
    diff_stat: str,
    repo_root_str: str,
    memory_path: Path | None,
) -> dict:
    """Push the branch to Gitea and open a PR. Returns {pr_url, pr_number}
    on success or {error} on failure. Best-effort: failures never block
    the dispatch return.
    """
    if not ok:
        return {"error": "sub-agent failed — not opening a PR"}
    if not diff_stat.strip():
        return {"error": "no commits — not opening a PR"}
    if not os.environ.get("GITEA_URL") or not os.environ.get("GITEA_TOKEN"):
        return {}  # gitea not configured — silent skip

    try:
        sys.path.insert(0, str(Path(repo_root_str) / "bot"))
        from tools import gitea  # type: ignore
    except Exception as exc:
        return {"error": f"gitea import failed: {exc}"}

    # 1. Push the branch
    try:
        pushed, push_out = gitea.push_branch(branch, repo_root=repo_root_str)
    except Exception as exc:
        return {"error": f"push error: {exc}"}
    if not pushed:
        return {"error": f"push failed: {push_out[:200]}"}

    # 2. Open the PR
    title = (task.splitlines()[0] if task else branch)[:70]
    body_lines = [
        "**Automated PR from dispatched sub-agent**",
        "",
        f"**Task:**",
        "",
        "```",
        task[:2000],
        "```",
        "",
        f"**Runner:** `{AGENT_DISPATCHER or 'custom'}`",
        f"**Sandbox:** `{SANDBOX_MODE}`"
        + (f" / image `{SANDBOX_IMAGE}`" if SANDBOX_MODE == "docker" and SANDBOX_IMAGE else ""),
        f"**Branch:** `{branch}`",
        "",
        "**Diff stat:**",
        "",
        "```",
        diff_stat[:2000] or "(no changes)",
        "```",
    ]
    if memory_path:
        body_lines.extend([
            "",
            f"**Source memory:** `{memory_path.as_posix()}`",
        ])
    body_lines.extend([
        "",
        "---",
        "",
        "*Review with `make review PR=<number>` to trigger the automated review agent, "
        "or inspect the diff in the Gitea web UI and merge manually.*",
    ])
    body = "\n".join(body_lines)

    try:
        pr = gitea.open_pr(title=title, body=body, head=branch, base="main")
    except Exception as exc:
        return {"error": f"open_pr failed: {exc}"}

    pr_number = pr.get("number")
    pr_url = gitea.pr_url(pr_number)
    return {"pr_number": pr_number, "pr_url": pr_url}


def _auto_review(pr_number: int, ctx: dict) -> str:
    """Trigger review_pr in-process for a freshly-opened PR.
    Returns a short status string for the summary.
    """
    try:
        sys.path.insert(0, "bot")
        from tools import review_pr  # type: ignore
        return review_pr.call(str(pr_number), ctx)[:200]
    except Exception as exc:
        return f"(auto-review failed: {exc})"


# ── Self-aware pipeline integration (AGENTS.md §24.5) ─────────────────────


AUTOFIX_MAX_ATTEMPTS = int(os.environ.get("AUTOFIX_MAX_ATTEMPTS", "3"))


def _watch_pipeline_post_dispatch(pr_number: int) -> str:
    """Wait for the Gitea Actions pipeline to finish after a dispatch-opened
    PR. Returns a one-line summary. Failures include the first few log
    lines so the autofix dispatch has something to reason about.
    """
    try:
        sys.path.insert(0, "bot")
        from tools import watch_pipeline  # type: ignore
        return watch_pipeline.call(str(pr_number), ctx={})
    except Exception as exc:
        return f"(watch_pipeline failed: {exc})"


def _should_autofix(memory_path: Path | None) -> bool:
    """Circuit breaker — check the sub_agent_run memory for fix_attempts
    frontmatter and return True only if we're under the limit.
    """
    if not memory_path or not memory_path.exists():
        return AUTOFIX_MAX_ATTEMPTS > 0
    try:
        text = memory_path.read_text()
    except Exception:
        return True
    m = re.search(r"^fix_attempts:\s*(\d+)\s*$", text, re.MULTILINE)
    attempts = int(m.group(1)) if m else 0
    return attempts < AUTOFIX_MAX_ATTEMPTS


def _bump_fix_attempts(memory_path: Path | None):
    """Increment fix_attempts: N in the memory frontmatter."""
    if not memory_path or not memory_path.exists():
        return
    try:
        text = memory_path.read_text()
    except Exception:
        return
    m = re.search(r"^fix_attempts:\s*(\d+)\s*$", text, re.MULTILINE)
    if m:
        new_val = int(m.group(1)) + 1
        text = re.sub(
            r"^fix_attempts:\s*\d+\s*$",
            f"fix_attempts: {new_val}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Insert before the closing ---
        text = re.sub(
            r"(\nauthor: [^\n]+\n)",
            r"\1fix_attempts: 1\n",
            text,
            count=1,
        )
    memory_path.write_text(text)


def _autofix_loop(
    pr_number: int,
    original_task: str,
    original_branch: str,
    ctx: dict,
    memory_path: Path | None,
    pipeline_info: str,
) -> str:
    """Dispatch a new sub-agent to fix a failing pipeline.

    The new dispatch gets the original task + failure classification + log
    tail as its task description. Circuit breaker (_should_autofix) ensures
    we don't infinite-loop. The new dispatch goes through the normal
    dispatch → push → open PR → watch pipeline pathway, so a fix that ALSO
    fails will trigger another autofix attempt (up to AUTOFIX_MAX_ATTEMPTS).
    """
    _bump_fix_attempts(memory_path)

    # Construct a targeted fix task
    fix_task = (
        f"The pipeline for PR #{pr_number} on branch `{original_branch}` failed.\n\n"
        f"Original task:\n```\n{original_task[:1000]}\n```\n\n"
        f"Pipeline failure summary:\n{pipeline_info[:2000]}\n\n"
        f"Your job: diagnose the failure and fix it. Do NOT re-introduce the "
        f"original scope — only fix what's needed to make the pipeline green. "
        f"Read memory/_relevant-for-<branch>.md (pre-flight brief) first. "
        f"Before declaring success, run `make test` inside the sandbox — if "
        f"local tests don't pass, your fix is incomplete."
    )

    try:
        # Dispatch a new sub-agent. This recurses back into call() which
        # does the full flow: compile brief, sandbox, push, open PR, watch
        # pipeline. If the new PR's pipeline ALSO fails, the circuit
        # breaker in _should_autofix will eventually stop the loop.
        result = call(fix_task, ctx)
        return f"autofix dispatched → {result[:150]}"
    except Exception as exc:
        return f"(autofix dispatch error: {exc})"


def _build_docker_command(task: str, branch: str, ctx: dict, repo_root_str: str) -> list[str]:
    """Assemble the `docker run` command with all sandbox flags.

    Key isolation properties:
        - Only repo_root is mounted (no $HOME, no sibling projects, no host)
        - --network=<SANDBOX_NETWORK> (default 'none' — no outbound access)
        - --read-only rootfs with a writable /tmp tmpfs
        - --cap-drop=ALL to strip Linux capabilities
        - --security-opt no-new-privileges
        - --cpus and --memory limits
        - Only whitelisted env vars are forwarded (SANDBOX_FORWARD_ENV)
        - No host credentials, no ssh keys, no docker sock
    """
    container_name = f"{ctx.get('project', 'agent')}-dispatch-{int(time.time())}"

    cmd = [
        "docker", "run",
        "--rm",
        "--name", container_name,
        "--network", SANDBOX_NETWORK,
        "--read-only",
        "--tmpfs", "/tmp:exec,size=512m",
        "--tmpfs", "/workspace/.agent-home:exec,size=256m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--cpus", SANDBOX_CPUS,
        "--memory", SANDBOX_MEMORY,
        "--pids-limit", "256",
        "-v", f"{repo_root_str}:/workspace:rw",
        "-w", "/workspace",
        "-e", f"TASK={task}",
        "-e", f"BRANCH={branch}",
        "-e", f"PROJECT={ctx.get('project', '')}",
        "-e", "HOME=/workspace/.agent-home",
    ]

    # Forward whitelisted env vars only
    for var in SANDBOX_FORWARD_ENV:
        var = var.strip()
        if var and var in os.environ:
            cmd.extend(["-e", f"{var}={os.environ[var]}"])

    cmd.append(SANDBOX_IMAGE)
    # Runner script path is relative to /workspace (the project root)
    cmd.extend(["sh", "-c", AGENT_COMMAND])
    return cmd
