#!/usr/bin/env python3
"""Summarise and gate an OpenCodeReview result for <name>.

Reads the JSON that `ocr review --format json` writes, prints it as something
a human can read in a CI log, and exits non-zero when a finding is at or above
a severity threshold.

Why this exists rather than just reading the raw JSON: an AI reviewer produces
a lot of low-severity opinion, and a job that fails on all of it gets disabled
within a week. Gating on `critical` by default means red always means
something, and everything else is still there to read.

Usage:
    python3 review/gate.py .ocr/result.json
    python3 review/gate.py .ocr/result.json --fail-on high
    python3 review/gate.py .ocr/result.json --fail-on none      # report only
    python3 review/gate.py .ocr/result.json --format markdown   # for a comment

Exit codes:
    0  no finding at or above the threshold
    1  at least one finding at or above the threshold
    2  the result file is missing or unparseable

Stdlib only: this runs in whatever image the review job uses, and should never
need an install step of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# OpenCodeReview emits critical / high / medium / low. Older builds and some
# models also produce blocker / major / minor / info, so they are mapped here
# rather than silently sorting as unknown — an unrecognised severity that
# ranks last is exactly how a critical finding slips through a gate.
SEVERITY_RANK = {
    "critical": 4,
    "blocker": 4,
    "high": 3,
    "major": 3,
    "medium": 2,
    "normal": 2,
    "low": 1,
    "minor": 1,
    "info": 0,
    "trivial": 0,
}

ORDER = ["critical", "high", "medium", "low", "info"]


def rank(severity: str | None) -> int:
    """Rank a severity string. Unknown values rank as high, deliberately.

    Treating an unrecognised severity as low would let a new severity name
    introduced upstream quietly bypass the gate. Ranking it high makes the
    surprise loud instead.
    """
    if not severity:
        return 2
    return SEVERITY_RANK.get(severity.strip().lower(), 3)


def load(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: no review result at {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: {path} is not valid JSON ({exc}).\n"
            f"       `ocr review` most likely failed — check its stderr log.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    if isinstance(data, list):
        comments = data
    elif isinstance(data, dict):
        comments = data.get("comments") or []
    else:
        print(f"ERROR: unexpected JSON shape in {path}", file=sys.stderr)
        raise SystemExit(2)

    return [c for c in comments if isinstance(c, dict)]


def location(comment: dict) -> str:
    path = comment.get("path") or "(no file)"
    start = comment.get("start_line") or 0
    end = comment.get("end_line") or start
    if not start:
        return path
    return f"{path}:{start}" if start == end else f"{path}:{start}-{end}"


def render_text(comments: list[dict]) -> str:
    lines: list[str] = []
    for severity in ORDER:
        bucket = [c for c in comments if (c.get("severity") or "").lower() == severity]
        if not bucket:
            continue
        lines.append(f"\n── {severity.upper()} ({len(bucket)}) " + "─" * (50 - len(severity)))
        for comment in bucket:
            category = comment.get("category") or "other"
            lines.append(f"  {location(comment)}  [{category}]")
            for text_line in (comment.get("content") or "").strip().splitlines():
                lines.append(f"      {text_line}")
            suggestion = (comment.get("suggestion_code") or "").strip()
            if suggestion:
                lines.append("      suggested:")
                for text_line in suggestion.splitlines():
                    lines.append(f"        {text_line}")
    # Anything whose severity did not match a known bucket still has to be
    # shown, or the summary silently loses findings.
    shown = {id(c) for severity in ORDER for c in comments if (c.get("severity") or "").lower() == severity}
    rest = [c for c in comments if id(c) not in shown]
    if rest:
        lines.append(f"\n── UNCLASSIFIED ({len(rest)}) " + "─" * 38)
        for comment in rest:
            lines.append(f"  {location(comment)}  severity={comment.get('severity')!r}")
            for text_line in (comment.get("content") or "").strip().splitlines():
                lines.append(f"      {text_line}")
    return "\n".join(lines)


def render_markdown(comments: list[dict]) -> str:
    if not comments:
        return "_No review findings._"
    lines = ["| Severity | Location | Category | Finding |", "|---|---|---|---|"]
    for comment in sorted(comments, key=lambda c: -rank(c.get("severity"))):
        content = " ".join((comment.get("content") or "").split())
        if len(content) > 160:
            content = content[:157] + "…"
        lines.append(
            f"| {comment.get('severity') or '?'} | `{location(comment)}` | "
            f"{comment.get('category') or 'other'} | {content} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarise and gate an OpenCodeReview result")
    parser.add_argument("result", type=Path, help="path to `ocr review --format json` output")
    parser.add_argument(
        "--fail-on",
        default="critical",
        help="lowest severity that fails the job: critical|high|medium|low|none (default: critical)",
    )
    parser.add_argument("--format", choices=["text", "markdown"], default="text")
    args = parser.parse_args()

    comments = load(args.result)

    if not comments:
        print("no review findings")
        return 0

    counts = {severity: 0 for severity in ORDER}
    for comment in comments:
        key = (comment.get("severity") or "").lower()
        counts[key] = counts.get(key, 0) + 1

    if args.format == "markdown":
        print(render_markdown(comments))
    else:
        print(render_text(comments))

    summary = ", ".join(f"{severity}={counts.get(severity, 0)}" for severity in ORDER)
    print(f"\n{len(comments)} finding(s): {summary}")
    print(f"[<name>-perf] phase=code_review_gate findings={len(comments)} threshold={args.fail_on}")

    # stderr is unbuffered and stdout is not, so without this the failure
    # block below appears *above* the report it refers to in a CI log.
    sys.stdout.flush()

    if args.fail_on.lower() in {"none", "off", ""}:
        return 0

    threshold = rank(args.fail_on)
    blocking = [c for c in comments if rank(c.get("severity")) >= threshold]
    if blocking:
        print(
            f"\nFAIL: {len(blocking)} finding(s) at or above '{args.fail_on}'.",
            file=sys.stderr,
        )
        for comment in blocking:
            print(f"  {comment.get('severity')}: {location(comment)}", file=sys.stderr)
        return 1

    print(f"no findings at or above '{args.fail_on}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
