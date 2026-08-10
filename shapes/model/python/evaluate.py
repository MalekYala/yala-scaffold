#!/usr/bin/env python3
"""Evaluate <name>'s model against a served endpoint, and write a JSON report.

Runs every example in the eval set against an OpenAI-compatible endpoint
(vLLM, Ollama, llama.cpp, TGI, or a hosted API), scores the outputs, and
writes a report that `qa_check.py` gates on.

It evaluates a **served model**, not a checkpoint on disk, deliberately: what
matters is the thing you would actually route traffic to, including its
serving stack, quantisation and sampling parameters. A checkpoint that scores
well and a server that answers badly is a real and common gap.

The report records accuracy *and* latency together. A model that is two points
more accurate and three times slower is usually not an improvement, and a
report that omits latency lets that decision be made by accident.

Usage:
    python3 evaluate.py                          # against eval/eval.jsonl
    python3 evaluate.py --dataset eval/held-out.jsonl --out eval/reports/held-out.json
    python3 evaluate.py --model my-model-v2 --base-url http://127.0.0.1:8000/v1
    python3 evaluate.py --limit 20               # quick smoke run

Exit codes:
    0  the evaluation ran (pass/fail is qa_check.py's job, not this script's)
    1  the endpoint was unreachable, or the eval set is empty/unusable
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = PROJECT_ROOT / "eval" / "eval.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "eval" / "reports" / "latest.json"
CONTRACT_FILE = PROJECT_ROOT / "eval" / "contract.json"


def load_contract() -> dict[str, Any]:
    if not CONTRACT_FILE.is_file():
        return {}
    try:
        return dict(json.loads(CONTRACT_FILE.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


def load_examples(path: Path, limit: int | None) -> list[dict[str, Any]]:
    if not path.is_file():
        print(f"ERROR: no eval set at {path}", file=sys.stderr)
        raise SystemExit(1)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"WARN: skipping unparseable eval line: {exc}", file=sys.stderr)
    return rows[:limit] if limit else rows


def complete(base_url: str, model: str, messages: list[dict[str, Any]], api_key: str, timeout: float) -> tuple[str | None, float, str | None]:
    """One chat completion. Returns (text, latency_ms, error)."""
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            # Deterministic by default: an eval that moves when nothing changed
            # cannot tell you whether your change helped.
            "temperature": 0.0,
            "max_tokens": 512,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=payload, headers=headers)

    started = time.perf_counter()
    try:
        # The URL comes from --base-url, which is operator-supplied, not user input.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        elapsed = (time.perf_counter() - started) * 1000.0
        text = body["choices"][0]["message"]["content"]
        return text, elapsed, None
    except urllib.error.HTTPError as exc:
        return None, (time.perf_counter() - started) * 1000.0, f"HTTP {exc.code}: {exc.read()[:200]!r}"
    # Deliberately broad: one bad example must not end the run.
    except Exception as exc:
        return None, (time.perf_counter() - started) * 1000.0, f"{type(exc).__name__}: {exc}"


def score(prediction: str, expected: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Compare one prediction against its target.

    Exact match is the floor. For a JSON contract it also scores each key
    independently, because "which field regressed" is the question you
    actually ask when a number drops, and a single aggregate cannot answer it.

    **Replace this with your task's real metric.** Exact match on free-form
    text is close to meaningless; on a structured contract it is exactly right.
    """
    result: dict[str, Any] = {"exact_match": prediction.strip() == expected.strip(), "fields": {}}

    if contract.get("format") != "json":
        return result

    try:
        got = json.loads(prediction)
    except json.JSONDecodeError:
        # A parse failure is its own category. A model that emits unparseable
        # output is broken in a way that per-field accuracy would hide.
        result["parse_error"] = True
        return result

    result["parse_error"] = False
    try:
        want = json.loads(expected)
    except json.JSONDecodeError:
        return result

    if isinstance(got, dict) and isinstance(want, dict):
        for key in want:
            result["fields"][key] = got.get(key) == want[key]

    return result


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def main() -> int:
    import os

    parser = argparse.ArgumentParser(description="Evaluate a served model")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--model", default=os.environ.get("EVAL_MODEL", "<name>"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8000/v1"),
    )
    parser.add_argument("--api-key", default=os.environ.get("EVAL_API_KEY", ""))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    contract = load_contract()
    examples = load_examples(args.dataset, args.limit)

    # An eval that finds nothing to run and reports success is worse than one
    # that fails: it looks like coverage and is not.
    if not examples:
        print(f"ERROR: {args.dataset} contains no usable examples", file=sys.stderr)
        return 1

    print(f"evaluating {len(examples)} example(s) against {args.model} at {args.base_url}", file=sys.stderr)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    errors = 0
    _t_all = time.monotonic()

    for index, row in enumerate(examples, 1):
        messages = [m for m in row.get("messages", []) if m.get("role") != "assistant"]
        expected = ""
        for message in row.get("messages", []):
            if message.get("role") == "assistant":
                expected = message.get("content") or ""

        prediction, latency_ms, error = complete(args.base_url, args.model, messages, args.api_key, args.timeout)
        latencies.append(latency_ms)

        if error is not None:
            errors += 1
            results.append({"index": index, "error": error, "latency_ms": round(latency_ms, 2)})
            # A dead endpoint should stop the run immediately rather than
            # producing a report full of zeros that looks like a bad model.
            if errors >= 5 and errors == index:
                print(
                    f"ERROR: first {errors} requests all failed — is the model served at {args.base_url}?\n       last error: {error}",
                    file=sys.stderr,
                )
                return 1
            continue

        scored = score(prediction or "", expected, contract)
        results.append(
            {
                "index": index,
                "latency_ms": round(latency_ms, 2),
                "expected": expected,
                "prediction": prediction,
                **scored,
            }
        )

        if index % 25 == 0:
            print(f"  {index}/{len(examples)}…", file=sys.stderr)

    scored_results = [r for r in results if "error" not in r]
    total = len(scored_results)

    field_names: set[str] = set()
    for result in scored_results:
        field_names |= set(result.get("fields", {}))

    summary: dict[str, Any] = {
        "total": len(results),
        "scored": total,
        "request_errors": errors,
        "parse_errors": sum(1 for r in scored_results if r.get("parse_error")),
        "exact_match": (sum(1 for r in scored_results if r.get("exact_match")) / total if total else 0.0),
        "fields": {name: (sum(1 for r in scored_results if r.get("fields", {}).get(name)) / total if total else 0.0) for name in sorted(field_names)},
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else 0.0,
            "p95": round(percentile(latencies, 0.95), 2),
            "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        },
    }
    summary["parse_error_rate"] = summary["parse_errors"] / total if total else 1.0

    report = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "base_url": args.base_url,
        "dataset": str(args.dataset.name),
        "summary": summary,
        "results": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    elapsed = int((time.monotonic() - _t_all) * 1000)
    print(
        f"[<name>-perf] phase=evaluate duration_ms={elapsed} examples={len(results)} "
        f"exact_match={summary['exact_match']:.4f} "
        f"parse_error_rate={summary['parse_error_rate']:.4f} "
        f"p50_ms={summary['latency_ms']['p50']}"
    )
    print(f"\nexact match : {summary['exact_match']:.1%}")
    for name, value in summary["fields"].items():
        print(f"  {name:<20} {value:.1%}")
    print(f"parse errors: {summary['parse_errors']} ({summary['parse_error_rate']:.1%})")
    print(f"latency     : p50 {summary['latency_ms']['p50']}ms  p95 {summary['latency_ms']['p95']}ms")
    print(f"\nreport: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
