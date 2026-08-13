#!/usr/bin/env bash
# runners/cursor.sh — dispatch a task to Cursor IDE's background agent.
#
# Env vars set by bot/tools/dispatch_agent.py:
#     TASK     — the task description
#     BRANCH   — the throwaway branch the agent should work on
#     PROJECT  — this project's slug
#
# Operator configures AGENT_COMMAND to point at this script:
#     AGENT_DISPATCHER=cursor
#     AGENT_COMMAND=./bot/runners/cursor.sh
#
# Exact Cursor CLI invocation depends on which Cursor version you're on
# and whether you're using Cursor Background Agents or the local CLI.
# Adapt the `cursor-agent` command below to your installation.

set -euo pipefail

: "${TASK:?TASK env var required}"
: "${BRANCH:?BRANCH env var required}"

echo "[cursor-runner] dispatching task to Cursor on branch $BRANCH"
echo "[cursor-runner] task: $TASK"

# Read the pre-flight memory brief if present — the orchestration bot
# compiles this before dispatch with relevant past lessons.
BRIEF="memory/_relevant-for-${BRANCH//\//_}.md"
if [ -f "$BRIEF" ]; then
    echo "[cursor-runner] memory brief: $BRIEF"
    # Pass the brief as additional context to the agent via env var or
    # file reference — depends on your Cursor CLI version.
    export AGENT_MEMORY_BRIEF_PATH="$BRIEF"
fi

# Example invocations — pick the one that matches your Cursor setup:
#
# Cursor Background Agents (cloud):
#     cursor agent create --task "$TASK" --branch "$BRANCH"
#
# Cursor local CLI (if exposed):
#     cursor-agent run --task "$TASK" --workspace .
#
# Generic fallback via the Cursor CLI binary:

if ! command -v cursor-agent >/dev/null 2>&1; then
    echo "[cursor-runner] cursor-agent binary not found on PATH" >&2
    echo "[cursor-runner] install from https://cursor.sh or adjust this runner" >&2
    exit 127
fi

cursor-agent run \
    --task "$TASK" \
    --workspace "$(pwd)" \
    --branch "$BRANCH" \
    --non-interactive

# ── Mandatory test gate (AGENTS.md §24.5) ────────────────────────────────
# Run the project's test suite before declaring success. If tests fail,
# the dispatch is marked failed, no PR is opened, and the bot will see the
# failure in logs. This stops broken code from reaching Gitea at all.
echo "[cursor-runner] running make test to verify changes..."
if command -v make >/dev/null 2>&1 && grep -q '^test:' Makefile 2>/dev/null; then
    if ! make test; then
        echo "[cursor-runner] ❌ tests failed — dispatch will be marked failed"
        exit 1
    fi
    echo "[cursor-runner] ✓ tests passed"
else
    echo "[cursor-runner] (no make test target — skipping local test gate)"
fi

echo "[cursor-runner] done"
