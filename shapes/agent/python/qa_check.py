#!/usr/bin/env python3
"""End-to-end check for <name> (shape: agent).

Runs entirely offline against a scripted model. No API key, no network, no
cost — which is the only way a check like this actually gets run on every
commit.

Checks:

  1. graph_compiles    — the StateGraph compiles
  2. graph_reachable   — every node is reachable from START
  3. graph_terminates  — every node has a path to END
  4. tools_documented  — every tool has a description and an args schema
  5. tools_unique      — no two tools share a name
  6. tools_bound       — the graph actually binds the tools it declares
  7. scenarios         — each committed scenario replays to its expected outcome
  8. no_phantom_tools  — no scenario expects a tool the agent does not have
  9. recursion_guarded — a model that always asks for a tool is stopped

**For an agent, "it ran without erroring" is the vacuous success.** An agent
that runs, calls no tools, and returns a confident wrong answer looks perfectly
healthy to a process monitor and to an HTTP check. So a scenario that declares
expected tool calls and produces none is a failure here, in the same family as
zero discovered routes, zero exposed tools, and zero extracted records
elsewhere in this kit.

Check 3 is worth dwelling on. A tool-calling loop only reaches END when the
model stops asking for tools — which is a property of the model, not the
graph. If the recursion limit does not fire, a bad model turns into an
unbounded bill and a hung process. Check 9 proves the backstop works by
scripting a model that never stops.

Usage:
    python3 qa_check.py
    python3 qa_check.py --scenarios eval/scenarios.json

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import graph as agent_graph  # noqa: E402
from models import scripted  # noqa: E402


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("scenarios", []))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} is not valid JSON: {exc}") from None


def to_ai_message(turn: dict[str, Any]) -> AIMessage:
    """Build one scripted assistant turn from its JSON declaration."""
    calls = turn.get("tool_calls") or []
    return AIMessage(
        content=turn.get("content", ""),
        tool_calls=[{"name": c["name"], "args": c.get("args", {}), "id": c.get("id", f"call_{i}")} for i, c in enumerate(calls)],
    )


def run(scenarios_path: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # 1. graph_compiles
    try:
        model = scripted(AIMessage(content="ok"))
        compiled = agent_graph.build_graph(model)
        checks.append({"name": "graph_compiles", "ok": True, "detail": "StateGraph compiled"})
    except Exception as exc:
        checks.append({"name": "graph_compiles", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
        return {"status": "fail", "checks": checks}

    drawn = compiled.get_graph()
    nodes = {name for name in drawn.nodes if not name.startswith("__")}
    edges = [(e.source, e.target) for e in drawn.edges]

    # 2. graph_reachable — an unreachable node is dead code that reads as a feature.
    reachable: set[str] = set()
    frontier = [t for s, t in edges if s == "__start__"]
    while frontier:
        node = frontier.pop()
        if node in reachable:
            continue
        reachable.add(node)
        frontier.extend(t for s, t in edges if s == node)
    orphans = sorted(nodes - reachable)
    checks.append(
        {
            "name": "graph_reachable",
            "ok": not orphans,
            "detail": f"{len(nodes)} node(s) all reachable from START" if not orphans else f"unreachable from START: {orphans} — dead code that looks like a feature",
        }
    )

    # 3. graph_terminates — a node with no path to END is a hang waiting to happen.
    can_end: set[str] = set()
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            if source in can_end:
                continue
            if target == "__end__" or target in can_end:
                can_end.add(source)
                changed = True
    stuck = sorted(nodes - can_end)
    checks.append(
        {
            "name": "graph_terminates",
            "ok": not stuck,
            "detail": "every node has a path to END" if not stuck else f"no path to END from: {stuck} — anything reaching these hangs",
        }
    )

    # 4/5. Tools. The description is the prompt the model reads, so an
    # undocumented tool is one it cannot use correctly.
    undocumented = [t.name for t in agent_graph.TOOLS if not (t.description or "").strip()]
    no_schema = [t.name for t in agent_graph.TOOLS if not getattr(t, "args_schema", None)]
    checks.append(
        {
            "name": "tools_documented",
            "ok": not undocumented and not no_schema,
            "detail": f"{len(agent_graph.TOOLS)} tool(s) documented"
            if not undocumented and not no_schema
            else f"no description: {undocumented}; no args schema: {no_schema} — the description IS the prompt the model reads",
        }
    )

    names = [t.name for t in agent_graph.TOOLS]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    checks.append(
        {
            "name": "tools_unique",
            "ok": not duplicates,
            "detail": "tool names unique" if not duplicates else f"duplicated: {duplicates}",
        }
    )

    # 6. tools_bound — declaring tools the graph never binds is a silent no-op.
    probe = scripted(AIMessage(content="done"))
    agent_graph.build_graph(probe)
    bound = {t.name for t in probe.bound_tools}
    missing = sorted(set(names) - bound)
    checks.append(
        {
            "name": "tools_bound",
            "ok": not missing,
            "detail": f"graph binds all {len(bound)} declared tool(s)" if not missing else f"declared but never bound to the model: {missing}",
        }
    )

    # 7/8. Scenarios.
    try:
        scenarios = load_scenarios(scenarios_path)
    except RuntimeError as exc:
        checks.append({"name": "scenarios", "ok": False, "detail": str(exc)})
        return {"status": "fail", "checks": checks}

    if not scenarios:
        # No scenarios means nothing about behaviour was verified. Reporting
        # success here would be exactly the vacuous pass this kit refuses.
        checks.append(
            {
                "name": "scenarios",
                "ok": False,
                "detail": f"no scenarios in {scenarios_path.name} — nothing about the agent's behaviour is being checked",
            }
        )
    else:
        failures: list[str] = []
        phantom: list[str] = []
        available = agent_graph.tool_names()

        for scenario in scenarios:
            name = scenario.get("name", "unnamed")
            for turn in scenario.get("turns", []):
                for call in turn.get("tool_calls") or []:
                    if call["name"] not in available:
                        phantom.append(f"{name}: {call['name']}")

            try:
                model = scripted(*[to_ai_message(t) for t in scenario.get("turns", [])])
                compiled = agent_graph.build_graph(model)
                result = compiled.invoke(
                    {"messages": [HumanMessage(content=scenario["input"])]},
                    {"recursion_limit": scenario.get("recursion_limit", 25)},
                )
            except Exception as exc:
                failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
                continue

            messages = result["messages"]
            actual_calls = [call["name"] for message in messages for call in (getattr(message, "tool_calls", None) or [])]
            expected_calls = scenario.get("expect_tool_calls", [])

            if actual_calls != expected_calls:
                failures.append(f"{name}: tool calls {actual_calls} != expected {expected_calls}")

            expected_text = scenario.get("expect_final_contains")
            final = (messages[-1].content or "") if messages else ""
            if expected_text and expected_text.lower() not in final.lower():
                failures.append(f"{name}: final answer {final[:60]!r} lacks {expected_text!r}")

        checks.append(
            {
                "name": "scenarios",
                "ok": not failures,
                "detail": f"{len(scenarios)} scenario(s) replayed as expected" if not failures else "; ".join(failures[:4]),
            }
        )
        checks.append(
            {
                "name": "no_phantom_tools",
                "ok": not phantom,
                "detail": "every scenario calls a real tool" if not phantom else f"scenarios reference tools that do not exist: {phantom}",
            }
        )

    # 9. recursion_guarded — prove the backstop fires rather than trusting it.
    looping = scripted(
        *[
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 1, "b": 1}, "id": f"loop_{i}"}],
            )
            for i in range(50)
        ]
    )
    try:
        agent_graph.build_graph(looping).invoke(
            {"messages": [HumanMessage(content="loop forever")]},
            {"recursion_limit": 6},
        )
        guarded = False
        detail = "a model that never stops asking for tools ran to completion — the recursion limit did not fire, so a bad model means an unbounded bill"
    except Exception as exc:  # any stop is a pass; hanging is the failure
        guarded = True
        detail = f"loop stopped by {type(exc).__name__}"
    checks.append({"name": "recursion_guarded", "ok": guarded, "detail": detail})

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the agent graph offline")
    parser.add_argument("--scenarios", type=Path, default=PROJECT_ROOT / "eval" / "scenarios.json")
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.scenarios)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
