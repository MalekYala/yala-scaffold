# Self-contained Dockerfile for <name> (shape: webapp, lang: node).
# Multi-stage build:
#   1. `development` — full dependency set for local commands
#   2. `test`        — runs unit tests, lint, and the production build
#   3. `builder`     — produces dist/
#   4. `runtime`     — lean Fastify runtime with production dependencies

# ── builder ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS development

ARG APP_UID=1000
ARG APP_GID=1000
RUN deluser node \
    && addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app
WORKDIR /build
RUN chown app:app /build
USER app

# Install ALL deps (including dev) for the build step
COPY --chown=app:app package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source + brand + locales so Vite can embed them at build time
COPY --chown=app:app . .

FROM development AS test
ENV BUILD_OUT_DIR=/tmp/dist
CMD ["npm", "test"]

FROM development AS builder

# Make the favicon path in index.html / brand/config.json discoverable by Vite
RUN cp -r brand public/brand && cp -r locales public/locales || true

RUN npm run build

# ── runtime ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS runtime

# Build version, supplied by `make release` / CI from `git describe`. Reported
# by /health and by qa_check, so an incident can answer "which build is this?"
# without going to the deployment logs to guess.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION

ARG APP_UID=1000
ARG APP_GID=1000
RUN apk add --no-cache curl ca-certificates
RUN deluser node \
    && addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app

WORKDIR /app
RUN chown app:app /app
USER app

# Install only production deps (Fastify + dotenv) for the runtime image
COPY --chown=app:app package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

# Copy the built frontend, server, brand config, and locales
COPY --chown=app:app --from=builder /build/dist ./dist
COPY --chown=app:app server.js qa_check.js metric.sh ./
COPY --chown=app:app brand ./brand
COPY --chown=app:app locales ./locales

ARG PORT=<PORT>
ENV PORT=${PORT}
ENV NODE_ENV=production
# Bind to 0.0.0.0 INSIDE the container — external localhost-only exposure
# is enforced by the `127.0.0.1:${PORT}:${PORT}` mapping in compose
# (AGENTS.md §2). Binding to 127.0.0.1 inside the container would make it
# unreachable via the port mapping.
ENV HOST=0.0.0.0
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://127.0.0.1:${PORT}/health || exit 1

CMD ["node", "server.js"]
