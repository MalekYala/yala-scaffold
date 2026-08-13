#!/usr/bin/env python3
"""Merge a LoRA adapter into its base model, for <name>.

Training produces an adapter — small, cheap to keep, but most serving stacks
either cannot load one or are slower when they do. Merging produces a single
standalone model directory you can serve directly.

Keep the adapter after merging. It is the cheap artifact worth archiving per
experiment; the merged model is a derived, regenerable one, and merged
directories are large enough that keeping every one is a disk problem.

Usage:
    python3 merge.py                                   # default adapter + base
    python3 merge.py --adapter output/lora-v2 --out output/merged-v2
    python3 merge.py --dtype float16

Exit codes:
    0  merged
    1  adapter or base missing / merge failed
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge a LoRA adapter into its base model")
    parser.add_argument(
        "--adapter",
        type=Path,
        default=Path(os.environ.get("TRAIN_OUT_DIR", str(PROJECT_ROOT / "output" / "lora-adapter"))),
    )
    parser.add_argument(
        "--base",
        default=os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
    )
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "output" / "merged")
    parser.add_argument(
        "--dtype",
        default=os.environ.get("MERGE_DTYPE", "bfloat16"),
        choices=["bfloat16", "float16", "float32"],
    )
    args = parser.parse_args()

    if not args.adapter.is_dir():
        print(f"ERROR: no adapter at {args.adapter} — run `make train` first")
        return 1

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dtype = getattr(torch, args.dtype)
    print(f"[merge] base={args.base}")
    print(f"[merge] adapter={args.adapter}")
    print(f"[merge] out={args.out} dtype={args.dtype}")

    _t = time.monotonic()

    # CPU merge: it is a one-off arithmetic pass, and doing it on CPU keeps the
    # GPU free and avoids needing one at all on a build host.
    base_model = AutoModelForCausalLM.from_pretrained(args.base, dtype=dtype, device_map="cpu")
    merged = PeftModel.from_pretrained(base_model, str(args.adapter)).merge_and_unload()

    args.out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(args.out), safe_serialization=True)

    # The tokenizer must travel with the model. A merged directory without one
    # fails at serve time with an error that points nowhere useful.
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(args.adapter), use_fast=True)
    except (OSError, ValueError):
        tokenizer = AutoTokenizer.from_pretrained(args.base, use_fast=True)
    tokenizer.save_pretrained(str(args.out))

    elapsed = int((time.monotonic() - _t) * 1000)
    print(f"[<name>-perf] phase=merge duration_ms={elapsed} out={args.out.name}")
    print(f"\n[merge] merged model at {args.out}")
    print("[merge] next: make serve && make evaluate && make qa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
