# Self-contained Dockerfile for <name> (shape: game).
#
# Ships the Godot engine so the game can be built and checked with nothing
# installed on the host. Godot publishes both x86_64 and arm64 Linux builds,
# so this image works on either without emulation.

FROM python:3.12-slim AS base

ARG APP_UID=1000
ARG APP_GID=1000
ARG GODOT_VERSION=4.3-stable

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_DATA_HOME=/tmp/data \
    XDG_CONFIG_HOME=/tmp/config \
    GODOT_BIN=/usr/local/bin/godot

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Fetch the engine for this image's architecture. TARGETARCH is supplied by
# BuildKit; the fallback keeps a plain `docker build` working.
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) godot_arch=x86_64 ;; \
      arm64) godot_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    ver="${GODOT_VERSION}"; \
    url="https://github.com/godotengine/godot/releases/download/${ver}/Godot_v${ver}_linux.${godot_arch}.zip"; \
    curl -fsSL -o /tmp/godot.zip "$url"; \
    unzip -q /tmp/godot.zip -d /tmp/godot; \
    mv /tmp/godot/Godot_v${ver}_linux.${godot_arch} /usr/local/bin/godot; \
    chmod +x /usr/local/bin/godot; \
    rm -rf /tmp/godot.zip /tmp/godot; \
    godot --version

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

ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION

COPY --chown=app:app . .
USER app

# Default run is the headless contract check: scenes load, references resolve,
# scripts compile, the simulation advances deterministically and stays inside
# its frame budget. No display, no GPU, no input.
CMD ["python3", "qa_check.py"]
