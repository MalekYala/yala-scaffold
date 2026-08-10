#!/usr/bin/env bash
# runners/custom.sh — template for rolling your own agent runner.
#
# Copy this file, edit to call whatever coding agent or LLM you want, and
# set AGENT_COMMAND=./bot/runners/my_runner.sh in .env.
#
# Env vars your runner will receive:
#     TASK     — natural-language task description from the IRC bot
#     BRANCH   — throwaway git branch name (already checked out)
#     PROJECT  — this project's slug
#
# Contract:
#     - Operate on the current working directory (the project root)
#     - Make whatever changes the task requires
#     - Commit your changes (git add + git commit) if you want them reviewable
#     - Exit 0 on success, non-zero on failure
#     - Write progress/logs to stdout — dispatch_agent.py captures them to
#       logs/agent-<branch>.log for later review
#
# The dispatcher caps concurrency at $AGENT_MAX_CONCURRENT and kills the
# runner after $AGENT_TIMEOUT_S seconds.

set -euo pipefail

: "${TASK:?TASK env var required}"
: "${BRANCH:?BRANCH env var required}"

echo "[custom-runner] task: $TASK"
echo "[custom-runner] branch: $BRANCH"
echo "[custom-runner] cwd: $(pwd)"
echo "[custom-runner] project: ${PROJECT:-unknown}"

# The orchestration bot writes a memory brief before dispatching. Read it
# here and feed it to your agent so past lessons inform the current run.
BRIEF="memory/_relevant-for-${BRANCH//\//_}.md"
if [ -f "$BRIEF" ]; then
    echo "[custom-runner] memory brief available at $BRIEF"
    # Your agent should read this file. Example (prepend to the task):
    #   TASK="$(cat "$BRIEF")\n\n---\n\n$TASK"
fi

# ── Put your agent invocation here ────────────────────────────────────────
#
# Examples:
#
# 1. A local Python script that wraps an LLM:
#     python3 bin/my_agent.py --task "$TASK"
#
# 2. curl an HTTP endpoint that runs an agent remotely:
#     curl -X POST "$AGENT_SERVICE_URL/run" \
#          -H 'Content-Type: application/json' \
#          -d "{\"task\": \"$TASK\", \"cwd\": \"$(pwd)\"}"
#
# 3. A full-custom implementation: read files, call an LLM, write patches
#    with `patch` or `git apply`, run tests, commit.
#
# The echo below is a placeholder — replace it with your real invocation.

echo "[custom-runner] TODO: implement the actual agent invocation in runners/custom.sh"
echo "[custom-runner] no changes made"

# Auto-commit the working tree if the agent made any changes (optional)
if ! git diff --quiet HEAD 2>/dev/null; then
    git add -A
    git commit -m "bot: $TASK"
    echo "[custom-runner] committed changes on $BRANCH"
fi

# ── Mandatory test gate (AGENTS.md §24.5) ────────────────────────────────
# Every runner MUST run the project's tests before finishing. If tests
# fail, exit non-zero so dispatch_agent marks this dispatch failed and
# doesn't open a PR. This prevents broken code from ever reaching Gitea.
echo "[custom-runner] running make test to verify changes..."
if command -v make >/dev/null 2>&1 && grep -q '^test:' Makefile 2>/dev/null; then
    if ! make test; then
        echo "[custom-runner] ❌ tests failed — dispatch will be marked failed"
        exit 1
    fi
    echo "[custom-runner] ✓ tests passed"
else
    echo "[custom-runner] (no make test target — skipping local test gate)"
fi
