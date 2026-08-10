# Self-contained Dockerfile for <name> (shape: worker, lang: node).
# Background task processor — no HTTP port, long-running.

FROM node:20-alpine AS development

ARG APP_UID=1000
ARG APP_GID=1000
RUN apk add --no-cache ca-certificates
RUN deluser node \
    && addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app

WORKDIR /app
RUN chown app:app /app
USER app

COPY --chown=app:app package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --chown=app:app . .

FROM development AS test
CMD ["npm", "test"]

FROM node:20-alpine AS runtime

# Build version, supplied by `make release` / CI from `git describe`. Reported
# by /health and by qa_check, so an incident can answer "which build is this?"
# without going to the deployment logs to guess.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION

ARG APP_UID=1000
ARG APP_GID=1000
RUN apk add --no-cache ca-certificates
RUN deluser node \
    && addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app
WORKDIR /app
RUN chown app:app /app
USER app
COPY --chown=app:app package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
COPY --chown=app:app src ./src
COPY --chown=app:app qa_check.js metric.sh ./

# Healthcheck: heartbeat file touched by the worker loop.
# Unhealthy if the file is missing or older than 60s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "const fs=require('fs'); try { const age=(Date.now()-fs.statSync('/app/data/heartbeat').mtimeMs)/1000; process.exit(age<60?0:1); } catch { process.exit(1); }" || exit 1

CMD ["node", "src/worker.js"]
