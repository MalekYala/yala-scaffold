"""review_pr — LLM-based PR review agent for <name>.

When the orchestration bot wants a PR reviewed, it calls this tool with a
PR number. The tool:

    1. Fetches the PR (metadata + full diff + file list) from Gitea
    2. Finds the original task from memory/sub_agent_runs/ if the PR was
       opened by dispatch_agent
    3. Queries project memory (read_memory_local) for relevant past lessons
    4. Queries long-term memory (read_memory_longterm) for cross-project
       lessons if MEMORY_STORE_URL is set
    5. Asks the design advisor in #devs for a design-pattern sanity check (best-effort;
       skips if IRC isn't connected)
    6. Runs an LLM with a STRICT review prompt that evaluates:
         - Does the diff match the original task scope?
         - Are there out-of-scope changes?
         - Are there missing tests? (AGENTS.md §6)
         - Are docs updated? (AGENTS.md §7)
         - Any AGENTS.md rule violations?
         - Security smells?
    7. Parses the LLM verdict: merge | request_changes | reject
    8. Executes the verdict via Gitea API:
         merge → POST /pulls/<n>/merge (only if confidence is high enough)
         request_changes → POST /pulls/<n>/reviews with event=REQUEST_CHANGES
         reject → PATCH /pulls/<n> state=closed
    9. Captures the review in memory/pr_reviews/<n>-<slug>.md
   10. Returns a one-line summary for the bot's channel

Safety gates:
    - Auto-merge requires confidence >= GITEA_AUTO_MERGE_CONFIDENCE (default 'high')
    - Lower-confidence verdicts fall back to request_changes (NOT merge)
    - review_pr NEVER force-pushes, never modifies files, never touches main
    - All LLM outputs are sanitized before being posted to Gitea
    - The reviewer prompt explicitly forbids dispatching further sub-agents
"""
import json
import os
import re
import sys
import time
from pathlib import Path

NAME = "review_pr"
DESCRIPTION = (
    "Review a pull request on this project's Gitea and decide whether to "
    "merge, request changes, or reject it. The reviewer reads the diff, "
    "checks it against the original task (if the PR was opened by a "
    "dispatched sub-agent), cross-references project memory and the design advisor's "
    "design-pattern advice, then posts its verdict to Gitea. Auto-merges "
    "only high-confidence approvals — anything less becomes a "
    "request_changes review for human follow-up. Query format: "
    "'<pr-number>' or 'pr=<n>; focus=<what to emphasize>'."
)

# ── Config ────────────────────────────────────────────────────────────────

