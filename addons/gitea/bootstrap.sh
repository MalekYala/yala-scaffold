#!/usr/bin/env bash
# gitea/bootstrap.sh — first-run automation for <name>'s Gitea instance.
#
# Run ONCE after `make gitea` brings up the container. This script:
#   1. Waits for Gitea HTTP to come up
#   2. Creates a bot user (<name>-bot) via `gitea admin user create`
#   3. Generates an API token for the bot user with repo write scope
#   4. Writes GITEA_TOKEN to the project's .env (idempotent — updates if present)
#   5. Creates the project repo (<name>) under the bot user
#   6. Adds a `gitea` git remote to the host project pointing at the new repo
#   7. Pushes the current main branch to seed Gitea
#
# Idempotent — safe to rerun. If the bot user / token / repo already exist,
# this script skips the create steps.
#
# Env vars consumed:
#   GITEA_HTTP_PORT       — host port Gitea is bound to (default 3030)
#   GITEA_CONTAINER       — container name (default <name>-gitea)
#   GITEA_BOT_USER        — bot user (default <name>-bot)
#   GITEA_BOT_PASSWORD    — bot password (auto-generated if unset; written to .env)
#   GITEA_BOT_EMAIL       — bot email (default <name>-bot@local)
#   GITEA_REPO            — repo name (default <name>)

set -euo pipefail

PROJECT_NAME="<name>"
GITEA_HTTP_PORT="${GITEA_HTTP_PORT:-3030}"
GITEA_CONTAINER="${GITEA_CONTAINER:-${PROJECT_NAME}-gitea}"
GITEA_BOT_USER="${GITEA_BOT_USER:-${PROJECT_NAME}-bot}"
GITEA_BOT_EMAIL="${GITEA_BOT_EMAIL:-${GITEA_BOT_USER}@local}"
GITEA_REPO="${GITEA_REPO:-${PROJECT_NAME}}"
GITEA_URL="http://127.0.0.1:${GITEA_HTTP_PORT}"
GITEA_API_URL="${GITEA_URL}/api/v1"

log() { echo "[gitea-bootstrap] $*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require docker
require curl
require git

# ── 1. Wait for Gitea HTTP ────────────────────────────────────────────────
log "waiting for Gitea at ${GITEA_URL} ..."
for i in $(seq 1 60); do
    if curl -sf "${GITEA_URL}/api/healthz" >/dev/null 2>&1; then
        log "gitea is up (after ${i}s)"
        break
    fi
    sleep 1
    if [ "$i" = "60" ]; then
        die "gitea did not come up within 60s — check: docker logs ${GITEA_CONTAINER}"
    fi
done

# ── 2. Generate a bot password if not supplied ────────────────────────────
if [ -z "${GITEA_BOT_PASSWORD:-}" ]; then
    if command -v openssl >/dev/null 2>&1; then
        GITEA_BOT_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/')"
    else
        GITEA_BOT_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '=+/')"
    fi
    log "generated bot password (stored in .env)"
fi

# ── 3. Create bot user (idempotent via `gitea admin user list`) ───────────
log "ensuring bot user ${GITEA_BOT_USER} exists ..."
if docker exec "${GITEA_CONTAINER}" su git -c "gitea admin user list --admin" 2>/dev/null \
        | awk 'NR>1 {print $2}' | grep -qx "${GITEA_BOT_USER}"; then
    log "bot user ${GITEA_BOT_USER} already exists"
else
    docker exec "${GITEA_CONTAINER}" su git -c \
        "gitea admin user create --username ${GITEA_BOT_USER} \
                                 --password '${GITEA_BOT_PASSWORD}' \
                                 --email ${GITEA_BOT_EMAIL} \
                                 --admin \
                                 --must-change-password=false" \
        || die "failed to create bot user"
    log "created bot user ${GITEA_BOT_USER}"
fi

# ── 4. Generate an API token (always create fresh on bootstrap) ───────────
log "generating API token for ${GITEA_BOT_USER} ..."
TOKEN_NAME="orchestration-bot-$(date +%s)"
TOKEN_OUTPUT="$(docker exec "${GITEA_CONTAINER}" su git -c \
    "gitea admin user generate-access-token \
        --username ${GITEA_BOT_USER} \
        --token-name ${TOKEN_NAME} \
        --scopes 'write:repository,write:issue,write:user,read:user'")" \
    || die "failed to generate token"

