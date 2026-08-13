# Self-contained Dockerfile for <name> (shape: report).
#
# Generates documents: PDF / slideshow / Excel / docx / epub / HTML.
# Ships with a full document toolchain so the project works offline on any
# machine. Optionally offloads to an operator's ConvertX instance via
# CONVERTX_URL (see README.md / docs/SETUP.md).

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

# Document toolchain:
#   pandoc         — markdown ↔ docx/html/epub/latex
#   texlive-xetex  — PDF engine for pandoc (xelatex)
#   libreoffice    — fallback for .docx/.pptx/.xlsx conversion
#   weasyprint deps — CSS-based HTML→PDF engine
#   fonts-*        — bundled fonts so rendered PDFs look consistent in CI
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    pandoc \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-latex-recommended \
    texlive-plain-generic \
    lmodern \
    libreoffice-core \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    fonts-dejavu \
    fonts-liberation \
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

ENV OUTPUTS_DIR=/app/outputs
ENV TEMPLATES_DIR=/app/templates
ENV CONTENT_DIR=/app/content

CMD ["python3", "generate_report.py"]
