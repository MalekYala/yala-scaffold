#!/usr/bin/env python3
"""Build the SFT train/val/eval splits for <name>.

Reads raw examples from `dataset/sources/*.jsonl` and emits chat-format splits
the trainer and evaluator consume:

    dataset/train.jsonl
    dataset/val.jsonl
    eval/eval.jsonl

Two properties matter more than anything else here:

**The system prompt is defined once.** Every example gets the same one, from
`SYSTEM_PROMPT` below. A drifted or truncated prompt between training and
serving does not error — it quietly costs accuracy, and you find out after a
training run. Keep this string byte-identical to what production sends.

**Splitting is deterministic and by input.** Hashing the input rather than
shuffling means the same example always lands in the same split, so
regenerating the dataset does not silently move an example from val into train
and inflate your next eval. `preflight.py` enforces the disjointness this
produces.

Usage:
    python3 dataset/build.py
    python3 dataset/build.py --val-fraction 0.2 --eval-fraction 0.1
    python3 dataset/build.py --sources dataset/sources --out dataset
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Keep byte-identical to the prompt your production code sends. Changing it
# means retraining — the model learns the prompt as much as the task.
SYSTEM_PROMPT = (
    "You classify an inbound support message. "
    "Respond with a single JSON object and nothing else, with exactly these keys: "
    '"label" (one of bug, feature_request, question, billing, unknown) and '
    '"confidence" (one of high, medium, low).'
)


def bucket(text: str) -> float:
    """Stable 0..1 position for an input, from its hash.

    Deterministic on purpose: rebuilding the dataset must not reshuffle
    examples across splits, or every eval number becomes incomparable with the
    last one.
    """
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def to_chat(row: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one raw example into the chat format the trainer expects."""
    user = row.get("input")
    output = row.get("output")
    if not isinstance(user, str) or output is None:
        return None
    target = output if isinstance(output, str) else json.dumps(output, separators=(",", ":"))
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": target},
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SFT splits")
    parser.add_argument("--sources", type=Path, default=PROJECT_ROOT / "dataset" / "sources")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "dataset")
    parser.add_argument("--eval-out", type=Path, default=PROJECT_ROOT / "eval" / "eval.jsonl")
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--eval-fraction", type=float, default=0.15)
    args = parser.parse_args()

    _t = time.monotonic()

    source_files = sorted(args.sources.glob("*.jsonl"))
    if not source_files:
        print(f"ERROR: no *.jsonl under {args.sources}", file=sys.stderr)
        return 1

    seen: set[str] = set()
    train, val, evaluation = [], [], []
    skipped = 0

    for path in source_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"WARN: {path.name}:{number} unparseable, skipped ({exc})", file=sys.stderr)
                skipped += 1
                continue

            example = to_chat(row)
            if example is None:
                print(f"WARN: {path.name}:{number} missing input/output, skipped", file=sys.stderr)
                skipped += 1
                continue

            key = str(row.get("input", "")).strip()
            # Deduplicate across source files: the same input in two sources
            # would otherwise land in two splits and read as leakage.
            if key in seen:
                skipped += 1
                continue
            seen.add(key)

            position = bucket(key)
            if position < args.eval_fraction:
                evaluation.append(example)
            elif position < args.eval_fraction + args.val_fraction:
                val.append(example)
            else:
                train.append(example)

    def write(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    write(args.out / "train.jsonl", train)
    write(args.out / "val.jsonl", val)
    write(args.eval_out, evaluation)

    elapsed = int((time.monotonic() - _t) * 1000)
    print(f"[<name>-perf] phase=build_dataset duration_ms={elapsed} train={len(train)} val={len(val)} eval={len(evaluation)} skipped={skipped}")
    print(f"train {len(train)} / val {len(val)} / eval {len(evaluation)}  (skipped {skipped})")

    if not train or not val:
        print(
            "\nERROR: an empty split. With very few source examples the fractions can starve one — add more data, or lower --val-fraction/--eval-fraction.",
            file=sys.stderr,
        )
        return 1

    print("next: make preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
