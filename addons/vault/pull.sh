#!/usr/bin/env bash
#
# Pull <name>'s secrets from Vault into .env.
#
# Reads vault/secret-map.tsv (ENV_VAR <TAB> path <TAB> field), fetches each
# value, and writes .env with mode 0600. Values are never printed — not on
# success, not in an error, not under `set -x`.
#
# Configuration comes from the environment (or .env), never from a hardcoded
# path, so nothing operator-specific is ever written into a committed file:
#
#   VAULT_ADDR       Vault API address, e.g. http://127.0.0.1:8200   (required)
#   VAULT_ROLE       AppRole to authenticate as                       (required)
#   VAULT_KV_MOUNT   KV v2 mount name                          (default: kv)
#   VAULT_CREDS_DIR  Directory holding role-id/secret-id  (default: ~/.vault)
#   VAULT_TOKEN      Pre-obtained token; skips AppRole login    (optional)
#
# Usage:
#   ./vault/pull.sh              # write .env (refuses to clobber local edits)
#   FORCE=1 ./vault/pull.sh      # overwrite .env anyway
#   ./vault/pull.sh --stdout     # print to stdout instead (still no values in logs)
#
# Exit codes:
#   0  .env written
#   1  fetch failed — nothing written (fail-closed, never a partial .env)
#   2  configuration or usage error

set -euo pipefail

# A user's CDPATH makes `cd` print the directory it landed in, which would
# otherwise end up inside the command substitutions below and corrupt every
# path derived from them. Clearing it is local to this script's shell.
CDPATH=''
umask 077

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SECRET_MAP="vault/secret-map.tsv"
ENV_FILE=".env"
TO_STDOUT=0
BEST_EFFORT=0
for arg in "$@"; do
    case "$arg" in
        --stdout) TO_STDOUT=1 ;;
        # Emit an empty value for anything that does not resolve and keep
        # going, instead of failing at the first one. Only ever combined with
        # --stdout, so it can never write a partial .env — it exists so
        # check.sh can report every variable's status in one pass, which is
        # the whole point of a diagnostic.
        --best-effort) BEST_EFFORT=1; TO_STDOUT=1 ;;
    esac
done

msg()  { printf '[vault] %s\n' "$*" >&2; }
# die <message> [exit-code] — note "$1", not "$*": the exit code is an
# argument, not part of the message.
die()  { printf '[vault] error: %s\n' "$1" >&2; exit "${2:-1}"; }

# Load VAULT_* from .env if present, without exporting anything else.
if [[ -f "$ENV_FILE" ]]; then
    while IFS='=' read -r key value; do
        case "$key" in
            VAULT_ADDR|VAULT_ROLE|VAULT_KV_MOUNT|VAULT_CREDS_DIR)
                [[ -n "${!key:-}" ]] || export "$key=$value"
                ;;
        esac
    done < <(grep -E '^VAULT_[A-Z_]+=' "$ENV_FILE" 2>/dev/null || true)
fi

VAULT_KV_MOUNT="${VAULT_KV_MOUNT:-kv}"
VAULT_CREDS_DIR="${VAULT_CREDS_DIR:-$HOME/.vault}"

command -v curl >/dev/null 2>&1 || die "curl is required" 2
command -v python3 >/dev/null 2>&1 || die "python3 is required (JSON parsing)" 2
[[ -f "$SECRET_MAP" ]] || die "no $SECRET_MAP — nothing to pull" 2
[[ -n "${VAULT_ADDR:-}" ]] || die "VAULT_ADDR is not set (see vault/README.md)" 2

# ── authenticate ───────────────────────────────────────────────────────────
# Fail-closed, and distinguish the two failure modes that have different
# fixes: a sealed Vault needs unsealing, an unreachable one needs a corrected
# VAULT_ADDR. Reporting "login failed" for both wastes the operator's time.

if [[ -z "${VAULT_TOKEN:-}" ]]; then
    [[ -n "${VAULT_ROLE:-}" ]] || die "VAULT_ROLE is not set and no VAULT_TOKEN provided" 2

    role_dir="$VAULT_CREDS_DIR/$VAULT_ROLE"
    [[ -r "$role_dir/role-id" && -r "$role_dir/secret-id" ]] \
        || die "missing AppRole credentials in $role_dir (see vault/README.md)" 2

    health="$(curl -fsS --max-time 10 "$VAULT_ADDR/v1/sys/health" 2>/dev/null || true)"
    if [[ -z "$health" ]]; then
        die "Vault unreachable at $VAULT_ADDR — check VAULT_ADDR and that the server is running"
    fi
    if printf '%s' "$health" | grep -q '"sealed":true'; then
        die "Vault at $VAULT_ADDR is sealed — unseal it, then retry"
    fi

    login_payload="$(python3 -c '