LLM_URL = os.environ.get("LLM_ROUTER_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "120"))

AUTO_MERGE_CONFIDENCE = os.environ.get("GITEA_AUTO_MERGE_CONFIDENCE", "high").lower()

MAX_DIFF_CHARS = int(os.environ.get("REVIEW_MAX_DIFF_CHARS", "40000"))


def _parse_query(query: str) -> dict:
    """Accept '<number>' or 'pr=<n>; focus=...' format."""
    q = query.strip()
    if q.isdigit():
        return {"pr": int(q)}
    out: dict = {}
    if ";" in q and "=" in q:
        for pair in q.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        if "pr" in out:
            try:
                out["pr"] = int(out["pr"])
            except ValueError:
                pass
        return out
    m = re.search(r"\d+", q)
    if m:
        return {"pr": int(m.group())}
    return {}


# ── Context gathering ─────────────────────────────────────────────────────


def _find_source_memory(branch: str) -> tuple[str, Path | None]:
    """If the PR came from dispatch_agent, find the sub_agent_run memory
    that describes the original task. Returns (task_description, path).
    """
    memory_dir = Path("memory/sub_agent_runs")
    if not memory_dir.exists():
        return "", None

    # The branch encodes: bot/<slug>-<timestamp>
    slug_match = re.search(r"bot/(.+?)(?:-\d+)?$", branch)
    slug = slug_match.group(1) if slug_match else branch.replace("/", "_")

    for p in sorted(memory_dir.glob("*.md"), reverse=True):
        text = p.read_text(errors="replace")
        if slug in p.name or branch in text:
            # Extract the task from frontmatter
            m = re.search(r'^agent_task:\s*"?(.+?)"?$', text, re.MULTILINE)
            if m:
                return m.group(1).strip().strip('"'), p
            # Fall back to the ## Task section
            m = re.search(r"## Task\s*\n\s*```\s*\n(.+?)\n```", text, re.DOTALL)
            if m:
                return m.group(1).strip(), p
    return "", None


def _gather_context(pr_body: str, task: str, files: list[dict], pr_number: int) -> dict:
    """Pull relevant context from other bot tools. Best-effort — failures
    just leave the corresponding context empty.
    """
    ctx: dict = {
        "memory_local": "",
        "memory_longterm": "",
        "pipeline": None,
        "test_quality": None,
    }

    sys.path.insert(0, "bot")

    # Query project memory for the task keywords
    try:
        from tools import read_memory_local
        query = task or pr_body[:200]
        ctx["memory_local"] = read_memory_local.call(query, ctx={"project": os.environ.get("PROJECT_NAME", "unknown")})
    except Exception as exc:
        ctx["memory_local"] = f"(memory_local query failed: {exc})"

    # Query long-term memory if configured
    if os.environ.get("MEMORY_STORE_URL"):
        try:
            from tools import read_memory_longterm
            query = task or pr_body[:200]
            ctx["memory_longterm"] = read_memory_longterm.call(query, ctx={"project": os.environ.get("PROJECT_NAME", "unknown")})
        except Exception as exc:
            ctx["memory_longterm"] = f"(memory_longterm query failed: {exc})"


    # Pipeline gate — wait for Gitea Actions to finish
    try:
        from tools import gitea  # type: ignore
        timeout = int(os.environ.get("PIPELINE_WAIT_TIMEOUT", "600"))
        poll = int(os.environ.get("PIPELINE_POLL_INTERVAL", "15"))
        ctx["pipeline"] = gitea.wait_for_checks(
            pr_index=pr_number,
            timeout_s=timeout,
            poll_interval_s=poll,
        )
    except Exception as exc:
        ctx["pipeline"] = {"status": "error", "error": str(exc)}

    # Test quality analysis on the changed files
    try:
        from tools import test_quality  # type: ignore
        ctx["test_quality"] = test_quality.analyze_files(files)
    except Exception as exc:
        ctx["test_quality"] = {"error": str(exc)}

    return ctx


# ── LLM review ────────────────────────────────────────────────────────────


REVIEW_SYSTEM_PROMPT = """You are a strict code review agent for the <name> project.

Your job: read a pull request diff and decide whether to MERGE, REQUEST CHANGES, or REJECT it.

HARD RULES:
1. If the PR's changes don't match the original task, request changes citing the scope drift.
2. If the PR touches files outside the task scope without justification, request changes.
3. **Tests must be real functional validating tests, not just present.** Specifically:
   - Reject tautological tests: `assert True`, `assert 1 == 1`, `expect(true).toBe(true)`, empty test bodies.
   - Reject mock-only tests that set up a mock, call a function that uses it, then only assert that the mock was called. Real tests verify BEHAVIOR with REAL inputs and REAL outputs.
   - For every new public function / endpoint / class: require at least one test with real inputs, real assertions on real outputs, AND at least one edge case.
   - If the test_quality report (provided in the context) shows anti-patterns or a score below 0.8, treat this as missing-tests and request changes citing the specific anti-patterns.
   - If a source file was changed but no corresponding test file has new assertions in the diff, treat as missing tests.
4. If user-visible behavior changed without docs updates (README.md, docs/, CHANGELOG.md), request changes (AGENTS.md §7).
5. If you see potential security issues (SQL injection, command injection, credentials in code, disabled TLS, unescaped shell args, etc.), REJECT.
6. **The Gitea pipeline result is binding.** If the pipeline report (provided in the context) shows the CI pipeline is failing, your verdict MUST be request_changes and your feedback MUST cite the failing job + classification. Do not merge a red pipeline under any circumstance.
7. Only MERGE a PR that satisfies ALL of:
   - Diff is small, focused, and aligned with the task
   - Tests exist AND test_quality score ≥ 0.8 AND cover the changed source files
   - User-visible behavior changes have docs updates
   - Pipeline is green
   - No security smells
8. When uncertain, request_changes is always preferred over merge.

You MUST respond with exactly this format:

VERDICT: merge | request_changes | reject
CONFIDENCE: high | medium | low
RATIONALE:
<3-10 bullet points explaining your decision. Cite specific files, AGENTS.md sections, pipeline job names, and test_quality findings.>

FEEDBACK:
<bulleted actionable feedback the author can use to fix the PR. Required for request_changes and reject. Optional for merge.>

Do NOT include any other text. Do NOT invoke other tools. Do NOT dispatch sub-agents.
Your output goes directly to the Gitea review — keep it concise and technical.
"""


def _call_llm(user_prompt: str) -> str:
    """Run the review LLM call. Returns the raw text response."""
    if not LLM_URL:
        return "(LLM_ROUTER_URL not set — cannot run review)"

    try:
        import httpx
    except ImportError:
        return "(httpx not installed)"

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,  # deterministic-ish reviews
        "max_tokens": 1500,
    }
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        r = httpx.post(
            f"{LLM_URL.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=LLM_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"(LLM call failed: {exc})"


def _parse_verdict(llm_output: str) -> dict:
    """Extract verdict + confidence + rationale + feedback from the LLM response."""
    result = {
        "verdict": "request_changes",  # safe default
        "confidence": "low",
        "rationale": llm_output,
        "feedback": "",
    }
    m = re.search(r"VERDICT:\s*(merge|request_changes|reject)", llm_output, re.IGNORECASE)
    if m:
        result["verdict"] = m.group(1).lower()
    m = re.search(r"CONFIDENCE:\s*(high|medium|low)", llm_output, re.IGNORECASE)
    if m:
        result["confidence"] = m.group(1).lower()
    m = re.search(r"RATIONALE:\s*\n(.+?)(?:\n\s*FEEDBACK:|$)", llm_output, re.DOTALL)
    if m:
        result["rationale"] = m.group(1).strip()
    m = re.search(r"FEEDBACK:\s*\n(.+?)$", llm_output, re.DOTALL)
    if m:
        result["feedback"] = m.group(1).strip()
    return result


# ── Verdict execution ────────────────────────────────────────────────────


def _enforce_merge_policy(verdict: str, confidence: str) -> tuple[str, str]:
    """Safety gate — downgrade merge verdicts that don't meet the confidence bar.

    If the LLM says merge but confidence < GITEA_AUTO_MERGE_CONFIDENCE,
    downgrade to request_changes with a note.
    """
    order = {"low": 0, "medium": 1, "high": 2}
    if verdict != "merge":
        return verdict, ""

    required = order.get(AUTO_MERGE_CONFIDENCE, 2)
    actual = order.get(confidence, 0)
    if actual < required:
        return (
            "request_changes",
            (
                f"\n\n**Auto-merge policy:** the reviewer's confidence was "
                f"`{confidence}` but `GITEA_AUTO_MERGE_CONFIDENCE` requires "
                f"`{AUTO_MERGE_CONFIDENCE}`. Human review needed to merge."
            ),
        )
    return "merge", ""


def _format_review_body(verdict: dict, task: str, source_mem: Path | None, context: dict) -> str:
    """Markdown body for the Gitea review post."""
    parts = [
        f"## Automated review — verdict: **{verdict['verdict'].upper()}** (confidence: {verdict['confidence']})",
        "",
    ]
    if task:
        parts.extend(["### Original task", "", "```", task, "```", ""])
    parts.extend(["### Rationale", "", verdict["rationale"], ""])
    if verdict["feedback"]:
        parts.extend(["### Feedback", "", verdict["feedback"], ""])
    if source_mem:
        parts.append(f"Source task: [{source_mem.as_posix()}]({source_mem.as_posix()})")
    parts.append("")
    parts.append("*Reviewed by the project's orchestration bot. See `memory/pr_reviews/` for the audit trail.*")
    return "\n".join(parts)


def _write_pr_review_memory(
    pr_number: int,
    pr_url: str,
    verdict: dict,
    task: str,
    source_mem: Path | None,
    files: list[dict],
) -> Path | None:
    """Capture the review outcome to memory/pr_reviews/."""
    try:
        mem_dir = Path("memory/pr_reviews")
        mem_dir.mkdir(parents=True, exist_ok=True)
        existing = [int(m.group(1)) for p in mem_dir.glob("*.md")
                    if (m := re.match(r"^(\d{4})-", p.name))]
        mem_id = f"{(max(existing) + 1 if existing else 1):04d}"

        slug = re.sub(r"[^a-z0-9-]+", "-", (task or f"pr-{pr_number}").lower())[:40].strip("-") or "pr"
        filename = f"{mem_id}-{pr_number}-{slug}.md"
        path = mem_dir / filename

        project = os.environ.get("PROJECT_NAME", "unknown")
        shape = os.environ.get("PROJECT_SHAPE", "unknown")
        lang = os.environ.get("PROJECT_LANG", "unknown")

        outcome = {
            "merge": "success",
            "request_changes": "neutral",
            "reject": "failure",
        }.get(verdict["verdict"], "neutral")

        frontmatter = [
            "---",
            f"name: PR #{pr_number} review — {(task or 'untitled')[:60]}",
            f'id: "{mem_id}"',
            "type: pr_review",
            f"date: {time.strftime('%Y-%m-%d')}",
            f"project: {project}",
            f"shape: {shape}",
            f"lang: {lang}",
            f"tags: [pr-review, {verdict['verdict']}, {verdict['confidence']}]",
            f"confidence: {verdict['confidence']}",
            f"outcome: {outcome}",
            f"promote: {'pending' if verdict['confidence'] == 'high' else 'no'}",
            "author: bot",
            f"pr_number: {pr_number}",
            f"pr_url: {pr_url}",
        ]
        if source_mem:
            frontmatter.append(f"source_memory: {source_mem.as_posix()}")
        frontmatter.append("---")
        frontmatter.append("")

        body = [
            f"## Task",
            "",
            f"```",
            task or "(unknown — PR not opened by dispatch_agent)",
            "```",
            "",
            f"## Files changed ({len(files)})",
            "",
        ]
        for f in files[:20]:
            body.append(
                f"- `{f.get('filename', '?')}` "
                f"(+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            )
        if len(files) > 20:
            body.append(f"- …and {len(files) - 20} more")
        body.append("")
        body.append(f"## Verdict: {verdict['verdict']} ({verdict['confidence']})")
        body.append("")
        body.append("### Rationale")
        body.append("")
        body.append(verdict["rationale"])
        if verdict["feedback"]:
            body.append("")
            body.append("### Feedback")
            body.append("")
            body.append(verdict["feedback"])

        path.write_text("\n".join(frontmatter) + "\n".join(body) + "\n")
        return path
    except Exception as exc:
        return None


# ── Context formatting helpers ───────────────────────────────────────────


def _format_pipeline_summary(pipeline: dict) -> str:
    """Format the pipeline result as a human-readable block for the LLM."""
    if not pipeline:
        return "(pipeline status unknown — gitea module may not be configured)"
    status = pipeline.get("status", "unknown")
    elapsed = pipeline.get("elapsed_s", 0)
    if status == "success":
        return f"✓ PIPELINE PASSING (finished in {elapsed}s) — all jobs green."
    if status == "timeout":
        return (
            f"⌛ PIPELINE TIMEOUT after {elapsed}s — pipeline still running. "
            "Defer merge until it completes; if the LLM says merge anyway, "
            "downgrade to request_changes because we can't confirm green."
        )
    if status == "no_runs":
        return (
            "⚠ NO WORKFLOW RUNS for this PR's head SHA. Either .gitea/workflows/ci.yml "
            "is missing, the act_runner is not registered, or the runner is offline. "
            "Merging blind is unsafe — request changes and ask for CI to be set up."
        )
    if status == "error":
        return f"⚠ PIPELINE CHECK ERROR: {pipeline.get('error', '?')}"
    if status == "failure":
        failed_jobs = pipeline.get("failed_jobs") or []
        lines = [f"✗ PIPELINE FAILING — {len(failed_jobs)} failed job(s):"]
        for j in failed_jobs[:5]:
            lines.append(
                f"  - workflow `{j.get('workflow', '?')}` "
                f"job `{j.get('name', '?')}` "
                f"conclusion={j.get('conclusion', '?')}"
            )
        lines.append("")
        lines.append("**This PR MUST get request_changes. Never merge a failing pipeline.**")
        return "\n".join(lines)
    return f"(unknown pipeline status: {status})"


def _format_test_quality_summary(tq: dict) -> str:
    """Format the test_quality report for the LLM."""
    if not tq or "error" in tq:
        return f"(test quality analysis unavailable: {tq.get('error', '?') if tq else 'empty'})"
    score = tq.get("score", 0.0)
    lines = [
        f"Score: {score:.2f} / 1.00",
        f"Test files analyzed: {len(tq.get('files_analyzed', []))}",
        f"Source files changed: {len(tq.get('source_files', []))}",
        f"Missing tests for: {len(tq.get('missing_tests_for', []))} source file(s)",
        f"Total tests: {tq.get('total_tests', 0)}",
        f"Total assertions: {tq.get('total_assertions', 0)}",
        f"Total anti-patterns: {tq.get('total_anti_patterns', 0)}",
    ]
    findings = tq.get("findings") or []
    if findings:
        lines.append("")
        lines.append("Findings:")
        for f in findings[:10]:
            lines.append(f"  • {f}")
    if tq.get("missing_tests_for"):
        lines.append("")
        lines.append("Source files with NO corresponding test file:")
        for s in tq["missing_tests_for"][:10]:
            lines.append(f"  - {s}")
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────


def call(query: str, ctx: dict) -> str:
    parsed = _parse_query(query)
    pr_number = parsed.get("pr")
    if not pr_number:
        return "(review_pr: need a PR number — try '42' or 'pr=42; focus=security')"

    try:
        from tools import gitea
    except ImportError as exc:
        return f"(review_pr: gitea module missing: {exc})"

    # 1. Fetch the PR + files + diff
    try:
        pr = gitea.get_pr(pr_number)
        files = gitea.get_pr_files(pr_number)
        diff = gitea.get_pr_diff(pr_number)
    except Exception as exc:
        return f"(review_pr: failed to fetch PR #{pr_number}: {exc})"

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + f"\n\n... (diff truncated at {MAX_DIFF_CHARS} chars)"

    head_branch = (pr.get("head") or {}).get("ref", "")
    task, source_mem = _find_source_memory(head_branch)
    pr_body = pr.get("body") or ""

    # 2. Gather context from other tools (pipeline status + test quality)
    context = _gather_context(pr_body, task, files, pr_number)

    # 3. Format pipeline and test_quality sections for the LLM
    pipeline = context.get("pipeline") or {}
    pipeline_summary = _format_pipeline_summary(pipeline)
    tq = context.get("test_quality") or {}
    tq_summary = _format_test_quality_summary(tq)

    # 4. Run the LLM review
    user_prompt = f"""Review this pull request.

PR #{pr_number}: {pr.get('title')}
Author: {(pr.get('user') or {}).get('login', '?')}
Branch: {head_branch} → {(pr.get('base') or {}).get('ref', '?')}

## Original task
{task or '(unknown — PR was not opened by dispatch_agent)'}

## PR body
{pr_body[:2000]}

## Pipeline status (binding — red pipeline = request_changes)
{pipeline_summary}

## Test quality report (score below 0.8 = request_changes)
{tq_summary}

## Files changed ({len(files)})
{chr(10).join(f"- {f.get('filename', '?')} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})" for f in files[:30])}

## Project-local memory relevant to this change
{context.get('memory_local', '')[:3000]}

## Cross-project memory (if available)
{context.get('memory_longterm', '')[:2000]}

## Diff
```diff
{diff}
```

Now review. Output only VERDICT/CONFIDENCE/RATIONALE/FEEDBACK per the format.
"""

    llm_output = _call_llm(user_prompt)
    if llm_output.startswith("("):  # error
        return f"(review_pr: {llm_output})"

    verdict = _parse_verdict(llm_output)

    # 5. Enforce pipeline gate — red pipeline always forces request_changes
    if pipeline.get("status") == "failure":
        verdict["verdict"] = "request_changes"
        verdict["confidence"] = "high"
        verdict["rationale"] = (
            "Pipeline is FAILING — merge is blocked regardless of the LLM's verdict.\n\n"
            + verdict.get("rationale", "")
        )
        verdict["feedback"] = (
            "The CI pipeline failed. Fix the failing jobs before requesting review again.\n\n"
            + verdict.get("feedback", "")
        )

    # 6. Enforce test quality gate — score < 0.8 forces request_changes
    tq_score = tq.get("score")
    if tq_score is not None and tq_score < 0.8 and verdict["verdict"] == "merge":
        verdict["verdict"] = "request_changes"
        verdict["rationale"] += (
            f"\n\n**Test quality gate:** test_quality score is {tq_score:.2f} "
            f"(< 0.8 required for merge). Anti-patterns or missing tests detected — "
            f"merge blocked."
        )

    # 7. Enforce merge-policy safety gate (confidence threshold)
    final_verdict, policy_note = _enforce_merge_policy(verdict["verdict"], verdict["confidence"])
    if policy_note:
        verdict["rationale"] += policy_note
    verdict["verdict"] = final_verdict

    # 5. Format review body and post to Gitea
    review_body = _format_review_body(verdict, task, source_mem, context)

    try:
        if verdict["verdict"] == "merge":
            # Approve review first, then merge
            gitea.post_review(pr_number, review_body, event="APPROVED")
            gitea.merge_pr(pr_number, method="squash", title=pr.get("title"), message=verdict["rationale"][:1000])
            # Best-effort branch cleanup
            try:
                gitea.delete_branch(head_branch)
            except Exception:
                pass
            action_taken = "merged (squash)"
        elif verdict["verdict"] == "request_changes":
            gitea.post_review(pr_number, review_body, event="REQUEST_CHANGES")
            action_taken = "requested changes"
        else:  # reject
            gitea.post_review(pr_number, review_body, event="COMMENT")
            gitea.close_pr(pr_number)
            action_taken = "closed as rejected"
    except Exception as exc:
        return f"(review_pr: failed to execute verdict {verdict['verdict']}: {exc})"

    # 6. Capture to memory
    memory_path = _write_pr_review_memory(pr_number, gitea.pr_url(pr_number), verdict, task, source_mem, files)

    summary = (
        f"PR #{pr_number} review: **{verdict['verdict']}** "
        f"(confidence={verdict['confidence']}) → {action_taken} · "
        f"{gitea.pr_url(pr_number)}"
    )
    if memory_path:
        summary += f" · memory: {memory_path}"
    return summary
