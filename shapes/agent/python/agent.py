"""Entry point for <name> (shape: agent).

Runs the graph against a real model. Everything structural is checked offline
by `qa_check.py` with a scripted model; this is where you actually talk to one.

    python3 agent.py "what is 12 plus 30?"
    python3 agent.py --trace "look up the answer"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from langchain_core.messages import HumanMessage, SystemMessage

import config
from graph import SYSTEM_PROMPT, build_graph
from models import real_model

settings = config.load()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("<name>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent")
    parser.add_argument("prompt", nargs="*", help="what to ask")
    parser.add_argument("--trace", action="store_true", help="print every step, not just the answer")
    parser.add_argument("--recursion-limit", type=int, default=int(settings.recursion_limit))
    args = parser.parse_args()

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("usage: agent.py <prompt>", file=sys.stderr)
        return 2

    try:
        model = real_model(settings)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    app = build_graph(model)
    _t = time.monotonic()
    result = app.invoke(
        {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]},
        {"recursion_limit": args.recursion_limit},
    )
    elapsed = int((time.monotonic() - _t) * 1000)

    messages = result["messages"]
    tool_calls = [call["name"] for message in messages for call in (getattr(message, "tool_calls", None) or [])]

    if args.trace:
        for message in messages:
            kind = type(message).__name__.replace("Message", "")
            calls = getattr(message, "tool_calls", None) or []
            suffix = f"  -> {[c['name'] for c in calls]}" if calls else ""
            print(f"[{kind}] {(message.content or '')[:200]}{suffix}", file=sys.stderr)

    log.info(f"[<name>-perf] phase=agent_run duration_ms={elapsed} steps={len(messages)} tool_calls={len(tool_calls)}")
    print(messages[-1].content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
