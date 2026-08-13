# Self-contained Dockerfile for <name> (shape: notebook).
#
# Jupyter-first project. `docker compose up` runs JupyterLab for interactive
# work; the CI pipeline runs `nbconvert --execute` on every notebook in
# notebooks/ to catch regressions.

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
    RUFF_CACHE_DIR=/tmp/ruff \
    MPLCONFIGDIR=/tmp/matplotlib \
    JUPYTER_CONFIG_DIR=/tmp/jupyter/config \
    JUPYTER_DATA_DIR=/tmp/jupyter/data \
    JUPYTER_RUNTIME_DIR=/tmp/jupyter/runtime \
    IPYTHONDIR=/tmp/ipython

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
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

# Build version, supplied by `make release` / CI from `git describe`. Reported
# by /health and by qa_check, so an incident can answer "which build is this?"
# without going to the deployment logs to guess.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION
COPY --chown=app:app . .
USER app

ARG PORT=<PORT>
ENV PORT=${PORT}
EXPOSE ${PORT}

# Network and authentication settings live in Jupyter's config file so an
# operator-supplied token never appears in the process argument list.
CMD ["jupyter", "lab", "--config=/app/jupyter_server_config.py"]
