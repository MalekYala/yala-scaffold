#!/usr/bin/env python3
"""Evaluate <name> against a real model, and gate on committed thresholds.

`qa_check.py` proves the graph is correct using a scripted model: routing,
tool wiring, termination. It cannot tell you whether a real model *chooses*
the right tool, because it never asks one. This does — and costs tokens, so it
is opt-in rather than part of every commit.

Scores three things, from `eval/cases.json`:

  pass_rate       cases meeting every expectation
  tool_precision  expected tool calls / actual tool calls
  avg_steps       mean graph steps per case

`tool_precision` is the one people leave out and then regret. An agent that
reaches the right answer by calling four tools where one would do is slower,
more expensive, and closer to the edge on the next input — but it scores a
perfect pass rate.

Usage:
    python3 evaluate.py
    python3 evaluate.py --cases eval/cases.json --out eval/reports/latest.json

Exit codes:
    0  ran and met every threshold
    1  a threshold was missed
    2  could not run (no model configured, no cases)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from graph import SYSTEM_PROMPT, build_graph  # noqa: E402
from models import real_model  # noqa: E402

settings = config.load()


def resolve(report: dict[str, Any], dotted: str) -> Any:
    node = report
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the agent against a real model")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "eval" / "cases.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "eval" / "reports" / "latest.json")
    parser.add_argument("--thresholds", type=Path, default=PROJECT_ROOT / "eval" / "thresholds.json")
    args = parser.parse_args()

    if not args.cases.is_file():
        print(f"ERROR: no cases at {args.cases}", file=sys.stderr)
        return 2
    cases = json.loads(args.cases.read_text(encoding="utf-8")).get("cases", [])
    if not cases:
        # An evaluation that measures nothing must not report success.
        print(f"ERROR: {args.cases.name} declares no cases", file=sys.stderr)
        return 2

    try:
        model = real_model(settings)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    app = build_graph(model)
    results = []
    _t_all = time.monotonic()

    for case in cases:
        started = time.perf_counter()
        record: dict[str, Any] = {"name": case.get("name", "unnamed")}
        try:
            output = app.invoke(
                {
                    "messages": [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=case["input"]),
                    ]
                },
                {"recursion_limit": case.get("max_steps", int(settings.recursion_limit))},
            )
        except Exception as exc:  # one bad case must not end the run
            record.update({"ok": False, "error": f"{type(exc).__name__}: {exc}", "steps": 0, "tools": []})
            results.append(record)
            continue

        messages = output["messages"]
        tools_called = [call["name"] for message in messages for call in (getattr(message, "tool_calls", None) or [])]
        final = (messages[-1].content or "") if messages else ""

        expected_tools = case.get("expect_tools", [])
        expected_text = case.get("expect_contains", "")

        used_expected = all(name in tools_called for name in expected_tools)
        said_expected = expected_text.lower() in final.lower() if expected_text else True

        record.update(
            {
                "ok": used_expected and said_expected,
                "steps": len(messages),
                "tools": tools_called,
                "expected_tools": expected_tools,
                "final": final[:400],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "used_expected_tools": used_expected,
                "said_expected": said_expected,
            }
        )
        results.append(record)

    total = len(results)
    passed = sum(1 for r in results if r.get("ok"))
    expected_total = sum(len(r.get("expected_tools", [])) for r in results)
    actual_total = sum(len(r.get("tools", [])) for r in results)

    summary = {
        "cases": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        # 1.0 when the agent called exactly the tools it needed. Below 1.0
        # means it flailed; above would mean it under-called, so it is capped.
        "tool_precision": min(1.0, expected_total / actual_total) if actual_total else (1.0 if expected_total == 0 else 0.0),
        "avg_steps": round(statistics.fmean([r.get("steps", 0) for r in results]), 2) if total else 0.0,
        "avg_latency_ms": round(statistics.fmean([r.get("latency_ms", 0) for r in results]), 1) if total else 0.0,
    }

    report = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": f"{settings.model_provider}/{settings.model_name}",
        "summary": summary,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    elapsed = int((time.monotonic() - _t_all) * 1000)
    print(f"[<name>-perf] phase=evaluate duration_ms={elapsed} cases={total} pass_rate={summary['pass_rate']:.3f} tool_precision={summary['tool_precision']:.3f}")
    for record in results:
        mark = "ok  " if record.get("ok") else "FAIL"
        print(f"  {mark} {record['name']:<32} steps={record.get('steps')} tools={record.get('tools')}")
    print(f"\npass {passed}/{total}  tool_precision {summary['tool_precision']:.2f}  avg_steps {summary['avg_steps']}")
    print(f"report: {args.out}")

    # Gate on thresholds committed before the run.
    if not args.thresholds.is_file():
        print("no thresholds file — nothing gated", file=sys.stderr)
        return 0
    declared = json.loads(args.thresholds.read_text(encoding="utf-8")).get("thresholds", [])
    failures = []
    for rule in declared:
        actual = resolve(report, rule["metric"])
        if actual is None:
            failures.append(f"{rule['metric']} absent from the report")
            continue
        ok = actual >= rule["value"] if rule.get("direction", "min") == "min" else actual <= rule["value"]
        symbol = ">=" if rule.get("direction", "min") == "min" else "<="
        print(f"  [{'PASS' if ok else 'FAIL'}] {rule['metric']}: {actual} {symbol} {rule['value']}")
        if not ok:
            failures.append(f"{rule['metric']}={actual} (wanted {symbol} {rule['value']})")

    if failures:
        print(f"\nGATE FAILED: {'; '.join(failures)}", file=sys.stderr)
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
