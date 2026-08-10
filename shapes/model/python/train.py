#!/usr/bin/env python3
"""LoRA supervised fine-tune for <name>.

Trains a PEFT LoRA adapter on `dataset/{train,val}.jsonl`. Adapters are small
(tens of MB) and cheap to keep, so every experiment stays on disk and
comparable — which is what makes the measure-change-measure loop in
AUTORESEARCH.md work for a model project.

**This is the only part of the project that needs a GPU**, and the only part
that needs the heavy dependency set. It runs in a separate image behind a
Compose profile so `make setup`, `make test`, `make lint` and `make qa` stay
fast and work on any machine:

    make train          # builds the training image, then trains

Every hyperparameter is env-overridable, so a sweep is a shell loop rather
than a series of edits:

    for lr in 1e-4 2e-4; do
      TRAIN_LR=$lr TRAIN_OUT_DIR=output/lora-lr$lr make train
    done

Refuses to start unless `preflight.py` passes. Discovering a broken dataset
after an hour on a GPU is an expensive way to learn something that takes two
seconds to check.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "dataset"

BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
EPOCHS = float(os.environ.get("TRAIN_EPOCHS", "3"))
BATCH_SIZE = int(os.environ.get("TRAIN_BATCH_SIZE", "2"))
GRAD_ACCUM = int(os.environ.get("TRAIN_GRAD_ACCUM", "8"))
MAX_LEN = int(os.environ.get("TRAIN_MAX_LEN", "1024"))
LEARNING_RATE = float(os.environ.get("TRAIN_LR", "2e-4"))
LORA_R = int(os.environ.get("TRAIN_LORA_R", "16"))
LORA_ALPHA = int(os.environ.get("TRAIN_LORA_ALPHA", "32"))
LORA_DROPOUT = float(os.environ.get("TRAIN_LORA_DROPOUT", "0.05"))
OUT_DIR = Path(os.environ.get("TRAIN_OUT_DIR", str(PROJECT_ROOT / "output" / "lora-adapter")))
SEED = int(os.environ.get("TRAIN_SEED", "0"))


def preflight() -> None:
    """Never spend GPU time on a dataset that has not been checked."""
    print("[train] preflight…", flush=True)
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "preflight.py"), "--max-len", str(MAX_LEN)],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(
            "[train] preflight failed — refusing to train on this dataset.\n        Fix the problems above, or run preflight.py directly to iterate.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> int:
    preflight()

    # Imported after preflight so a dataset problem surfaces in seconds rather
    # than after the CUDA stack has finished loading.
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    print(f"[train] base={BASE_MODEL}")
    print(f"[train] out={OUT_DIR}")
    print(f"[train] epochs={EPOCHS} bs={BATCH_SIZE}x{GRAD_ACCUM} lr={LEARNING_RATE} max_len={MAX_LEN}")
    print(f"[train] lora r={LORA_R} alpha={LORA_ALPHA} dropout={LORA_DROPOUT}")

    if not torch.cuda.is_available():
        print(
            "[train] WARNING: no CUDA device visible. Training will fall back to CPU and be impractically slow.\n        Check that the container was started with GPU access — see docs/SETUP.md.",
            file=sys.stderr,
        )

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(DATA_DIR / "train.jsonl"),
            "validation": str(DATA_DIR / "val.jsonl"),
        },
    )

    peft_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        # Attention + MLP projections. Narrow this to the attention
        # projections only if you are memory-bound.
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )

    config = SFTConfig(
        output_dir=str(OUT_DIR),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        max_length=MAX_LEN,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        # Keep the best checkpoint by validation loss rather than the last —
        # the last epoch is frequently not the best one.
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=2,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        seed=SEED,
        report_to=[],
    )

    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=peft_config,
        processing_class=tokenizer,
    )

    _t = time.monotonic()
    trainer.train()
    elapsed = int((time.monotonic() - _t) * 1000)

    trainer.save_model(str(OUT_DIR))
    tokenizer.save_pretrained(str(OUT_DIR))

    print(f"[<name>-perf] phase=train duration_ms={elapsed} epochs={EPOCHS} base={BASE_MODEL} out={OUT_DIR.name}")
    print(f"\n[train] adapter written to {OUT_DIR}")
    print("[train] next:")
    print(f"  make merge ADAPTER={OUT_DIR}     # adapter + base -> a servable model")
    print("  make serve                        # start it behind an OpenAI-compatible API")
    print("  make evaluate && make qa          # score it, then gate on the thresholds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
