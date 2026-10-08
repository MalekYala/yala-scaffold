#!/usr/bin/env python3
"""Reject commits that carry AI attribution notes.

Checks every commit in history (or a REV range):
  - author and committer: no AI tool or bot identity
  - message: no AI co-author/assisted-by trailers, no "generated with <tool>"
    style notes, no robot emoji, no tool default prefixes such as "aider: "
  - added lines: the same attribution notes, so they can't hide in a file

Tool *names* on their own are fine. The kit supports coding agents (see
addons/bot/runners/), so "claude_code.sh" or "set CLAUDE_MODEL" must pass;
only attribution phrasing is rejected.

Usage: tests/check_ai_notes.py [REV_RANGE]   (default: all of HEAD's history)
Exit 1 on any finding. Paths listed in .ai-notes-allow (one glob per line)
are skipped by the added-lines check.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOOLS = (
    r"claude|anthropic|chatgpt|openai|gpt-?[345]\w*|copilot|cursor ?agent|aider|codex|gemini|"
    r"devin|windsurf|codeium|tabnine|codewhisperer|amazon q|llm|large language model|ai assistant|ai model"
)
T = rf"(?:{TOOLS})"

MESSAGE_RULES = [
    ("AI co-author trailer", re.compile(rf"^\s*(co-authored-by|assisted-by|generated-by|helped-by)\s*:.*\b{T}\b", re.I | re.M)),
    ("generated-with note", re.compile(rf"\b(generated|written|created|authored|produced|drafted)\s+(with|by|using|via)\s+(the\s+help\s+of\s+)?\[?{T}\b", re.I)),
    ("assisted-by note", re.compile(rf"\b(with\s+(the\s+)?help\s+(of|from)|assisted\s+by|courtesy\s+of)\s+\[?{T}\b", re.I)),
    ("AI self-reference", re.compile(r"\bas an ai\b|\bas a (large )?language model\b|\bi'?m an ai\b", re.I)),
    ("robot emoji", re.compile("\U0001F916")),
    ("AI vendor address", re.compile(r"noreply@anthropic\.com|@openai\.com|cursoragent@cursor\.com|\+copilot@users\.noreply\.github\.com", re.I)),
    ("aider default prefix", re.compile(r"\Aaider:\s", re.I)),
]
# Added lines get the same checks minus the message-only prefix rule.
CONTENT_RULES = [r for r in MESSAGE_RULES if r[0] != "aider default prefix"]
IDENTITY = re.compile(rf"\b{T}\b|noreply@anthropic\.com|cursoragent@|\+copilot@", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def allowed_paths() -> list[str]:
    f = ROOT / ".ai-notes-allow"
    if not f.is_file():
        return []
    return [ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def check_commits(rev: str) -> list[str]:
    findings: list[str] = []
    sep, end = "\x1f", "\x1e"
    log = git("log", f"--format=%H{sep}%an{sep}%ae{sep}%cn{sep}%ce{sep}%B{end}", rev)
    for record in filter(None, (r.strip("\n") for r in log.split(end))):
        sha, an, ae, cn, ce, body = record.split(sep, 5)
        short = sha[:7]
        for who, value in (("author", f"{an} <{ae}>"), ("committer", f"{cn} <{ce}>")):
            if IDENTITY.search(value):
                findings.append(f"{short}: {who} looks like an AI tool: {value}")
        for label, rx in MESSAGE_RULES:
            m = rx.search(body)
            if m:
                line = body[: m.start()].count("\n") + 1
                findings.append(f"{short}: message line {line}: {label}: {m.group(0).strip()!r}")
    return findings


def check_added_lines(rev: str) -> list[str]:
    findings: list[str] = []
    allow = allowed_paths()
    patch = git("log", "-p", "--no-color", "--format=commit %h", "--unified=0", rev)
    commit = path = ""
    for line in patch.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and not line.startswith("+++") and path:
            if any(fnmatch.fnmatch(path, g) for g in allow):
                continue
            for label, rx in CONTENT_RULES:
                m = rx.search(line[1:])
                if m:
                    findings.append(f"{commit}: {path}: {label}: {m.group(0).strip()!r}")
    return findings


def main(argv: list[str]) -> int:
    rev = argv[0] if argv else "HEAD"
    count = len(git("rev-list", rev).split())
    findings = check_commits(rev) + check_added_lines(rev)
    for f in findings:
        print(f, file=sys.stderr)
    print(f"check_ai_notes: {count} commits, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
