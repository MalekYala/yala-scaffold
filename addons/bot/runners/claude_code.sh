#!/usr/bin/env bash
# runners/claude_code.sh — dispatch a task to Claude Code CLI.
#
# Env vars set by bot/tools/dispatch_agent.py:
#     TASK     — the task description
#     BRANCH   — the throwaway branch the agent should work on
#     PROJECT  — this project's slug
#
# Operator configures AGENT_COMMAND to point at this script:
#     AGENT_DISPATCHER=claude-code
#     AGENT_COMMAND=./bot/runners/claude_code.sh
#
# This runs claude in headless mode, which reads the task and operates on
# the current working directory (already on $BRANCH when the runner starts).

set -euo pipefail

: "${TASK:?TASK env var required}"
: "${BRANCH:?BRANCH env var required}"

echo "[claude-runner] dispatching task to Claude Code on branch $BRANCH"
echo "[claude-runner] task: $TASK"

# Read the pre-flight memory brief if present — prepend it to the task
# so Claude reads past lessons before planning.
BRIEF="memory/_relevant-for-${BRANCH//\//_}.md"
if [ -f "$BRIEF" ]; then
    echo "[claude-runner] memory brief: $BRIEF"
    TASK="Read the following memory brief first, then complete the task below.

Memory brief (from $BRIEF):

$(cat "$BRIEF")

---

Task:

$TASK"
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "[claude-runner] claude CLI not found on PATH" >&2
    echo "[claude-runner] install from https://claude.com/code or adjust this runner" >&2
    exit 127
fi

# Headless / print mode: feed the task via stdin or --print depending on
# your Claude Code version. Adjust as needed.
claude --print "$TASK" 2>&1 || {
    # Fallback to interactive stdin
    echo "$TASK" | claude
}

# ── Mandatory test gate (AGENTS.md §24.5) ────────────────────────────────
echo "[claude-runner] running make test to verify changes..."
if command -v make >/dev/null 2>&1 && grep -q '^test:' Makefile 2>/dev/null; then
    if ! make test; then
        echo "[claude-runner] ❌ tests failed — dispatch will be marked failed"
        exit 1
    fi
    echo "[claude-runner] ✓ tests passed"
else
    echo "[claude-runner] (no make test target — skipping local test gate)"
fi

echo "[claude-runner] done"
