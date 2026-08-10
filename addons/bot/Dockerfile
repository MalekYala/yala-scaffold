# Dockerfile for <name>-bot.
# Runs the project's IRC agent. Lightweight — no ML/embedding deps; the
# actual RAG backend is accessed via HTTP (remote) or SQLite (built-in).

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    make \
    && rm -rf /var/lib/apt/lists/*

# The runtime UID/GID default to the common first host user. Override these
# build args when the project directory is owned by another numeric user.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home app

# This image-local setting does not change host Git configuration. It lets the
# non-root bot operate on the explicitly mounted project directory.
RUN git config --system --add safe.directory '*'

WORKDIR /app

COPY bot/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole project so the bot can read STRATEGY.md, README.md,
# AGENTS.md, rag/config.yml, logs/, results/, etc. The read is non-invasive
# (mount the project read-only in docker-compose.bot.yml to be safe).
COPY . .
RUN chown -R app:app /app

ENV HOME=/tmp
ENV PYTHONDONTWRITEBYTECODE=1
USER app

# Bot healthcheck: heartbeat file touched by bot.py's main loop every 30s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import os, time, sys; sys.exit(0 if time.time() - os.path.getmtime('/app/data/bot-heartbeat') < 120 else 1)" || exit 1

CMD ["python3", "bot/bot.py"]
