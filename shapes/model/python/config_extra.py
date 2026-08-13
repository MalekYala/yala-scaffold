"""Shape-specific configuration for <name> (shape: model).

Training, serving and evaluation each need a handful of settings that the
universal schema has no business carrying. Declaring them here means they are
typed, validated at startup, and documented in `.env.example` automatically.

The training hyperparameters are deliberately *also* readable straight from
the environment by `train.py`, so a sweep stays a shell loop:

    for lr in 1e-4 2e-4; do TRAIN_LR=$lr make train; done
"""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "BASE_MODEL",
        "Base model to fine-tune, as a HuggingFace repo id or a local path. The default is deliberately tiny so the pipeline runs end to end on modest hardware before you commit to something large.",
        default="Qwen/Qwen2.5-0.5B-Instruct",
        section="Model training",
    ),
    Field(
        "MODEL_CACHE",
        "Host directory for base weights and the HuggingFace cache. Point this at a disk with room — base models reach tens of gigabytes.",
        default="./data",
    ),
    Field(
        "GPU_COUNT",
        "GPUs to reserve for the train and serve services.",
        cast=as_int,
        default=1,
    ),
    Field(
        "EVAL_BASE_URL",
        "OpenAI-compatible endpoint the evaluator scores against. Evaluating a served model rather than a checkpoint is the point: it includes the serving stack, quantisation and sampling settings.",
        default="http://127.0.0.1:8000/v1",
        section="Evaluation",
    ),
    Field(
        "EVAL_MODEL",
        "Model name to request from that endpoint.",
        default="<name>",
    ),
    Field(
        "EVAL_API_KEY",
        "Bearer token for the eval endpoint. Unset for a local vLLM server.",
        commented=True,
        secret=True,
    ),
    Field(
        "SERVE_PORT",
        "Host port for the vLLM server. Bound to 127.0.0.1 only.",
        cast=as_int,
        default=8000,
        section="Serving",
    ),
]
