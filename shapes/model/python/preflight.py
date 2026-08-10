#!/usr/bin/env python3
"""Validate the SFT dataset for <name> before spending GPU time on it.

Training is the expensive, slow, hard-to-debug part of this pipeline. Almost
everything that makes a fine-tune fail is visible in the dataset beforehand,
and costs seconds to check:

  1. Every line is valid JSON in the chat format the trainer expects.
  2. The system prompt is byte-identical across every example. A drifted or
     truncated prompt does not error — it quietly collapses accuracy, and you
     find out after the training run.
  3. Assistant messages satisfy the output contract (required keys, allowed
     enum values) declared in `eval/contract.json`.
  4. **train and val are disjoint by input.** Leakage is the single most
     common way a fine-tune posts excellent eval numbers and then fails in
     production. It is invisible unless something checks for it.
  5. Every target round-trips through the *real* downstream consumer
     (`contract_check` below). Training a model to emit a string your parser
     rejects produces a model that scores well and is useless.
  6. Length distribution against the trainer's max sequence length, so
     silent truncation of long targets shows up here rather than as
     mysteriously bad outputs.

Exit non-zero on any problem, and report **all** of them at once — fixing a
dataset one error per run is a miserable loop.

Usage:
    python3 preflight.py
    python3 preflight.py --train dataset/train.jsonl --val dataset/val.jsonl
    python3 preflight.py --max-len 2048
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
CONTRACT_FILE = PROJECT_ROOT / "eval" / "contract.json"

errors: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        fail(f"{path} does not exist — run `make dataset` first")
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            fail(f"{path.name}:{number} is not valid JSON: {exc}")
    return rows


def load_contract() -> dict[str, Any]:
    """The output contract: what a valid assistant message looks like.

    Kept as data rather than code so the same file drives preflight, the
    evaluator and your production parser's expectations.
    """
    if not CONTRACT_FILE.is_file():
        return {}
    try:
        return dict(json.loads(CONTRACT_FILE.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        fail(f"eval/contract.json is not valid JSON: {exc}")
        return {}


def messages_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = row.get("messages")
    return msgs if isinstance(msgs, list) else []


def role_content(messages: list[dict[str, Any]], role: str) -> str | None:
    for message in messages:
        if message.get("role") == role:
            content = message.get("content")
            return content if isinstance(content, str) else None
    return None


def contract_check(target: str, contract: dict[str, Any]) -> str | None:
    """Validate one assistant message against the declared output contract.

    Returns an error string, or None when it passes.

    **This is the check worth extending first.** Replace or supplement it with
    a call into whatever actually consumes the model's output in production —
    your parser, your schema validator, your deserialiser. A target that this
    project's own code would reject is a target the model must never be
    trained to produce, and no generic JSON check will catch that.
    """
    if not contract:
        return None

    if contract.get("format") == "json":
        try:
            parsed = json.loads(target)
        except json.JSONDecodeError as exc:
            return f"assistant message is not valid JSON: {exc}"

        if not isinstance(parsed, dict):
            return "assistant message must be a JSON object"

        missing = set(contract.get("required_keys", [])) - set(parsed)
        if missing:
            return f"missing required key(s): {sorted(missing)}"

        for key, allowed in (contract.get("enums") or {}).items():
            if key in parsed and parsed[key] not in allowed:
                return f"{key}={parsed[key]!r} is not one of {allowed}"

    return None


def check_split(name: str, rows: list[dict[str, Any]], contract: dict[str, Any], max_len: int) -> list[str]:
    """Validate one split. Returns the list of user inputs, for leakage checks."""
    inputs: list[str] = []
    system_prompts: Counter[str] = Counter()
    long_examples = 0

    for index, row in enumerate(rows, 1):
        messages = messages_of(row)
        if not messages:
            fail(f"{name}:{index} has no `messages` list")
            continue

        system = role_content(messages, "system")
        user = role_content(messages, "user")
        assistant = role_content(messages, "assistant")

        if user is None:
            fail(f"{name}:{index} has no user message")
            continue
        if assistant is None:
            fail(f"{name}:{index} has no assistant message")
            continue

        if system is not None:
            system_prompts[system] += 1

        inputs.append(user.strip())

        problem = contract_check(assistant, contract)
        if problem:
            fail(f"{name}:{index} {problem}")

        # Rough character proxy for tokens: exact counts need the tokenizer,
        # which would drag the whole heavy dependency set into preflight.
        approx_tokens = (len(system or "") + len(user) + len(assistant)) // 4
        if approx_tokens > max_len:
            long_examples += 1

    if len(system_prompts) > 1:
        top = system_prompts.most_common()
        fail(
            f"{name} has {len(system_prompts)} different system prompts "
            f"(most common appears {top[0][1]}x, next {top[1][1]}x). "
            f"Every example must share one byte-identical system prompt — a "
            f"drifted prompt does not error, it just costs you accuracy."
        )

    if long_examples:
        warn(
            f"{name}: {long_examples} example(s) look longer than max_len={max_len} "
            f"tokens and will be truncated during training. Long targets lose "
            f"their endings, which is hard to spot in the resulting model."
        )

    duplicates = [text for text, count in Counter(inputs).items() if count > 1]
    if duplicates:
        warn(f"{name}: {len(duplicates)} duplicated input(s). Duplicates skew the loss toward whatever they represent.")

    return inputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the SFT dataset before training")
    parser.add_argument("--train", type=Path, default=PROJECT_ROOT / "dataset" / "train.jsonl")
    parser.add_argument("--val", type=Path, default=PROJECT_ROOT / "dataset" / "val.jsonl")
    parser.add_argument(
        "--max-len",
        type=int,
        default=1024,
        help="trainer max sequence length, for the truncation warning",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1,
        help="fail if a split has fewer rows than this",
    )
    args = parser.parse_args()

    _t = time.monotonic()

    contract = load_contract()
    train_rows = load_jsonl(args.train)
    val_rows = load_jsonl(args.val)

    # An empty dataset that "passes" is the worst outcome: it trains, produces
    # a model, and teaches nothing. Treat it as a failure, loudly.
    if len(train_rows) < args.min_rows:
        fail(f"train split has {len(train_rows)} row(s), need at least {args.min_rows}")
    if len(val_rows) < args.min_rows:
        fail(f"val split has {len(val_rows)} row(s), need at least {args.min_rows}")

    train_inputs = check_split("train", train_rows, contract, args.max_len)
    val_inputs = check_split("val", val_rows, contract, args.max_len)

    # Leakage. The failure this catches looks like success on every metric you
    # are watching, right up until production.
    overlap = set(train_inputs) & set(val_inputs)
    if overlap:
        sample = sorted(overlap)[:5]
        fail(
            f"{len(overlap)} input(s) appear in BOTH train and val — the eval "
            f"score will be inflated and will not predict production behaviour.\n" + "\n".join(f"         {text[:90]!r}" for text in sample)
        )

    elapsed = int((time.monotonic() - _t) * 1000)
    print(f"[<name>-perf] phase=preflight duration_ms={elapsed} train={len(train_rows)} val={len(val_rows)} errors={len(errors)} warnings={len(warnings)}")

    # stderr is unbuffered and stdout is not: without this the problems below
    # print above the summary line they belong to.
    sys.stdout.flush()

    for message in warnings:
        print(f"WARN  {message}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} problem(s) — not training on this dataset:", file=sys.stderr)
        for message in errors:
            print(f"  {message}", file=sys.stderr)
        return 1

    print(f"dataset OK: {len(train_rows)} train / {len(val_rows)} val, no leakage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
