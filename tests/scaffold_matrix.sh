#!/usr/bin/env bash
set -euo pipefail

# A user's CDPATH makes `cd` print the directory it landed in, which would
# otherwise end up inside the command substitutions below and corrupt every
# path derived from them. Clearing it is local to this script's shell.
CDPATH=''

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---quick}"

case "$MODE" in
    --quick|--full) shift || true ;;
    *)
        echo "usage: $0 [--quick|--full] [shape ...]" >&2
        exit 2
        ;;
esac

# Optional shape filter. A --full run builds and exercises every variant in
# Docker, which takes tens of minutes; naming shapes narrows it to those, so a
# fix for one shape can be verified without re-running the ones that already
# passed. No names means every shape, which is what CI does.
ONLY_SHAPES=("$@")
wanted() {
    local shape="$1" want
    (( ${#ONLY_SHAPES[@]} )) || return 0
    for want in "${ONLY_SHAPES[@]}"; do
        [[ "$shape" == "$want" ]] && return 0
    done
    return 1
}

for cmd in git docker make; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "missing required command: $cmd" >&2
        exit 1
    }
done
docker compose version >/dev/null 2>&1 || {
    echo "Docker Compose v2 is required" >&2
    exit 1
}
if [[ "$MODE" == "--full" ]]; then
    command -v curl >/dev/null 2>&1 || {
        echo "missing required command: curl" >&2
        exit 1
    }
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/yala-scaffold-matrix.XXXXXX")"
RUN_ID="$(basename "$TMP_ROOT" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9' | tail -c 9)"
PORT_BASE=$((20000 + RANDOM % 20000))
cleanup() {
    local project
    for project in "$TMP_ROOT"/projects/*; do
        [[ -d "$project" ]] || continue
        docker compose -f "$project/docker-compose.yml" down --remove-orphans >/dev/null 2>&1 || true
        docker image rm "$(basename "$project")-test" >/dev/null 2>&1 || true
        docker image rm "$(basename "$project"):latest" >/dev/null 2>&1 || true
    done
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$TMP_ROOT/projects"


variants=(
    "service python"
    "service node"
    "worker python"
    "worker node"
    "analysis python"
    "backtest python"
    "report python"
    "notebook python"
    "pipeline python"
    "webapp node"
    "image python"
    "tui go"
    "model python"
    "mcp python"
    "mcp node"
    "scraper python"
    "bridge python"
    "cli go"
    "agent python"
    "stream python"
    "browser python"
    "game python"
    "audio python"
)

# Some Docker daemons (user-namespace remapping, rootless, SELinux) cannot
# write to a bind mount owned by the invoking user. Generated projects diagnose
# this in `make doctor` and tell the operator to opt the service out in
# docker-compose.override.yml. The matrix has to do the same thing to itself,
# or --full cannot run at all on such a host.
NEEDS_USERNS_HOST=0
detect_bind_mount_writability() {
    local probe result
    probe="$(mktemp -d)"
    if docker run --rm --user "$(id -u):$(id -g)" -v "$probe":/probe \
        alpine:3.21 sh -c 'touch /probe/.w' >/dev/null 2>&1; then
        result=0
    else
        result=1
    fi
    rm -rf "$probe"
    return "$result"
}

# Write the same override `make doctor` recommends, so the full run exercises
# the documented fix rather than working around it some other way.
apply_userns_override() {
    local project="$1" name
    name="$(basename "$project")"
    (( NEEDS_USERNS_HOST )) || return 0
    cat > "$project/docker-compose.override.yml" <<OVERRIDE
services:
  ${name}:
    userns_mode: host
OVERRIDE
}

assert_absent() {
    local path="$1"
    [[ ! -e "$path" ]] || {
        echo "unexpected path exists: $path" >&2
        return 1
    }
}

if [[ "$MODE" == "--full" ]]; then
    if detect_bind_mount_writability; then
        echo "bind mounts are writable by uid $(id -u) — no compose override needed"
    else
        NEEDS_USERNS_HOST=1
        echo "NOTE: this daemon remaps user namespaces, so a bind mount owned by"
        echo "      uid $(id -u) is not writable from a container. Each generated"
        echo "      project gets the same docker-compose.override.yml that"
        echo "      'make doctor' recommends (userns_mode: host)."
    fi
fi

assert_security_defaults() {
    local project="$1"
    local config
    local runtime_user
    config="$(docker compose -f "$project/docker-compose.yml" config)"
    grep -q "read_only: true" <<<"$config"
    grep -q "no-new-privileges" <<<"$config"
    grep -A2 "cap_drop:" <<<"$config" | grep -q "ALL"
    grep -q "pids_limit:" <<<"$config"
    if grep -q "published:" <<<"$config"; then
        grep -q "host_ip: 127.0.0.1" <<<"$config"
        ! grep -q "host_ip: 0.0.0.0" <<<"$config"
    fi
    ! grep -Eq "privileged: true|network_mode: host|/var/run/docker.sock" <<<"$config"
    runtime_user="$(grep -E '^USER ' "$project/Dockerfile" | tail -1 | awk '{print $2}')"
    [[ -n "$runtime_user" && "$runtime_user" != "root" && "$runtime_user" != "0" ]]
    grep -q "APP_UID:" "$project/docker-compose.yml"
    grep -q "APP_GID:" "$project/docker-compose.yml"
}

run_full_validation() {
    local project="$1"
    local shape="$2"
    local port="$3"
    local metric_output
    local status

    make -C "$project" setup
    make -C "$project" test
    make -C "$project" lint
    make -C "$project" typecheck
    if [[ "$shape" == "tui" ]]; then
        docker compose -f "$project/docker-compose.yml" run --rm "$(basename "$project")" --demo
    elif [[ "$shape" == "mcp" ]]; then
        # An MCP server talks JSON-RPC over stdio and is spawned by its client,
        # so its `make run` is deliberately a foreground `compose up` that never
        # returns. `make qa` starts a server itself and drives the real
        # protocol, which is the stronger check anyway.
        :
    else
        # A `run` that never returns would otherwise stall the whole suite with
        # no output — the one failure mode worse than a red test.
        timeout 300 make -C "$project" run || {
            status=$?
            [[ $status -eq 124 ]] && echo "make run did not return within 300s for $shape" >&2
            exit "$status"
        }
    fi

    case "$shape" in
        analysis|backtest|report|pipeline)
            ;;
        tui)
            ;;
        *)
            sleep 5
            ;;
    esac

    if [[ "$shape" == "model" ]]; then
        # No served model in CI, so no eval report — the gate is SUPPOSED to
        # fail here. Assert that it fails for the right reason rather than
        # skipping it, which would let a gate that never fails go unnoticed.
        if make -C "$project" qa >"$TMP_ROOT/model-qa.log" 2>&1; then
            echo "model gate passed with no evaluation — it must not" >&2
            exit 1
        fi
        grep -q '"eval_report"' "$TMP_ROOT/model-qa.log"
    else
        make -C "$project" qa
    fi
    metric_output="$(make --no-print-directory -s -C "$project" metric)"
    tail -n 1 <<<"$metric_output" | grep -Eq '^-?[0-9]+([.][0-9]+)?$'

    if [[ "$shape" == "notebook" ]]; then
        local args
        local auth_status
        local unauth_status
        docker compose -f "$project/docker-compose.yml" down --remove-orphans >/dev/null
        JUPYTER_TOKEN=matrix-secret \
            docker compose -f "$project/docker-compose.yml" up -d >/dev/null
        for _ in {1..30}; do
            unauth_status="$(curl -sS -o /dev/null -w '%{http_code}' \
                "http://127.0.0.1:$port/api/contents" 2>/dev/null || true)"
            [[ "$unauth_status" != "000" ]] && break
            sleep 1
        done
        auth_status="$(curl -sS -o /dev/null -w '%{http_code}' \
            "http://127.0.0.1:$port/api/contents?token=matrix-secret")"
        args="$(docker inspect --format '{{json .Config.Cmd}}' "$(basename "$project")")"
        [[ "$unauth_status" == "403" ]]
        [[ "$auth_status" == "200" ]]
        [[ "$args" != *matrix-secret* ]]
    fi

    if [[ "$shape" == "image" ]]; then
        grep -q '@app.post("/api/transform")' "$project/app.py"
        grep -q "MAX_UPLOAD_BYTES" "$project/app.py"
        grep -q "Image.MAX_IMAGE_PIXELS" "$project/app.py"
        grep -q "python-multipart==" "$project/requirements.txt"
        grep -q "Pillow==" "$project/requirements.txt"
    fi

    if [[ "$shape" == "model" ]]; then
        # The whole no-GPU half of the pipeline must work: build a corpus,
        # validate it, and have the gate refuse an unevaluated model.
        make -C "$project" dataset
        make -C "$project" preflight
        # qa runs above and must FAIL here, because nothing has been evaluated.
        # That is the point of the gate — an unmeasured model is not shippable.
        :
    fi

    if [[ "$shape" == "tui" ]]; then
        [[ -f "$project/go.mod" ]]
        [[ -f "$project/go.sum" ]]
        [[ -f "$project/cmd/tui/main.go" ]]
        grep -q "bubbletea" "$project/go.mod"
        grep -q "docker compose run --rm $name" "$project/Makefile"
    fi

    make -C "$project" clean
}

# A filter that matches nothing would report a clean run having tested nothing,
# so a name that is not a real shape is an error rather than an empty result.
if (( ${#ONLY_SHAPES[@]} )); then
    known=" $(printf '%s\n' "${variants[@]}" | cut -d' ' -f1 | sort -u | tr '\n' ' ')"
    for want in "${ONLY_SHAPES[@]}"; do
        [[ "$known" == *" $want "* ]] || {
            echo "unknown shape: $want" >&2
            echo "known shapes:$known" >&2
            exit 2
        }
    done
    echo "filter: only ${ONLY_SHAPES[*]}"
fi

index=0
for variant in "${variants[@]}"; do
    read -r shape lang <<<"$variant"
    index=$((index + 1))
    wanted "$shape" || continue
    name="matrix-${RUN_ID}-${shape}-${lang}"
    port=$((PORT_BASE + index))
    project="$TMP_ROOT/projects/$name"

    "$ROOT/yala.sh" "$name" \
        --type "$shape" \
        --lang "$lang" \
        --port "$port" \
        --into "$TMP_ROOT/projects" >/dev/null

    git -C "$project" rev-parse --verify HEAD >/dev/null
    [[ -f "$project/.env" ]]
    [[ -f "$project/.env.example" ]]
    [[ -f "$project/Makefile" ]]
    docker compose -f "$project/docker-compose.yml" config --quiet
    assert_security_defaults "$project"

    assert_absent "$project/bot"
    assert_absent "$project/rag"
    assert_absent "$project/gitea"
    assert_absent "$project/vault"
    assert_absent "$project/monitor"
    assert_absent "$project/review"
    assert_absent "$project/scripts/kpi_collector.py"
    assert_absent "$project/scripts/kpi_dashboard.py"

    # ── Drift checks ship, and actually work, in every shape ──────────────
    [[ -f "$project/scripts/check_locales.py" ]]
    [[ -f "$project/scripts/check_env.py" ]]
    [[ -f "$project/scripts/check_root_clutter.py" ]]
    [[ -f "$project/scripts/refresh_agents.py" ]]
    [[ -f "$project/scripts/bench_run.py" ]]
    [[ -f "$project/scripts/bench_compare.py" ]]
    [[ -f "$project/bench/benchmarks.json" ]]
    [[ -f "$project/.pre-commit-config.yaml" ]]
    [[ -d "$project/docs/plans" && -d "$project/docs/specs" ]]
    [[ -d "$project/scratch" ]]
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$project/bench/benchmarks.json"

    # scratch/ must be ignored, or the directory that exists to keep debris out
    # of the repo becomes the debris.
    git -C "$project" check-ignore -q scratch \
        || { echo "scratch/ is not gitignored in $project" >&2; exit 1; }

    ( cd "$project" && python3 scripts/check_locales.py >/dev/null )
    ( cd "$project" && python3 scripts/check_root_clutter.py >/dev/null )

    # A desynchronised locale must FAIL. A check that cannot fail is decoration.
    python3 - "$project" <<'PYEOF'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1]) / "locales" / "es.json"
data = json.loads(path.read_text(encoding="utf-8"))
data["nav"].pop("about", None)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF
    if ( cd "$project" && python3 scripts/check_locales.py >/dev/null 2>&1 ); then
        echo "locale drift went undetected in $project" >&2
        exit 1
    fi
    git -C "$project" checkout -- locales/es.json

    # Root clutter must FAIL too.
    touch "$project/tmp_matrix_probe.py"
    git -C "$project" add -A >/dev/null 2>&1 || true
    if ( cd "$project" && python3 scripts/check_root_clutter.py >/dev/null 2>&1 ); then
        echo "root clutter went undetected in $project" >&2
        exit 1
    fi
    git -C "$project" rm -q --cached tmp_matrix_probe.py >/dev/null 2>&1 || true
    rm -f "$project/tmp_matrix_probe.py"

    # ── Typed config boundary ────────────────────────────────────────────
    grep -q "scaffold:env:start" "$project/.env.example"
    grep -q "scaffold:env:end" "$project/.env.example"
    grep -q "APP_VERSION=" "$project/.env.example"
    # Version identity reaches the image.
    grep -q "ARG VERSION" "$project/Dockerfile"
    grep -q "APP_VERSION" "$project/Dockerfile"
    grep -q "VERSION:" "$project/docker-compose.yml"

    # AGENTS.md must carry the markers that make it refreshable.
    grep -q "<!-- scaffold:start -->" "$project/AGENTS.md"
    grep -q "<!-- scaffold:end -->" "$project/AGENTS.md"

    case "$lang" in
        python)
            [[ -f "$project/config.py" ]]
            ( cd "$project" && python3 config.py --check >/dev/null )
            ( cd "$project" && python3 scripts/check_env.py >/dev/null )
            ;;
        node)
            [[ -f "$project/src/config.js" ]]
            ;;
        go)
            [[ -f "$project/internal/config/config.go" ]]
            [[ -f "$project/cmd/envtool/main.go" ]]
            ;;
    esac

    case "$shape" in
        webapp|image|service|notebook)
            [[ -f "$project/scripts/check_styles.py" ]]
            ( cd "$project" && python3 scripts/check_styles.py >/dev/null )
            ;;
        *)
            assert_absent "$project/scripts/check_styles.py"
            ;;
    esac

    if (( index == 1 )); then
        if make -C "$project" reindex >"$TMP_ROOT/addon-disabled.log" 2>&1; then
            echo "disabled RAG target unexpectedly succeeded" >&2
            exit 1
        fi
        grep -q "RAG add-on not enabled" "$TMP_ROOT/addon-disabled.log"
    fi

    case "$lang" in
        node)
            [[ -f "$project/qa_check.js" ]]
            assert_absent "$project/qa_check.py"
            grep -q "make qa" "$project/README.md"
            ! grep -q "python3 qa_check.py" "$project/README.md"
            [[ -f "$project/package-lock.json" ]]
            ;;
        go)
            if [[ "$shape" == "cli" ]]; then
                [[ -f "$project/cmd/cli/main.go" ]]
                [[ -f "$project/testdata/count.golden" ]]
            else
                [[ -f "$project/qa_check.go" ]]
            fi
            assert_absent "$project/qa_check.py"
            assert_absent "$project/qa_check.js"
            ;;
        *)
            [[ -f "$project/qa_check.py" ]]
            assert_absent "$project/qa_check.js"
            ;;
    esac

    if [[ "$shape" == "notebook" ]]; then
        [[ -f "$project/jupyter_server_config.py" ]]
        grep -q 'JUPYTER_TOKEN: "${JUPYTER_TOKEN:-}"' "$project/docker-compose.yml"
        grep -q '^# JUPYTER_TOKEN=$' "$project/.env.example"
        grep -q 'c.IdentityProvider.token = os.environ.get("JUPYTER_TOKEN", "")' \
            "$project/jupyter_server_config.py"
        grep -q -- '--config=/app/jupyter_server_config.py' "$project/Dockerfile"
        ! grep -Eq -- '--(ServerApp|IdentityProvider)\.token=' "$project/Dockerfile"
        grep -q 'reverse-proxy exposure with an empty token grants' "$project/README.md"
        config="$(docker compose -f "$project/docker-compose.yml" config)"
        grep -q 'JUPYTER_TOKEN: ""' <<<"$config"
        config="$(JUPYTER_TOKEN=matrix-secret docker compose -f "$project/docker-compose.yml" config)"
        grep -q 'JUPYTER_TOKEN: matrix-secret' <<<"$config"
    fi

    if grep -R -E "<name>|<PORT>|<shape>|<lang>|<YEAR>|<DATE>|<COPYRIGHT_HOLDER>|<HOST_UID>|<HOST_GID>" \
        "$project" --exclude-dir=.git --exclude=CODE_REVIEW.md >/dev/null; then
        echo "unresolved scaffold placeholder in $project" >&2
        exit 1
    fi

    if [[ "$MODE" == "--full" ]]; then
        apply_userns_override "$project"
        run_full_validation "$project" "$shape" "$port"
    fi

    echo "ok: $shape/$lang"
done

# Negative argument and destination cases must fail before creating a project.
if "$ROOT/yala.sh" invalid-port --port 70000 --into "$TMP_ROOT/projects" >/dev/null 2>&1; then
    echo "invalid port unexpectedly accepted" >&2
    exit 1
fi
if "$ROOT/yala.sh" missing-value --port >/dev/null 2>&1; then
    echo "missing flag value unexpectedly accepted" >&2
    exit 1
fi
if "$ROOT/yala.sh" wrong-license --license Apache-2.0 --into "$TMP_ROOT/projects" >/dev/null 2>&1; then
    echo "unsupported license unexpectedly accepted" >&2
    exit 1
fi
mkdir -p "$TMP_ROOT/projects/existing-project"
if "$ROOT/yala.sh" existing-project --into "$TMP_ROOT/projects" >/dev/null 2>&1; then
    echo "existing destination unexpectedly accepted" >&2
    exit 1
fi

"$ROOT/yala.sh" escaped-holder --type service --lang node \
    --holder "R&D | Labs" --into "$TMP_ROOT/projects" >/dev/null
grep -q "Copyright (c).*R&D | Labs" "$TMP_ROOT/projects/escaped-holder/LICENSE"

# Git fallback identity must create a commit without writing any Git config.
mkdir -p "$TMP_ROOT/empty-home"
HOME="$TMP_ROOT/empty-home" GIT_CONFIG_NOSYSTEM=1 \
    "$ROOT/yala.sh" fallback-identity --type service --lang node \
    --into "$TMP_ROOT/projects" >/dev/null
git -C "$TMP_ROOT/projects/fallback-identity" rev-parse --verify HEAD >/dev/null
[[ ! -f "$TMP_ROOT/empty-home/.gitconfig" ]]
[[ ! -f "$TMP_ROOT/projects/fallback-identity/.git/config.lock" ]]

# Optional files should be present only when explicitly requested.
"$ROOT/yala.sh" matrix-addons --type service --lang python --with-all \
    --into "$TMP_ROOT/projects" >/dev/null
for path in \
    bot \
    rag \
    gitea \
    vault \
    monitor \
    review \
    scripts/kpi_collector.py \
    scripts/kpi_dashboard.py; do
    [[ -e "$TMP_ROOT/projects/matrix-addons/$path" ]]
done

# ── Code review add-on ────────────────────────────────────────────────────
review_project="$TMP_ROOT/projects/matrix-addons"
# A project scaffolded WITHOUT the add-ons, for asserting the gated targets
# refuse cleanly. Defined here because the review checks below run first.
plain_project="$TMP_ROOT/projects/escaped-holder"
[[ -x "$review_project/review/gate.py" ]]
[[ -x "$review_project/review/run.sh" ]]
[[ -x "$review_project/review/fetch_poster.sh" ]]
[[ -f "$review_project/review/ci.gitlab-ci.yml" ]]

# The reviewer version must be pinned, not floating: a `latest` install makes
# today's review disagree with yesterday's for reasons unrelated to the code.
grep -qE 'OCR_VERSION[:=] *"?[0-9]+\.[0-9]+' "$review_project/review/ci.gitlab-ci.yml"
grep -qE '^OCR_VERSION \?= [0-9]+\.[0-9]+' "$review_project/Makefile"
! grep -q 'open-code-review@latest' "$review_project/review/ci.gitlab-ci.yml"

# Fetched third-party code must never be committed. Assert on a path INSIDE
# each directory: a trailing-slash pattern only matches a directory that
# already exists, and neither is created until a review actually runs.
git -C "$review_project" check-ignore -q review/vendor/post_review.py \
    || { echo "review/vendor/ is not gitignored" >&2; exit 1; }
git -C "$review_project" check-ignore -q .ocr/result.json \
    || { echo ".ocr/ is not gitignored" >&2; exit 1; }

# The gate must summarise, and must actually fail above its threshold — a
# gate that cannot fail is theatre.
mkdir -p "$review_project/.ocr"
cat > "$review_project/.ocr/matrix.json" <<'JSON'
{"comments":[
 {"path":"a.py","start_line":1,"end_line":1,"severity":"critical","category":"security","content":"boom"},
 {"path":"b.py","start_line":2,"end_line":2,"severity":"low","category":"style","content":"nit"},
 {"path":"c.py","start_line":3,"end_line":3,"severity":"from-the-future","category":"other","content":"?"}
]}
JSON
if ( cd "$review_project" && python3 review/gate.py .ocr/matrix.json >/dev/null 2>&1 ); then
    echo "review gate did not fail on a critical finding" >&2
    exit 1
fi
( cd "$review_project" && python3 review/gate.py .ocr/matrix.json --fail-on none >/dev/null )
# An unrecognised severity must rank high, not slip through as low.
if ( cd "$review_project" && python3 review/gate.py .ocr/matrix.json --fail-on high >/dev/null 2>&1 ); then
    echo "review gate let an unknown severity bypass the threshold" >&2
    exit 1
fi
# A crashed `ocr review` leaves unparseable output; that must be exit 2, not
# a silent pass.
echo 'not json' > "$review_project/.ocr/bad.json"
# `set -e` would abort on the non-zero exit before it could be inspected, so
# capture it rather than letting the subshell's status escape.
gate_rc=0
( cd "$review_project" && python3 review/gate.py .ocr/bad.json >/dev/null 2>&1 ) || gate_rc=$?
[[ "$gate_rc" -eq 2 ]] \
    || { echo "review gate mishandled unparseable output (rc=$gate_rc, want 2)" >&2; exit 1; }
rm -rf "$review_project/.ocr"

# Gated Make target must refuse cleanly when the add-on is absent.
if make -C "$plain_project" code-review >"$TMP_ROOT/review-disabled.log" 2>&1; then
    echo "disabled review target unexpectedly succeeded" >&2
    exit 1
fi
grep -q "review add-on not enabled" "$TMP_ROOT/review-disabled.log"

# ── Vault add-on ──────────────────────────────────────────────────────────
vault_project="$TMP_ROOT/projects/matrix-addons"
[[ -x "$vault_project/vault/pull.sh" ]]
[[ -x "$vault_project/vault/check.sh" ]]
[[ -f "$vault_project/vault/secret-map.tsv" ]]

# secret-map.tsv is committed on purpose (names and paths, never values), so
# it must NOT be ignored — while credential material must be.
git -C "$vault_project" check-ignore -q vault/secret-map.tsv && {
    echo "vault/secret-map.tsv must be committed, not ignored" >&2
    exit 1
}
git -C "$vault_project" check-ignore -q vault/.token \
    || { echo "vault/.token is not gitignored" >&2; exit 1; }

# No absolute operator path may reach a committed file. This add-on is the
# single most likely thing in the kit to reintroduce one.
if grep -rqE '/home/[a-z0-9_-]+/|/Users/[a-z0-9_-]+/' \
    "$vault_project/vault" 2>/dev/null; then
    echo "absolute operator path leaked into vault/ add-on" >&2
    exit 1
fi

# Fail closed: no VAULT_ADDR must write nothing and exit non-zero.
cp "$vault_project/.env" "$TMP_ROOT/vault-env-before"
if ( cd "$vault_project" && env -u VAULT_ADDR -u VAULT_TOKEN ./vault/pull.sh \
        >"$TMP_ROOT/vault-pull.log" 2>&1 ); then
    echo "vault pull.sh succeeded with no VAULT_ADDR" >&2
    exit 1
fi
grep -q "VAULT_ADDR is not set" "$TMP_ROOT/vault-pull.log"
cmp -s "$vault_project/.env" "$TMP_ROOT/vault-env-before" \
    || { echo "vault pull.sh modified .env on failure" >&2; exit 1; }

# Unreachable Vault: distinct, actionable message; still writes nothing.
mkdir -p "$TMP_ROOT/fake-vault-creds/probe"
echo fake-role > "$TMP_ROOT/fake-vault-creds/probe/role-id"
echo fake-secret > "$TMP_ROOT/fake-vault-creds/probe/secret-id"
if ( cd "$vault_project" && VAULT_ADDR=http://127.0.0.1:59999 VAULT_ROLE=probe \
        VAULT_CREDS_DIR="$TMP_ROOT/fake-vault-creds" ./vault/pull.sh \
        >"$TMP_ROOT/vault-unreachable.log" 2>&1 ); then
    echo "vault pull.sh succeeded against an unreachable server" >&2
    exit 1
fi
grep -q "unreachable" "$TMP_ROOT/vault-unreachable.log"
cmp -s "$vault_project/.env" "$TMP_ROOT/vault-env-before" \
    || { echo "vault pull.sh modified .env when Vault was unreachable" >&2; exit 1; }

# Gated Make targets must refuse cleanly when the add-on is absent.
if make -C "$plain_project" secrets-pull >"$TMP_ROOT/vault-disabled.log" 2>&1; then
    echo "disabled Vault target unexpectedly succeeded" >&2
    exit 1
fi
grep -q "Vault add-on not enabled" "$TMP_ROOT/vault-disabled.log"
# ── RAG add-on is self-sufficient ─────────────────────────────────────────
# It is documented as independent of the bot, so it must be usable without it.
"$ROOT/yala.sh" matrix-ragonly --type service --lang python --with-rag \
    --into "$TMP_ROOT/projects" >/dev/null
rag_project="$TMP_ROOT/projects/matrix-ragonly"
assert_absent "$rag_project/bot"
( cd "$rag_project" && python3 rag/index.py >/dev/null 2>&1 )
# An index with no read path is a write-only database.
( cd "$rag_project" && python3 rag/index.py --search "health" >/dev/null 2>&1 ) \
    || { echo "rag add-on cannot search its own index without the bot" >&2; exit 1; }
# A missing index must be distinguishable from an empty result.
mv "$rag_project/data/rag.sqlite" "$TMP_ROOT/rag.bak"
rag_rc=0
( cd "$rag_project" && python3 rag/index.py --search "x" >/dev/null 2>&1 ) || rag_rc=$?
[[ "$rag_rc" -ne 0 ]] || { echo "searching a missing rag index reported success" >&2; exit 1; }
mv "$TMP_ROOT/rag.bak" "$rag_project/data/rag.sqlite"

# ── Bot add-on refuses rather than crash-looping ──────────────────────────
# `docker compose up -d` exits 0 for a container that immediately dies, so the
# target must verify the bot is actually alive.
if make -C "$TMP_ROOT/projects/matrix-addons" bot >"$TMP_ROOT/bot-start.log" 2>&1; then
    echo "make bot reported success with no IRC_SERVER configured" >&2
    exit 1
fi
grep -q "IRC_SERVER is not set" "$TMP_ROOT/bot-start.log"

# The offline preflight must run and report what is missing.
make -C "$TMP_ROOT/projects/matrix-addons" bot-check >"$TMP_ROOT/bot-check.log" 2>&1 || true
grep -q "tools loaded" "$TMP_ROOT/bot-check.log"

# A tool whose add-on is absent must not be advertised to the model.
"$ROOT/yala.sh" matrix-botonly --type service --lang python --with-bot \
    --into "$TMP_ROOT/projects" >/dev/null
make -C "$TMP_ROOT/projects/matrix-botonly" bot-check >"$TMP_ROOT/botonly.log" 2>&1 || true
grep -q "tool local_rag skipped" "$TMP_ROOT/botonly.log" \
    || { echo "local_rag was advertised without the RAG add-on installed" >&2; exit 1; }

# The bot must only offer tools a new user can actually reach, and must not
# ship modules nothing registers.
python3 "$ROOT/tests/assert_bot_tools.py" "$TMP_ROOT/projects/matrix-addons/bot"

grep -q "read_only: true" "$TMP_ROOT/projects/matrix-addons/bot/docker-compose.bot.yml"
grep -q "cap_drop:" "$TMP_ROOT/projects/matrix-addons/bot/docker-compose.bot.yml"
grep -q "no-new-privileges:true" "$TMP_ROOT/projects/matrix-addons/bot/docker-compose.bot.yml"
grep -A3 "profiles:" "$TMP_ROOT/projects/matrix-addons/gitea/docker-compose.gitea.yml" |
    grep -q "ci-runner"
grep -q "GITEA__service__REQUIRE_SIGNIN_VIEW=true" \
    "$TMP_ROOT/projects/matrix-addons/gitea/docker-compose.gitea.yml"
grep -q "http://127.0.0.1:3000/api/healthz" \
    "$TMP_ROOT/projects/matrix-addons/gitea/docker-compose.gitea.yml"
grep -Fq '"private":true' "$TMP_ROOT/projects/matrix-addons/gitea/bootstrap.sh"
grep -Fq '\"private\":true' "$TMP_ROOT/projects/matrix-addons/gitea/bootstrap.sh"
! grep -Fq '"private":false' "$TMP_ROOT/projects/matrix-addons/gitea/bootstrap.sh"
! grep -Fq '\"private\":false' "$TMP_ROOT/projects/matrix-addons/gitea/bootstrap.sh"

echo "scaffold matrix passed ($MODE)"
