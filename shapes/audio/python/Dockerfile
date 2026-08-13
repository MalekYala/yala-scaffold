# Self-contained Dockerfile for <name> (shape: audio).
# Long-running HTTP service. All dependencies installed inside the image.
# Build: docker compose build
# Run:   docker compose up -d

FROM python:3.12-slim AS base

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/config \
    XDG_DATA_HOME=/tmp/data \
    XDG_STATE_HOME=/tmp/state \
    RUFF_CACHE_DIR=/tmp/ruff

# OS-level deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --home-dir /home/app app \
    && chown app:app /app

# Install Python deps first for better layer caching
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

# Build version, supplied by `make release` / CI from `git describe`. Reported
# by /health and by qa_check, so an incident can answer "which build is this?"
# without going to the deployment logs to guess.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION
COPY --chown=app:app . .
USER app

# Default port (overridable via PORT env var)
ARG PORT=<PORT>
ENV PORT=${PORT}
EXPOSE ${PORT}

# Healthcheck — relies on /health endpoint exposed by the app (AGENTS.md §14)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://127.0.0.1:${PORT}/health || exit 1

# Bind to 0.0.0.0 INSIDE the container — external localhost-only exposure
# is enforced by the `127.0.0.1:${PORT}:${PORT}` port mapping in
# docker-compose.yml (AGENTS.md §2). Binding the in-container process to
# 127.0.0.1 would make it unreachable via the port mapping.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
