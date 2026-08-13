#!/usr/bin/env bash
#
# Verify every secret <name> declares actually resolves in Vault.
#
# Prints variable names and pass/fail only — never a value, never a partial
# value, never a length. The point is to answer "will this project start?"
# without putting secrets in a terminal buffer, a CI log, or a screen share.
#
# Configuration is identical to vault/pull.sh (VAULT_ADDR, VAULT_ROLE,
# VAULT_KV_MOUNT, VAULT_CREDS_DIR, VAULT_TOKEN).
#
# Usage:
#   ./vault/check.sh           # check every mapped secret
#   ./vault/check.sh --diff    # also report which local .env values differ, BY NAME
#
# Exit codes:
#   0  every mapped secret resolves
#   1  one or more do not (or Vault is unreachable/sealed)
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
SHOW_DIFF=0
[[ "${1:-}" == "--diff" ]] && SHOW_DIFF=1

# die <message> [exit-code] — note "$1", not "$*": the exit code is an
# argument, not part of the message.
die() { printf '[vault] error: %s\n' "$1" >&2; exit "${2:-1}"; }

[[ -f "$SECRET_MAP" ]] || die "no $SECRET_MAP" 2

# vault/pull.sh does the authentication and fetching. Reusing it keeps exactly
# one implementation of "talk to Vault" in the project, so the two commands can
# never disagree about whether a secret resolves.
#
# --best-effort (which implies --stdout, so nothing is ever written) reports
# every variable in one pass instead of stopping at the first failure. A
# diagnostic that gives up on the first problem makes you run it once per
# broken secret.
errors="$(mktemp)"
trap 'rm -f "$errors"' EXIT

if ! fetched="$(./vault/pull.sh --best-effort 2>"$errors")"; then
    cat "$errors" >&2
    exit 1
fi

# Connection-level problems (sealed, unreachable, bad credentials) still abort
# inside pull.sh; what reaches here is per-secret detail worth showing.
grep -v '^\[vault\] authenticated' "$errors" >&2 || true

resolved=0
failed=0

printf '%-40s %s\n' "VARIABLE" "VAULT"
printf '%-40s %s\n' "----------------------------------------" "-----"

while IFS=$'\t' read -r var path field || [[ -n "${var:-}" ]]; do
    [[ -z "${var:-}" || "$var" == \#* ]] && continue
    if printf '%s' "$fetched" | grep -qE "^${var}="; then
        # A mapped key that resolves to the empty string is a configuration
        # bug, not a success: the field exists but was never populated.
        if printf '%s' "$fetched" | grep -qE "^${var}=$"; then
            printf '%-40s %s\n' "$var" "EMPTY"
            failed=$((failed + 1))
        else
            printf '%-40s %s\n' "$var" "ok"
            resolved=$((resolved + 1))
        fi
    else
        printf '%-40s %s\n' "$var" "MISSING"
        failed=$((failed + 1))
    fi
done < "$SECRET_MAP"

if (( SHOW_DIFF )); then
    printf '\n%-40s %s\n' "VARIABLE" "LOCAL .env vs VAULT"
    printf '%-40s %s\n' "----------------------------------------" "-------------------"
    if [[ ! -f "$ENV_FILE" ]]; then
        printf 'no %s — run: make secrets-pull\n' "$ENV_FILE"
    else
        while IFS= read -r line; do
            key="${line%%=*}"
            local_line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -n1 || true)"
            if [[ -z "$local_line" ]]; then
                printf '%-40s %s\n' "$key" "absent locally"
            elif [[ "$local_line" != "$line" ]]; then
                printf '%-40s %s\n' "$key" "DIFFERS"
            else
                printf '%-40s %s\n' "$key" "same"
            fi
        done <<< "$fetched"
    fi
fi

printf '\n%d resolved, %d failed\n' "$resolved" "$failed"
(( failed == 0 )) || exit 1
