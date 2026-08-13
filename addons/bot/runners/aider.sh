#!/usr/bin/env bash
# runners/aider.sh — dispatch a task to Aider (https://aider.chat).
#
# Env vars set by bot/tools/dispatch_agent.py:
#     TASK     — the task description
#     BRANCH   — the throwaway branch the agent should work on
#     PROJECT  — this project's slug
#
# Operator configures AGENT_COMMAND to point at this script:
#     AGENT_DISPATCHER=aider
#     AGENT_COMMAND=./bot/runners/aider.sh
#
# Aider needs an LLM provider — set OPENAI_API_KEY or ANTHROPIC_API_KEY,
# or point at an OpenAI-compatible local endpoint via --openai-api-base.

set -euo pipefail

: "${TASK:?TASK env var required}"
: "${BRANCH:?BRANCH env var required}"

echo "[aider-runner] dispatching task to Aider on branch $BRANCH"
echo "[aider-runner] task: $TASK"

# Include the memory brief in the task prompt if present
BRIEF="memory/_relevant-for-${BRANCH//\//_}.md"
if [ -f "$BRIEF" ]; then
    echo "[aider-runner] memory brief: $BRIEF"
    TASK="Read the memory brief at $BRIEF first (past lessons relevant to this task). Then: $TASK"
fi

if ! command -v aider >/dev/null 2>&1; then
    echo "[aider-runner] aider not found on PATH" >&2
    echo "[aider-runner] install with: pip install aider-chat" >&2
    exit 127
fi

# Run aider with the task as a one-shot message. --yes auto-accepts edits;
# remove it if you want the operator to review each diff interactively
# (won't work in non-interactive dispatch, but useful for debugging).
aider \
    --yes \
    --no-auto-commits \
    --message "$TASK" \
    ${AIDER_EXTRA_ARGS:-}

# Aider leaves you in an interactive session by default — the --message
# flag runs a single task and exits. If your aider version behaves
# differently, adjust the flags above.

# ── Mandatory test gate (AGENTS.md §24.5) ────────────────────────────────
echo "[aider-runner] running make test to verify changes..."
if command -v make >/dev/null 2>&1 && grep -q '^test:' Makefile 2>/dev/null; then
    if ! make test; then
        echo "[aider-runner] ❌ tests failed — dispatch will be marked failed"
        exit 1
    fi
    echo "[aider-runner] ✓ tests passed"
else
    echo "[aider-runner] (no make test target — skipping local test gate)"
fi

echo "[aider-runner] done"
