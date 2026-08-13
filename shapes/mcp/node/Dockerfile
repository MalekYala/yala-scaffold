# Self-contained Dockerfile for <name> (shape: service, lang: node).
# Long-running HTTP service on Node.js 20 LTS.

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
RUN apk add --no-cache curl ca-certificates
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

ARG PORT=<PORT>
ENV PORT=${PORT}
# Bind to 0.0.0.0 INSIDE the container — external localhost-only exposure
# is enforced by the `127.0.0.1:${PORT}:${PORT}` mapping in compose
# (AGENTS.md §2). Binding to 127.0.0.1 inside the container would make it
# unreachable via the port mapping.
ENV HOST=0.0.0.0


# Healthcheck — hits the /health endpoint exposed by src/index.js (AGENTS.md §14)