# Gitea output format: "Access token was successfully created: <token>"
GITEA_TOKEN="$(echo "$TOKEN_OUTPUT" | awk -F': ' '/Access token/ {print $NF}')"
[ -n "$GITEA_TOKEN" ] || die "could not parse token from output: $TOKEN_OUTPUT"
log "token generated"

# ── 5. Write / update .env ────────────────────────────────────────────────
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    die "no .env file in current directory — run this script from the project root"
fi

update_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        # Replace existing value
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

update_env GITEA_URL "${GITEA_URL}"
update_env GITEA_API_URL "${GITEA_API_URL}"
update_env GITEA_TOKEN "${GITEA_TOKEN}"
update_env GITEA_OWNER "${GITEA_BOT_USER}"
update_env GITEA_REPO "${GITEA_REPO}"
update_env GITEA_BOT_USER "${GITEA_BOT_USER}"
update_env GITEA_BOT_PASSWORD "${GITEA_BOT_PASSWORD}"
log "updated .env with GITEA_* variables"

# ── 5a. Generate an Actions runner token for the act_runner container ─────
log "generating Gitea Actions runner token ..."
RUNNER_TOKEN_OUTPUT="$(docker exec "${GITEA_CONTAINER}" su git -c \
    'gitea actions generate-runner-token' 2>&1)" || true
# Token is a 40-char alphanum string; extract it from stdout
RUNNER_TOKEN="$(echo "$RUNNER_TOKEN_OUTPUT" | grep -oE '[a-zA-Z0-9]{40,}' | tail -1)"
if [ -n "$RUNNER_TOKEN" ]; then
    update_env GITEA_RUNNER_TOKEN "${RUNNER_TOKEN}"
    log "runner token generated — enable the trusted runner explicitly with: make gitea-runner"
else
    log "WARN: could not generate runner token (Actions may not be enabled, or gitea CLI changed)"
    log "      CI workflows will not run until you set GITEA_RUNNER_TOKEN manually"
fi

# ── 6. Create the project repo (idempotent) ───────────────────────────────
log "ensuring repo ${GITEA_BOT_USER}/${GITEA_REPO} exists ..."
REPO_STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token ${GITEA_TOKEN}" \
    "${GITEA_API_URL}/repos/${GITEA_BOT_USER}/${GITEA_REPO}")"

if [ "$REPO_STATUS" = "200" ]; then
    curl -sf -X PATCH \
        -H "Authorization: token ${GITEA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"private":true}' \
        "${GITEA_API_URL}/repos/${GITEA_BOT_USER}/${GITEA_REPO}" >/dev/null \
        || die "failed to ensure existing repo is private"
    log "repo already exists; ensured it is private"
else
    curl -sf -X POST \
        -H "Authorization: token ${GITEA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${GITEA_REPO}\",\"description\":\"auto-scaffolded project repo\",\"private\":true,\"default_branch\":\"main\",\"auto_init\":false}" \
        "${GITEA_API_URL}/user/repos" >/dev/null \
        || die "failed to create repo"
    log "created repo ${GITEA_BOT_USER}/${GITEA_REPO}"
fi

# ── 7. Add / update the 'gitea' git remote and push ──────────────────────
REMOTE_URL="http://${GITEA_BOT_USER}:${GITEA_TOKEN}@127.0.0.1:${GITEA_HTTP_PORT}/${GITEA_BOT_USER}/${GITEA_REPO}.git"

if git remote get-url gitea >/dev/null 2>&1; then
    git remote set-url gitea "${REMOTE_URL}"
    log "updated gitea remote URL"
else
    git remote add gitea "${REMOTE_URL}"
    log "added gitea remote"
fi

CURRENT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo main)"
log "pushing ${CURRENT_BRANCH} to gitea ..."
if git push gitea "${CURRENT_BRANCH}" 2>&1; then
    log "pushed ${CURRENT_BRANCH}"
else
    log "WARN: push failed — repo may not be empty, try: git push gitea ${CURRENT_BRANCH} --force (only on first bootstrap)"
fi

log ""
log "═══ gitea bootstrap complete ═══"
log "URL:   ${GITEA_URL}"
log "User:  ${GITEA_BOT_USER}"
log "Repo:  ${GITEA_BOT_USER}/${GITEA_REPO}"
log "Token: stored in .env as GITEA_TOKEN"
log ""
log "Next: the bot can now push dispatched branches and open PRs automatically."
log "Visit ${GITEA_URL} in your browser (login with the bot user or create another account)."