import json, sys
print(json.dumps({"role_id": open(sys.argv[1]).read().strip(),
                  "secret_id": open(sys.argv[2]).read().strip()}))
' "$role_dir/role-id" "$role_dir/secret-id")"

    VAULT_TOKEN="$(
        curl -fsS --max-time 10 \
            --request POST \
            --data "$login_payload" \
            "$VAULT_ADDR/v1/auth/approle/login" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])' \
            2>/dev/null || true
    )"
    [[ -n "$VAULT_TOKEN" ]] || die "AppRole login failed for role '$VAULT_ROLE' (expired secret-id?)"
    msg "authenticated as AppRole '$VAULT_ROLE'"
fi

# ── fetch ──────────────────────────────────────────────────────────────────
# Build the whole file in memory first. A partial .env is worse than none:
# the service starts, half-configured, and fails somewhere unrelated.

_t_start=$(date +%s%3N 2>/dev/null || echo 0)
rendered=""
count=0
declare -A path_cache=()

while IFS=$'\t' read -r var path field || [[ -n "${var:-}" ]]; do
    [[ -z "${var:-}" || "$var" == \#* ]] && continue
    [[ -n "${path:-}" && -n "${field:-}" ]] \
        || die "malformed line in $SECRET_MAP: expected 3 tab-separated columns for '$var'" 2

    if [[ -z "${path_cache[$path]+set}" ]]; then
        response="$(
            curl -fsS --max-time 15 \
                --header "X-Vault-Token: $VAULT_TOKEN" \
                "$VAULT_ADDR/v1/$VAULT_KV_MOUNT/data/$path" 2>/dev/null || true
        )"
        if [[ -z "$response" ]]; then
            (( BEST_EFFORT )) || die "cannot read $VAULT_KV_MOUNT/$path (missing, or role lacks read capability)"
            msg "cannot read $VAULT_KV_MOUNT/$path (missing, or role lacks read capability)"
        fi
        path_cache[$path]="$response"
    fi

    if [[ -n "${path_cache[$path]}" ]]; then
        value="$(
            printf '%s' "${path_cache[$path]}" \
            | python3 -c '
import json, sys
field = sys.argv[1]
data = json.load(sys.stdin)["data"]["data"]
if field not in data:
    sys.exit(3)
sys.stdout.write(str(data[field]))
' "$field" 2>/dev/null
        )" || {
            (( BEST_EFFORT )) || die "field '$field' not present at $VAULT_KV_MOUNT/$path (required by $var)"
            msg "field '$field' not present at $VAULT_KV_MOUNT/$path (required by $var)"
            value=""
        }
    else
        value=""
    fi

    rendered+="$var=$value"$'\n'
    count=$((count + 1))
done < "$SECRET_MAP"

_t_end=$(date +%s%3N 2>/dev/null || echo 0)
msg "[<name>-perf] phase=vault_fetch duration_ms=$((_t_end - _t_start)) secrets=$count"

(( count > 0 )) || die "no secrets declared in $SECRET_MAP" 2

# ── write ──────────────────────────────────────────────────────────────────

if (( TO_STDOUT )); then
    printf '%s' "$rendered"
    exit 0
fi

if [[ -f "$ENV_FILE" && "${FORCE:-0}" != "1" ]]; then
    # Only refuse when a mapped key already has a different value — an
    # unchanged or absent key is not a local edit worth protecting.
    conflicts=""
    while IFS= read -r line; do
        key="${line%%=*}"
        existing="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -n1 || true)"
        if [[ -n "$existing" && "$existing" != "$line" ]]; then
            conflicts+="  $key"$'\n'
        fi
    done <<< "$rendered"

    if [[ -n "$conflicts" ]]; then
        printf '[vault] error: %s already has different values for:\n%s' "$ENV_FILE" "$conflicts" >&2
        printf '[vault] re-run with FORCE=1 to overwrite, or reconcile by hand.\n' >&2
        exit 1
    fi
fi

# Preserve any non-mapped lines already in .env (ports, feature flags, add-on
# wiring); replace only what Vault owns.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"

if [[ -f "$ENV_FILE" ]]; then
    mapped_keys="$(printf '%s' "$rendered" | cut -d= -f1 | paste -sd'|' -)"
    grep -vE "^(${mapped_keys})=" "$ENV_FILE" > "$tmp" || true
    printf '\n# ── pulled from Vault by vault/pull.sh — do not edit by hand ──\n' >> "$tmp"
fi
printf '%s' "$rendered" >> "$tmp"

mv "$tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
trap - EXIT

msg "wrote $count secret(s) to $ENV_FILE (mode 0600)"
