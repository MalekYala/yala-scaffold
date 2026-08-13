# Self-contained Dockerfile for <name> (shape: model).
#
# Two families of image, and the split is the point:
#
#   runtime / test / lint / typecheck — LIGHT. Dataset tooling, evaluation and
#     the QA gate. No torch, no CUDA, ~150MB. Builds in seconds on any machine.
#     This is what `make setup`, `make test`, `make lint` and `make qa` use, so
#     the whole quality loop works on a laptop with no GPU.
#
#   train — HEAVY. torch + transformers + peft + trl, multi-gigabyte, needs a
#     CUDA runtime. Built only by `make train`.
#
# Keeping them apart is what stops a fine-tuning project from being one where
# nobody can run the tests.

FROM python:3.12-slim AS base

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/tmp/huggingface \
    RUFF_CACHE_DIR=/tmp/ruff

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --home-dir /home/app app \
    && chown app:app /app

COPY --chown=app:app requirements.txt .
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

FROM base AS development-dependencies
COPY requirements-dev.txt .
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements-dev.txt

FROM development-dependencies AS development
COPY --chown=app:app . .
USER app

FROM development AS test
CMD ["pytest", "-q", "-p", "no:cacheprovider", "tests/"]

FROM development AS lint
CMD ["sh", "-c", "ruff check . && ruff format --check ."]

FROM development AS typecheck
CMD ["mypy", "--cache-dir=/tmp/mypy", "."]

FROM base AS runtime

# Build version, supplied by `make release` / CI from `git describe`.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION

COPY --chown=app:app . .
USER app

# Default: build the dataset, validate it, and evaluate whatever is served.
# Training is a separate, explicit target — see the `train` stage.
CMD ["sh", "-c", "python3 dataset/build.py && python3 preflight.py"]

# ── Training image ─────────────────────────────────────────────────────────
# Separate base: the CUDA runtime and the heavy Python stack. Only built when
# `make train` asks for it, via the `train` Compose profile.
#
# The default tag targets CUDA 12.4. Match it to your driver — a mismatch here
# surfaces as an unhelpful "no kernel image is available" at the first forward
# pass rather than as a clear error at build time.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS train

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/data/huggingface \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app
RUN groupadd --gid "${APP_GID}" app 2>/dev/null || true \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/app app 2>/dev/null || true \
    && chown -R "${APP_UID}:${APP_GID}" /app

COPY requirements-train.txt .
# torch already ships in the base image; installing it again would download
# several gigabytes to arrive at the same place.
RUN grep -v '^torch==' requirements-train.txt > /tmp/train-deps.txt \
    && python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/train-deps.txt

COPY --chown=app:app . .
USER app

CMD ["python3", "train.py"]
