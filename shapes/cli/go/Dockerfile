FROM golang:1.24-alpine AS development

ARG APP_UID=1000
ARG APP_GID=1000
ENV CGO_ENABLED=0 GOCACHE=/tmp/go-build
RUN addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app
WORKDIR /app
RUN chown app:app /app
# go.su[m] is a glob that matches go.sum when it exists and is skipped when it
# does not. This CLI is deliberately stdlib-only, so it has no go.sum yet — and
# a plain `COPY go.sum` would fail the build until someone adds a dependency.
COPY --chown=app:app go.mod go.su[m] ./
RUN go mod download
COPY --chown=app:app . .
USER app

FROM development AS test
CMD ["go", "test", "./..."]

FROM development AS lint
CMD ["sh", "-c", "test -z \"$(gofmt -l .)\" && go vet ./..."]

FROM development AS typecheck
CMD ["go", "test", "./..."]

FROM development AS builder
# VERSION is injected into the binary, not just the environment: `--version`
# is part of this shape's contract and qa-check asserts on it, so a binary
# that cannot report its own build is a failing binary.
ARG VERSION=0.0.0-dev
RUN go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /tmp/<name> ./cmd/cli \
    && go build -trimpath -ldflags="-s -w" -o /tmp/qa-check ./cmd/qa

FROM alpine:3.21 AS runtime

# Build version, supplied by `make release` / CI from `git describe`. Reported
# by /health and by qa_check, so an incident can answer "which build is this?"
# without going to the deployment logs to guess.
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION}
LABEL org.opencontainers.image.version=$VERSION
ARG APP_UID=1000
ARG APP_GID=1000
RUN addgroup -g "${APP_GID}" app \
    && adduser -D -u "${APP_UID}" -G app app
WORKDIR /app
COPY --from=builder --chown=app:app /tmp/<name> /app/<name>
COPY --from=builder --chown=app:app /tmp/qa-check /app/qa-check
COPY --chown=app:app metric.sh /app/metric.sh
# qa-check compares stdout against these, resolved relative to WORKDIR.
COPY --chown=app:app testdata /app/testdata
USER app
ENTRYPOINT ["/app/<name>"]
