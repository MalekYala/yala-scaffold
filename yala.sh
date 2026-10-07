#!/bin/bash
# Scaffold a public-ready project into the current directory (or --into DIR).
# Templates live alongside (shapes/, BOT_TEMPLATE/, GITEA_TEMPLATE/, etc.);
# scaffolded projects land as sibling subdirectories of those templates.
#
# Every scaffolded project is:
#   - public-safe (no absolute operator paths, no private hostnames, no secrets)
#   - self-contained in Docker
#   - shaped by --type (service/worker/analysis/backtest/report/notebook/pipeline/image/tui)
#   - implemented in --lang (python default, node for service/worker, go for tui)
#   - pre-wired with STRATEGY.md, AGENTS.md, docs/, CHANGELOG.md, kpi.json,
#     qa_check.{py,js}, metric.sh, AUTORESEARCH.md, .gitlab-ci.yml, and portable
#     KPI collector + dashboard
#
# Usage:
#   yala.sh <name> [--type SHAPE] [--lang LANG] [--port PORT] [--license MIT]
#               [--into DIR] [--with-bot|--with-gitea|--with-rag|--with-kpi]
#               [--with-vault|--with-monitor|--with-all]
#   yala.sh --wizard              interactive; prompts for everything
#
# Shapes (see shapes/<shape>/<lang>/ for templates):
#   service   — long-running HTTP API (default; /health endpoint)       python | node
#   worker    — background task processor (heartbeat file pattern)      python | node
#   analysis  — one-shot data analysis (analyze.py → outputs/)          python only
#   backtest  — strategy backtest (metrics.json + graphs)               python only
#   report    — document generator (PDF/HTML/slideshow/xlsx)            python only
#   notebook  — Jupyter-first exploration                               python only
#   pipeline  — multi-stage ETL (stages/NN_*.py)                        python only
#   webapp    — React + Vite frontend served by Fastify                  node only
#   image     — browser image-to-image processing interface              python only
#   tui       — interactive terminal user interface                      go only
#   model     — LLM fine-tune: dataset -> LoRA -> eval -> ship gate       python only
#   mcp       — Model Context Protocol server (stdio, tool surface)      python | node
#   scraper   — extract records from remote pages (fixture-tested)       python only
#   bridge    — wrap an upstream service, degrade honestly               python only
#   cli       — distributable command-line tool                          go only
#   agent     — LangGraph agent: graph + tools + offline scenario tests   python only
#   stream    — WebRTC media/data streaming with session lifecycle        python only
#   browser   — multi-step browser automation, fixture-site tested        python only
#   game      — Godot game: headless boot, determinism, frame budget       python only
#   audio     — speech/audio generation, verified audible not silent       python only
#
# Legacy aliases: --type python → service --lang python
#                 --type node   → service --lang node
#                 --type generic → service --lang python
#
# Examples:
#   yala.sh my-api --type service --port 8500
#   yala.sh my-node-api --type service --lang node --port 8500
#   yala.sh my-queue --type worker --lang node
#   yala.sh rsi-backtest --type backtest
#   yala.sh q2-report --type report
#   yala.sh --wizard

set -euo pipefail

# A user's CDPATH makes `cd` print the directory it landed in, which would
# otherwise end up inside the command substitutions below and corrupt every
# path derived from them. Clearing it is local to this script's shell.
CDPATH=''

# Resolve the kit's own location so assets are found from a clone anywhere,
# including through a symlink on PATH.
SELF="${BASH_SOURCE[0]}"
while [[ -L "$SELF" ]]; do
    SELF_DIR="$(cd -P "$(dirname "$SELF")" && pwd)"
    SELF="$(readlink "$SELF")"
    [[ "$SELF" != /* ]] && SELF="$SELF_DIR/$SELF"
done
KIT_ROOT="$(cd -P "$(dirname "$SELF")" && pwd)"

NAME=""
PORT=""
TYPE="service"
LANG=""
LICENSE_KIND="MIT"
COPYRIGHT_HOLDER="${COPYRIGHT_HOLDER:-The Project Authors}"
OUT_DIR="$PWD"
# Local domain used in generated docs/proxy examples. Placeholder by default so
# nothing in a fresh project points at one operator's private hostnames.
SCAFFOLD_DOMAIN="${SCAFFOLD_DOMAIN:-example.local}"

# Add-ons are opt-in. A newcomer scaffolding their first project should get a
# runnable project and nothing else; the IRC bot, per-project git server and
# RAG index are powerful but each brings infrastructure to understand first.
WITH_BOT=0
WITH_GITEA=0
WITH_RAG=0
WITH_KPI=0
WITH_VAULT=0
WITH_MONITOR=0
WITH_REVIEW=0

# Interactive mode. The six-flag invocation is the main friction for someone
# scaffolding their first project, so --wizard asks instead of requiring them
# to already know the vocabulary.
WIZARD=0

usage() {
    sed -n '2,40p' "$0"
}

require_flag_value() {
    local flag="$1"
    local value="${2:-}"
    if [[ -z "$value" || "$value" == -* ]]; then
        echo "ERROR: $flag requires a value" >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) require_flag_value "$1" "${2:-}"; PORT="$2"; shift 2 ;;
        --type) require_flag_value "$1" "${2:-}"; TYPE="$2"; shift 2 ;;
        --lang) require_flag_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
        --license) require_flag_value "$1" "${2:-}"; LICENSE_KIND="$2"; shift 2 ;;
        --holder) require_flag_value "$1" "${2:-}"; COPYRIGHT_HOLDER="$2"; shift 2 ;;
        --into) require_flag_value "$1" "${2:-}"; OUT_DIR="$2"; shift 2 ;;
        --with-bot) WITH_BOT=1; shift ;;
        --with-gitea) WITH_GITEA=1; shift ;;
        --with-rag) WITH_RAG=1; shift ;;
        --with-kpi) WITH_KPI=1; shift ;;
        --with-vault) WITH_VAULT=1; shift ;;
        --with-monitor) WITH_MONITOR=1; shift ;;
        --with-review) WITH_REVIEW=1; shift ;;
        --with-all)
            WITH_BOT=1; WITH_GITEA=1; WITH_RAG=1; WITH_KPI=1
            WITH_VAULT=1; WITH_MONITOR=1; WITH_REVIEW=1
            shift
            ;;
        --wizard) WIZARD=1; shift ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*) echo "ERROR: unknown flag: $1" >&2; exit 1 ;;
        *)
            if [[ -n "$NAME" ]]; then
                echo "ERROR: unexpected positional argument: $1" >&2
                exit 1
            fi
            NAME="$1"
            shift
            ;;
    esac
done

# ── Interactive wizard ────────────────────────────────────────────────────
# Prompts for the things that have no safe default (the name) and offers the
# defaults for everything else, so a first-time user never has to memorise the
# flag vocabulary before seeing a working project. Anything already passed on
# the command line is used as the prompt's default, so
# `--wizard --type worker` is a sensible partial invocation.

prompt_default() {
    # prompt_default <question> <default> -> echoes the answer
    local question="$1" default="$2" answer=""
    if [[ -n "$default" ]]; then
        read -r -p "$question [$default]: " answer </dev/tty || true
        printf '%s' "${answer:-$default}"
    else
        read -r -p "$question: " answer </dev/tty || true
        printf '%s' "$answer"
    fi
}

prompt_yes_no() {
    # prompt_yes_no <question> <default y|n> -> returns 0 for yes
    local question="$1" default="$2" answer=""
    local hint="y/N"
    [[ "$default" == "y" ]] && hint="Y/n"
    read -r -p "$question [$hint]: " answer </dev/tty || true
    answer="${answer:-$default}"
    [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]
}

if (( WIZARD )); then
    if [[ ! -t 0 && ! -r /dev/tty ]]; then
        echo "ERROR: --wizard needs an interactive terminal" >&2
        exit 1
    fi

    echo "── yala-scaffold ────────────────────────────────────────────"
    echo "Answer or press enter to accept the default in brackets."
    echo ""

    while true; do
        NAME="$(prompt_default "Project name (lower-case, digits, dashes)" "$NAME")"
        [[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] && (( ${#NAME} <= 48 )) && break
        echo "  → must be lower-case letters, digits and dashes, 48 chars or fewer" >&2
    done

    echo ""
    echo "Shapes: service worker analysis backtest report notebook pipeline"
    echo "        webapp image tui model mcp scraper bridge cli agent stream browser game audio"
    echo "  service  — something calls it over HTTP"
    echo "  worker   — it runs continuously on its own"
    echo "  analysis — it runs once and produces a number"
    TYPE="$(prompt_default "Shape" "$TYPE")"

    case "$TYPE" in
        webapp)  DEFAULT_LANG="node" ;;
        tui|cli) DEFAULT_LANG="go" ;;
        *)      DEFAULT_LANG="python" ;;
    esac
    case "$TYPE" in
        service|worker|mcp) LANG="$(prompt_default "Language (python|node)" "${LANG:-$DEFAULT_LANG}")" ;;
        *)              LANG="${LANG:-$DEFAULT_LANG}" ;;
    esac

    case "$TYPE" in
        analysis|backtest|report|pipeline|tui|model|mcp|scraper|cli|agent|browser|game) : ;;
        *) PORT="$(prompt_default "Host port" "${PORT:-8500}")" ;;
    esac

    COPYRIGHT_HOLDER="$(prompt_default "Copyright holder" "$COPYRIGHT_HOLDER")"

    echo ""
    echo "Add-ons connect to infrastructure you must already run. Say no if unsure —"
    echo "each one can be added later."
    prompt_yes_no "  KPI collector + dashboard?" n && WITH_KPI=1
    prompt_yes_no "  Vault-backed secrets?" n && WITH_VAULT=1
    prompt_yes_no "  Scheduled health/KPI prober?" n && WITH_MONITOR=1
    prompt_yes_no "  AI code review on merge requests?" n && WITH_REVIEW=1
    prompt_yes_no "  Local RAG document index?" n && WITH_RAG=1
    prompt_yes_no "  IRC bot + agent dispatch?" n && WITH_BOT=1
    prompt_yes_no "  Per-project Gitea server?" n && WITH_GITEA=1
    echo ""
fi

if [[ -z "$NAME" ]]; then
    echo "ERROR: project name is required" >&2
    echo "Usage: yala.sh <name> [--type SHAPE] [--lang LANG] [--port N]" >&2
    echo "   or: yala.sh --wizard" >&2
    exit 1
fi
if ! [[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    # The name becomes a directory, a docker container name, a hostname label
    # and a git repo slug, so constrain it once here rather than debugging a
    # confusing failure in one of those four places later.
    echo "ERROR: name must be lower-case letters, digits and dashes: $NAME" >&2
    exit 1
fi
if (( ${#NAME} > 48 )); then
    echo "ERROR: project name must be 48 characters or fewer" >&2
    exit 1
fi

if [[ "$LICENSE_KIND" != "MIT" ]]; then
    echo "ERROR: unsupported --license: $LICENSE_KIND" >&2
    echo "Supported licenses: MIT" >&2
    exit 1
fi

if [[ -n "$PORT" ]] && { ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); }; then
    echo "ERROR: --port must be an integer from 1 to 65535" >&2
    exit 1
fi

# Legacy aliases: map old --type values to --type + --lang
case "$TYPE" in
    python)  TYPE="service"; LANG="${LANG:-python}" ;;
    node)    TYPE="service"; LANG="${LANG:-node}" ;;
    generic) TYPE="service"; LANG="${LANG:-python}" ;;
esac

VALID_SHAPES="service worker analysis backtest report notebook pipeline webapp image tui model mcp scraper bridge cli agent stream browser game audio"
if ! echo " $VALID_SHAPES " | grep -q " $TYPE "; then
    echo "ERROR: invalid --type: $TYPE" >&2
    echo "Valid shapes: $VALID_SHAPES" >&2
    exit 1
fi

# Per-shape default lang (must run BEFORE the generic python default below).
# webapp defaults to node because React + Vite + i18next has no Python equivalent.
if [[ -z "${LANG:-}" ]]; then
    case "$TYPE" in
        webapp) LANG="node" ;;
        tui|cli) LANG="go" ;;
        *)      LANG="python" ;;
    esac
fi

VALID_LANGS="python node go"
if ! echo " $VALID_LANGS " | grep -q " $LANG "; then
    echo "ERROR: invalid --lang: $LANG" >&2
    echo "Valid langs: $VALID_LANGS" >&2
    exit 1
fi

# Not every shape supports every language. Data-heavy shapes are python-only
# because their libraries (pandas, numpy, matplotlib, openpyxl, jupyter,
# pyarrow) have no comparable Node ecosystem. webapp is node-only because its
# Vite + React + i18next stack doesn't have a direct Python equivalent that
# would ship a real frontend. Reject invalid combos early.
case "$TYPE:$LANG" in
    analysis:node|backtest:node|report:node|notebook:node|pipeline:node|image:node|model:node|scraper:node|bridge:node|agent:node|stream:node|browser:node|game:node|audio:node)
        echo "ERROR: --type $TYPE does not currently support --lang node" >&2
        echo "Python-only shapes: analysis, backtest, report, notebook, pipeline, image, model, scraper, bridge, agent, stream, browser, game, audio" >&2
        echo "Use --lang python (default) or pick --type service/worker for node." >&2
        exit 1
        ;;
    webapp:python)
        echo "ERROR: --type webapp does not currently support --lang python" >&2
        echo "webapp ships React + Vite + i18next; node is the only supported lang." >&2
        echo "For a Python web UI, use --type service and render HTML with Jinja2." >&2
        exit 1
        ;;
    tui:python|tui:node|cli:python|cli:node)
        echo "ERROR: --type $TYPE supports only --lang go" >&2
        exit 1
        ;;
    service:go|worker:go|analysis:go|backtest:go|report:go|notebook:go|pipeline:go|webapp:go|image:go|model:go|scraper:go|bridge:go|mcp:go|agent:go|stream:go|browser:go|game:go|audio:go)
        echo "ERROR: --lang go is supported only by --type tui and --type cli" >&2
        exit 1
        ;;
esac

if [[ "$LANG" == "node" ]]; then
    QA_FILE="qa_check.js"
    QA_INTERPRETER="node"
    # The typed config boundary (AGENTS.md): one declaration site for every
    # environment variable, and the source .env.example is generated from.
    CONFIG_MODULE="src/config.js"
    CONFIG_PRINT_CMD="node src/config.js --print-env"
    CONFIG_CHECK_CMD="node src/config.js --check"
elif [[ "$LANG" == "go" ]]; then
    QA_FILE="qa-check"
    QA_INTERPRETER="/app/qa-check"
    CONFIG_MODULE="internal/config/config.go"
    CONFIG_PRINT_CMD="go run ./cmd/envtool --print-env"
    CONFIG_CHECK_CMD="go run ./cmd/envtool --check"
else
    QA_FILE="qa_check.py"
    QA_INTERPRETER="python3"
    CONFIG_MODULE="config.py"
    CONFIG_PRINT_CMD="python3 config.py --print-env"
    CONFIG_CHECK_CMD="python3 config.py --check"
fi

# Where the new project is written. Defaults to the current directory so the
# kit works from a clone anywhere; override with --into or PROJECTS_ROOT.
PROJECTS_ROOT="${PROJECTS_ROOT:-$OUT_DIR}"
PROJ="$PROJECTS_ROOT/$NAME"
PORT="${PORT:-8500}"
YEAR="$(date +%Y)"
DATE_ISO="$(date +%Y-%m-%d)"
INVOKING_UID="$(id -u)"
INVOKING_GID="$(id -g)"
HOST_UID="$INVOKING_UID"
HOST_GID="$INVOKING_GID"
if (( HOST_UID == 0 )); then
    HOST_UID=10001
fi
if (( HOST_GID == 0 )); then
    HOST_GID=10001
fi

for cmd in git docker; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    fi
done
if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: Docker Compose v2 is required (expected: docker compose)" >&2
    exit 1
fi

mkdir -p "$PROJECTS_ROOT"
if [[ ! -d "$PROJECTS_ROOT" || ! -w "$PROJECTS_ROOT" ]]; then
    echo "ERROR: output directory is not writable: $PROJECTS_ROOT" >&2
    exit 1
fi

if [[ -e "$PROJ" ]]; then
    echo "ERROR: $PROJ already exists" >&2
    exit 1
fi

PROJECT_CREATED=0
SCAFFOLD_COMPLETE=0
report_partial_project() {
    local rc=$?
    if (( rc != 0 && PROJECT_CREATED == 1 && SCAFFOLD_COMPLETE == 0 )); then
        echo "ERROR: scaffolding stopped; partial project left at: $PROJ" >&2
        echo "Remove that directory before retrying." >&2
    fi
}
trap report_partial_project EXIT

# Kit assets live beside this script, wherever the repo was cloned.
TPL="$KIT_ROOT/templates"
ADDONS="$KIT_ROOT/addons"
SHAPE_DIR="$KIT_ROOT/shapes/$TYPE/$LANG"

# Verify universal + shape-specific templates are present
UNIVERSAL_TEMPLATES=(
    "$TPL/AGENTS_TEMPLATE.md"
    "$TPL/STRATEGY_TEMPLATE.md"
    "$TPL/AUTORESEARCH_TEMPLATE.md"
    "$TPL/KPI_SETUP_TEMPLATE.md"
    "$ADDONS/kpi/collector.py"
    "$ADDONS/kpi/dashboard.py"
    "$TPL/LOCAL_TEMPLATE.md"
    "$TPL/ENV_EXAMPLE_TEMPLATE"
    "$TPL/LICENSE_MIT_TEMPLATE"
    "$TPL/CONTRIBUTING_TEMPLATE.md"
    "$TPL/GITLEAKS_TEMPLATE.toml"
    "$TPL/TRANSLATE_DOCS_TEMPLATE.sh"
    "$TPL/TRANSLATE_DOCS_IMPL_TEMPLATE.py"
    "$TPL/CHECK_MEMORY_TEMPLATE.py"
    "$TPL/CHECK_LOCALES_TEMPLATE.py"
    "$TPL/CHECK_ENV_TEMPLATE.py"
    "$TPL/CHECK_ROOT_CLUTTER_TEMPLATE.py"
    "$TPL/CHECK_STYLES_TEMPLATE.py"
    "$TPL/REFRESH_AGENTS_TEMPLATE.py"
    "$TPL/BENCH_RUN_TEMPLATE.py"
    "$TPL/BENCH_COMPARE_TEMPLATE.py"
    "$TPL/PRECOMMIT_TEMPLATE_python.yaml"
    "$TPL/PRECOMMIT_TEMPLATE_node.yaml"
    "$TPL/PRECOMMIT_TEMPLATE_go.yaml"
    "$TPL/CONFIG_TEMPLATE.py"
    "$TPL/CONFIG_TEMPLATE.js"
)
UNIVERSAL_TEMPLATE_DIRS=(
    "$TPL/BRAND_TEMPLATE"
    "$TPL/LOCALES_TEMPLATE"
    "$ADDONS/rag"
    "$ADDONS/bot"
    "$TPL/MEMORY_TEMPLATE"
    "$ADDONS/gitea"
    "$ADDONS/vault"
    "$ADDONS/monitor"
    "$ADDONS/review"
)
for f in "${UNIVERSAL_TEMPLATES[@]}"; do
    [[ -f "$f" ]] || { echo "ERROR: universal template missing: $f" >&2; exit 1; }
done
for d in "${UNIVERSAL_TEMPLATE_DIRS[@]}"; do
    [[ -d "$d" ]] || { echo "ERROR: universal template dir missing: $d" >&2; exit 1; }
done
[[ -d "$SHAPE_DIR" ]] || { echo "ERROR: shape directory missing: $SHAPE_DIR" >&2; exit 1; }

echo "[scaffold] creating $PROJ (shape: $TYPE, lang: $LANG, port: $PORT)"
mkdir -p "$PROJ"
PROJECT_CREATED=1
cd "$PROJ"

# ── Helper: fill placeholders ──────────────────────────────────────────────
escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

NAME_SED="$(escape_sed_replacement "$NAME")"
TYPE_SED="$(escape_sed_replacement "$TYPE")"
LANG_SED="$(escape_sed_replacement "$LANG")"
PORT_SED="$(escape_sed_replacement "$PORT")"
YEAR_SED="$(escape_sed_replacement "$YEAR")"
HOLDER_SED="$(escape_sed_replacement "$COPYRIGHT_HOLDER")"
DATE_SED="$(escape_sed_replacement "$DATE_ISO")"
PROJ_SED="$(escape_sed_replacement "$PROJ")"
KIT_ROOT_SED="$(escape_sed_replacement "$KIT_ROOT")"
DOMAIN_SED="$(escape_sed_replacement "$SCAFFOLD_DOMAIN")"
QA_FILE_SED="$(escape_sed_replacement "$QA_FILE")"
HOST_UID_SED="$(escape_sed_replacement "$HOST_UID")"
HOST_GID_SED="$(escape_sed_replacement "$HOST_GID")"
CONFIG_MODULE_SED="$(escape_sed_replacement "$CONFIG_MODULE")"
CONFIG_PRINT_SED="$(escape_sed_replacement "$CONFIG_PRINT_CMD")"

fill() {
    sed \
        -e "s|<name>|$NAME_SED|g" \
        -e "s|<project-name>|$NAME_SED|g" \
        -e "s|<project>|$NAME_SED|g" \
        -e "s|<shape>|$TYPE_SED|g" \
        -e "s|<lang>|$LANG_SED|g" \
        -e "s|<PORT>|$PORT_SED|g" \
        -e "s|<YEAR>|$YEAR_SED|g" \
        -e "s|<COPYRIGHT_HOLDER>|$HOLDER_SED|g" \
        -e "s|<DATE>|$DATE_SED|g" \
        -e "s|<PROJECT_PATH>|$PROJ_SED|g" \
        -e "s|<CADDY_CONFIG>|~/caddy-proxy/Caddyfile|g" \
        -e "s|<SCRIPTS>|$KIT_ROOT_SED/scripts|g" \
        -e "s|<domain>|$DOMAIN_SED|g" \
        -e "s|<qa_file>|$QA_FILE_SED|g" \
        -e "s|<HOST_UID>|$HOST_UID_SED|g" \
        -e "s|<HOST_GID>|$HOST_GID_SED|g" \
        -e "s|<config_module>|$CONFIG_MODULE_SED|g" \
        -e "s|<config_print_cmd>|$CONFIG_PRINT_SED|g" \
        "$1"
}

# fill_dir: copy a directory tree and run fill() on every text file.
# Skips cache/build directories that should never land in a scaffolded
# project even if an earlier tool run dirtied the template.
fill_dir() {
    local src="$1"
    local dest="$2"
    mkdir -p "$dest"
    # Use find so we pick up hidden files like .gitlab-ci.yml. Prune
    # cache directories so earlier ruff/mypy/pytest runs on the template
    # don't pollute new projects.
    (cd "$src" && find . -type f \
        -not -path '*/.ruff_cache/*' \
        -not -path '*/.mypy_cache/*' \
        -not -path '*/__pycache__/*' \
        -not -path '*/.pytest_cache/*' \
        -not -path '*/node_modules/*' \
    ) | while read -r rel; do
        rel="${rel#./}"
        local src_file="$src/$rel"
        local dest_file="$dest/$rel"
        mkdir -p "$(dirname "$dest_file")"
        case "$rel" in
            *.png|*.jpg|*.jpeg|*.pdf|*.xlsx|*.parquet|*.zip|*.gz)
                cp "$src_file" "$dest_file"
                ;;
            *)
                fill "$src_file" > "$dest_file"
                ;;
        esac
    done
}

# ── UNIVERSAL PUBLIC FILES ────────────────────────────────────────────────

# AGENTS.md (shape-aware via §0)
fill "$TPL/AGENTS_TEMPLATE.md" > AGENTS.md

# STRATEGY.md — the project's reason for being
fill "$TPL/STRATEGY_TEMPLATE.md" > STRATEGY.md

# CONTRIBUTING.md, LICENSE, .env.example, .gitleaks.toml
fill "$TPL/CONTRIBUTING_TEMPLATE.md" > CONTRIBUTING.md
fill "$TPL/LICENSE_MIT_TEMPLATE" > LICENSE
fill "$TPL/GITLEAKS_TEMPLATE.toml" > .gitleaks.toml

# .env.example is written in two parts:
#   1. operator-facing prose and optional add-on wiring (hand-maintained)
#   2. a managed block generated from the config module's schema
# The managed block ships pre-generated so scaffolding needs no host Python,
# Node or Go toolchain. `make env-example` regenerates it inside Docker, and
# `make check-env` fails if the two ever drift.
fill "$TPL/ENV_EXAMPLE_TEMPLATE" > .env.example
printf '\n' >> .env.example
# A shape that ships config_extra.py declares more than the universal schema,
# so it needs its own pre-generated block. Falls back to the per-language one.
ENV_BLOCK="$TPL/ENV_BLOCK_shape_${TYPE}_${LANG}"
[[ -f "$ENV_BLOCK" ]] || ENV_BLOCK="$TPL/ENV_BLOCK_${LANG}"
fill "$ENV_BLOCK" >> .env.example

# AUTORESEARCH.md — shape-agnostic
fill "$TPL/AUTORESEARCH_TEMPLATE.md" > AUTORESEARCH.md

# Portable KPI collector + dashboard (scripts/) — opt-in via --with-kpi.
# kpi.json itself is always written; these only add the collector that ships
# those numbers to a central store, which needs somewhere to ship them to.
mkdir -p scripts
if [[ $WITH_KPI -eq 1 ]]; then
    fill "$ADDONS/kpi/collector.py" > scripts/kpi_collector.py
    fill "$ADDONS/kpi/dashboard.py" > scripts/kpi_dashboard.py
    chmod +x scripts/kpi_collector.py scripts/kpi_dashboard.py
fi

# Doc translation helpers (scripts/translate_docs.sh + impl)
fill "$TPL/TRANSLATE_DOCS_TEMPLATE.sh" > scripts/translate_docs.sh
fill "$TPL/TRANSLATE_DOCS_IMPL_TEMPLATE.py" > scripts/translate_docs_impl.py
chmod +x scripts/translate_docs.sh scripts/translate_docs_impl.py

# Memory lint / promote helper
fill "$TPL/CHECK_MEMORY_TEMPLATE.py" > scripts/check_memory.py
chmod +x scripts/check_memory.py

# ── Drift checks (AGENTS.md §7) ───────────────────────────────────────────
# Three cheap, dependency-free checks for the failure modes that lint and
# typecheck cannot see: a translation missing a key, a .env.example that no
# longer matches the code, and one-off debug scripts accumulating at the root.
fill "$TPL/CHECK_LOCALES_TEMPLATE.py" > scripts/check_locales.py
fill "$TPL/CHECK_ENV_TEMPLATE.py" > scripts/check_env.py
fill "$TPL/CHECK_ROOT_CLUTTER_TEMPLATE.py" > scripts/check_root_clutter.py
fill "$TPL/REFRESH_AGENTS_TEMPLATE.py" > scripts/refresh_agents.py
chmod +x scripts/check_locales.py scripts/check_env.py \
    scripts/check_root_clutter.py scripts/refresh_agents.py

# Style-token resolution — only for shapes that actually render a UI. A CSS
# custom property that is referenced but never defined renders invisible with
# no error anywhere; this is the cheapest possible guard against that.
case "$TYPE" in
    webapp|image|service|notebook)
        fill "$TPL/CHECK_STYLES_TEMPLATE.py" > scripts/check_styles.py
        chmod +x scripts/check_styles.py
        HAS_STYLE_CHECK=1
        ;;
    *)
        HAS_STYLE_CHECK=0
        ;;
esac

# ── Benchmarks (AUTORESEARCH.md) ──────────────────────────────────────────
# metric.sh answers "how good is it now"; these answer "is it worse than it
# was", which nothing else in the project tracks.
fill "$TPL/BENCH_RUN_TEMPLATE.py" > scripts/bench_run.py
fill "$TPL/BENCH_COMPARE_TEMPLATE.py" > scripts/bench_compare.py
chmod +x scripts/bench_run.py scripts/bench_compare.py

# ── Typed config boundary ─────────────────────────────────────────────────
# Every environment variable declared once, validated at startup, with
# .env.example generated from the declaration rather than maintained beside it.
case "$LANG" in
    node)
        mkdir -p src
        fill "$TPL/CONFIG_TEMPLATE.js" > src/config.js
        ;;
    go)
        # shapes/tui/go ships internal/config/config.go and cmd/envtool via
        # fill_dir below, since Go is currently tui-only.
        :
        ;;
    *)
        fill "$TPL/CONFIG_TEMPLATE.py" > config.py
        ;;
esac

# ── Pre-commit hooks ──────────────────────────────────────────────────────
# Universal, but language-appropriate. Fast hooks on staged files at commit;
# slow whole-project hooks at push, where waiting is expected.
fill "$TPL/PRECOMMIT_TEMPLATE_${LANG}.yaml" > .pre-commit-config.yaml

# ── UNIVERSAL brand/ + locales/ + memory/, then opt-in add-ons ────────────
# brand/, locales/ and memory/ are pure files with no infrastructure behind
# them, so every project gets them. The add-ons each require something to
# exist outside the project (an IRC server, a git server, an LLM endpoint),
# so they are opt-in — see docs/ADDONS.md.
fill_dir "$TPL/BRAND_TEMPLATE" "$PROJ/brand"
fill_dir "$TPL/LOCALES_TEMPLATE" "$PROJ/locales"
fill_dir "$TPL/MEMORY_TEMPLATE" "$PROJ/memory"

if [[ $WITH_RAG -eq 1 ]]; then
    fill_dir "$ADDONS/rag" "$PROJ/rag"
    chmod +x "$PROJ/rag/index.py" 2>/dev/null || true
fi
if [[ $WITH_BOT -eq 1 ]]; then
    fill_dir "$ADDONS/bot" "$PROJ/bot"
    chmod +x "$PROJ/bot/bot.py" "$PROJ/bot/runners"/*.sh 2>/dev/null || true
fi
if [[ $WITH_GITEA -eq 1 ]]; then
    fill_dir "$ADDONS/gitea" "$PROJ/gitea"
    chmod +x "$PROJ/gitea/bootstrap.sh" 2>/dev/null || true
fi
if [[ $WITH_VAULT -eq 1 ]]; then
    fill_dir "$ADDONS/vault" "$PROJ/vault"
    chmod +x "$PROJ/vault/pull.sh" "$PROJ/vault/check.sh" 2>/dev/null || true
    # secret-map.tsv is data, not a script, and its tab separators matter.
    chmod 0644 "$PROJ/vault/secret-map.tsv" 2>/dev/null || true
fi
if [[ $WITH_MONITOR -eq 1 ]]; then
    fill_dir "$ADDONS/monitor" "$PROJ/monitor"
    chmod +x "$PROJ/monitor/probe.py" 2>/dev/null || true
fi
if [[ $WITH_REVIEW -eq 1 ]]; then
    fill_dir "$ADDONS/review" "$PROJ/review"
    chmod +x "$PROJ/review/gate.py" "$PROJ/review/fetch_poster.sh" "$PROJ/review/run.sh" 2>/dev/null || true
fi

# docs/ — living documentation stubs (AGENTS.md §7)
mkdir -p docs
fill "$TPL/KPI_SETUP_TEMPLATE.md" > docs/KPI_SETUP.md

# docs/plans/ + docs/specs/ — where a change is designed before it is built.
# memory/decisions/ records why something was done, after the fact; these
# record what is about to be done, and are the natural home for the document
# you write before a large change. Dated filenames sort chronologically and
# make staleness obvious.
mkdir -p docs/plans docs/specs
cat > docs/plans/README.md <<EOF
# Plans

One file per planned change, named \`YYYY-MM-DD-short-topic.md\`.

A plan says **what** will change and **in what order**: the milestones, the
sequencing, what is deliberately out of scope. Its companion in
[../specs](../specs) says **how** the result should behave.

This is not the same as [memory/decisions](../../memory/decisions), which
records why something was done *after* the fact. A plan is written first, and
is allowed to be wrong — that is what makes it worth reviewing.

Keep finished plans. A plan that was abandoned, with a line explaining why, is
often more useful later than one that was followed.
EOF

cat > docs/specs/README.md <<EOF
# Specs

One file per designed change, named \`YYYY-MM-DD-short-topic-design.md\`,
pairing with the plan of the same date in [../plans](../plans).

A spec pins down behaviour: interfaces, data shapes, error cases, edge cases,
and what "done" looks like precisely enough to test. If a question about
expected behaviour comes up twice, the answer belongs here.

Write the spec before the code when the change is large enough that getting
the interface wrong would be expensive to undo.
EOF

# ── SHAPE-SPECIFIC FILES ──────────────────────────────────────────────────
# Copies everything from shapes/$TYPE/ into the project root, applying fill().
# This drops in: Dockerfile, docker-compose.yml, requirements.txt, app.py /
# worker.py / analyze.py / backtest.py / generate_report.py / pipeline.py,
# qa_check.py, kpi.json, metric.sh, .gitlab-ci.yml, plus fixtures/ / content/
# / notebooks/ / stages/ as relevant to the shape.
fill_dir "$SHAPE_DIR" "$PROJ"

# Ensure metric.sh is executable
[[ -f metric.sh ]] && chmod +x metric.sh || true

if [[ "$LANG" == "node" ]]; then
    LINT_CMD="npm run lint"
    FORMAT_CMD="npm run lint -- --fix"
    TYPECHECK_CMD="npm run typecheck"
    SANDBOX_TMPFS_OPTIONS="rw,noexec,nosuid,nodev,size=128m"
    # Dependency vulnerabilities. --audit-level=high keeps a fresh scaffold
    # from being born red over low-severity advisories in transitive dev deps.
    AUDIT_CMD="npm audit --audit-level=high"
    # Unused files, exports and dependencies. Nothing else catches a package
    # that is installed, shipped in the image, and imported by no one.
    DEADCODE_CMD="npx --yes knip --no-exit-code || echo 'knip reported findings (non-blocking)'"
    DEADCODE_IGNORE_NOTE="knip.json"
elif [[ "$LANG" == "go" ]]; then
    LINT_CMD='test -z "$$(/usr/local/go/bin/gofmt -l .)" && /usr/local/go/bin/go vet ./...'
    FORMAT_CMD='/usr/local/go/bin/gofmt -w .'
    TYPECHECK_CMD="/usr/local/go/bin/go test ./..."
    # The Go toolchain executes temporary test binaries from GOCACHE.
    SANDBOX_TMPFS_OPTIONS="rw,exec,nosuid,nodev,size=512m,mode=1777"
    AUDIT_CMD="/usr/local/go/bin/go run golang.org/x/vuln/cmd/govulncheck@latest ./..."
    DEADCODE_CMD='/usr/local/go/bin/go mod tidy -diff || echo "go.mod/go.sum are not tidy (non-blocking)"'
    DEADCODE_IGNORE_NOTE="go.mod"
else
    LINT_CMD="ruff check . && ruff format --check ."
    FORMAT_CMD="ruff format . && ruff check --fix ."
    TYPECHECK_CMD="mypy ."
    SANDBOX_TMPFS_OPTIONS="rw,noexec,nosuid,nodev,size=128m"
    # Installed at run time, unpinned and on purpose: an advisory database is
    # only useful when it is current, and these are diagnostics rather than
    # build dependencies. Same reasoning as govulncheck above.
    AUDIT_CMD="pip install --quiet --disable-pip-version-check pip-audit && pip-audit --requirement requirements.txt"
    DEADCODE_CMD="pip install --quiet --disable-pip-version-check deptry vulture && { deptry . || echo 'deptry reported findings (non-blocking)'; }; vulture . --min-confidence 80 || echo 'vulture reported findings (non-blocking)'"
    DEADCODE_IGNORE_NOTE="pyproject.toml ([tool.deptry] / [tool.vulture])"
fi

case "$TYPE" in
    analysis|backtest|report|pipeline|model|scraper|mcp|agent|browser|game)
        RUN_HINT="docker compose up --build"
        QA_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint $QA_INTERPRETER $NAME $QA_FILE"
        METRIC_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint sh $NAME metric.sh"
        ;;
    tui)
        RUN_HINT="docker compose run --rm $NAME"
        QA_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint /app/qa-check $NAME"
        METRIC_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint sh $NAME metric.sh"
        ;;
    cli)
        RUN_HINT="docker compose run --rm $NAME --help"
        QA_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint /app/qa-check $NAME -bin /app/$NAME"
        METRIC_DOCKER_CMD="docker compose run --rm --no-deps --entrypoint sh $NAME metric.sh"
        ;;
    *)
        RUN_HINT="docker compose up -d --build"
        QA_DOCKER_CMD="docker compose exec -T $NAME $QA_INTERPRETER $QA_FILE"
        METRIC_DOCKER_CMD="docker compose exec -T $NAME sh metric.sh"
        ;;
esac

# ── docs/ stubs — populated with shape-aware starters ─────────────────────

cat > docs/SETUP.md <<EOF
# $NAME — Setup Guide

> Full installation, configuration, and first-run walkthrough. For the 60-second
> quickstart see [README.md](../README.md); for development conventions see
> [AGENTS.md](../AGENTS.md); for the project's reason for being see
> [STRATEGY.md](../STRATEGY.md).
>
> This is a **$TYPE** shape project (see AGENTS.md §0).

## Prerequisites

- Docker 24+ with Docker Compose v2
- Git

No host Python or Node.js installation is required. Dependencies, tests, lint,
type checks, and QA run inside project containers.

## 1. Clone and configure

\`\`\`bash
git clone <repo-url> $NAME
cd $NAME
cp .env.example .env
\`\`\`

Edit \`.env\` and fill in every placeholder value. Document every variable
you add here — operators should never have to guess.

## 2. Build

\`\`\`bash
make setup
\`\`\`

## 3. Run

\`\`\`bash
make run
\`\`\`

## 4. Verify

\`\`\`bash
make test
make qa
\`\`\`

## 5. Host safety

- Published ports bind to \`127.0.0.1\`, not every host interface.
- Containers run as non-root with Linux capabilities dropped.
- Root filesystems are read-only; only declared project volumes are writable.
- No command changes global Git, Python, Node, Docker, or shell configuration.
- \`HOST_UID\`/\`HOST_GID\` in \`.env\` keep project bind mounts writable by
  matching the invoking account without running the container as root.

## 6. Monitoring

KPI definitions live in \`kpi.json\`. See [KPI_SETUP.md](KPI_SETUP.md).

The collector and dashboard are only included when scaffolding with
\`--with-kpi\`.

## See also

- [README.md](../README.md)
- [STRATEGY.md](../STRATEGY.md) — what this project is for and how success is measured
- [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- [AGENTS.md](../AGENTS.md)
EOF

# docs/API.md — only for shapes that have an HTTP surface
if [[ "$TYPE" == "service" || "$TYPE" == "notebook" || "$TYPE" == "webapp" || "$TYPE" == "image" || "$TYPE" == "bridge" || "$TYPE" == "stream" || "$TYPE" == "audio" ]]; then
    cat > docs/API.md <<EOF
# $NAME — API Reference

> Every endpoint this service exposes. Update in the same PR as any endpoint
> change (AGENTS.md §7).

## Conventions

- **Base URL:** \`http://127.0.0.1:$PORT\` (behind an operator reverse proxy in prod)
- **Content-Type:** \`application/json\`
- **Errors:** JSON \`{"error": "...", "code": "ERR_CODE"}\` with appropriate HTTP status

## Endpoints

### \`GET /health\`

Liveness/readiness probe.

**Response 200:** \`{"status": "ok", "service": "$NAME"}\`

**Response 503:** \`{"status": "fail", "checks": {"<dep>": "<error>"}}\`

---

*(Add new endpoint sections as you implement them.)*
EOF
else
    cat > docs/USAGE.md <<EOF
# $NAME — Usage

> Entry point contract, CLI flags, and env vars for this **$TYPE** project.
> Update in the same PR as any behavior change (AGENTS.md §7).

## Entry point

This is a \`$TYPE\` shape project. Its primary entry point is determined by
the shape — see the root of the repo for:

- \`analysis\`  → \`analyze.py\`
- \`backtest\`  → \`backtest.py\` + \`config/strategy.yml\`
- \`report\`    → \`generate_report.py\` + \`content/\` + \`templates/\`
- \`worker\`    → \`worker.py\`
- \`pipeline\`  → \`pipeline.py\` + \`stages/\`
- \`model\`     → \`dataset/build.py\` → \`preflight.py\` → \`train.py\` → \`evaluate.py\`
- \`mcp\`       → \`server.py\` / \`src/server.js\` (tools declared in \`TOOLS\`)
- \`scraper\`   → \`scrape.py\` + \`extract.py\` (selectors) + \`fixtures/\`
- \`cli\`       → \`cmd/cli/main.go\` + \`internal/app/\`
- \`agent\`     → \`graph.py\` (tools + routing) + \`eval/scenarios.json\`
- \`browser\`   → \`workflows/*.json\` (steps) + \`runner.py\` + \`fixtures/site/\`
- \`game\`      → \`scripts/sim.gd\` (rules) + \`scenes/\` + \`project.godot\`
- \`audio\`     → \`app.py\` + \`engines.py\` (swappable) + \`audio_checks.py\`

## Running

\`\`\`bash
make doctor
make setup
make run
make test
make qa
\`\`\`

All dependencies and checks run inside Docker; no host Python or Node.js
installation is required.

## Environment variables

*(Every variable this project reads. Keep in sync with \`.env.example\`.)*

| Var | Default | Purpose |
|---|---|---|
| \`LOG_LEVEL\` | \`info\` | \`debug\` / \`info\` / \`warn\` / \`error\` |
| *(add yours)* | | |

## Outputs

*(Where artifacts land, what format, and who consumes them. Keep in sync
with \`STRATEGY.md\`.)*

## Edge cases

*(Empty input, unicode, oversized payloads, concurrent runs, partial failures.
Document them HERE instead of letting them surface only as bugs.)*

## See also

- [STRATEGY.md](../STRATEGY.md) — problem + success metric
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — module map
- [AGENTS.md](../AGENTS.md) — conventions
EOF
fi

KPI_ARCH_LINE=""
if [[ $WITH_KPI -eq 1 ]]; then
    KPI_ARCH_LINE="- \`scripts/kpi_collector.py\` + \`scripts/kpi_dashboard.py\` — portable monitoring"
fi

cat > docs/ARCHITECTURE.md <<EOF
# $NAME — Architecture

> Module map, data flow, and key design decisions. Update in the same PR
> that restructures code or changes a data flow (AGENTS.md §7). This is a
> **$TYPE** shape project — see [AGENTS.md §0](../AGENTS.md#0-project-shape-and-strategy).

## Overview

*(One paragraph: what this project does, who its caller/consumer is, what it
depends on. Should match STRATEGY.md's problem statement.)*

## Module map

*(Fill in as the project grows. The shape-specific entry points are:)*

- Entry point(s): see [AGENTS.md §1](../AGENTS.md#1-layout)
- \`$QA_FILE\` — E2E check ([AGENTS.md §6](../AGENTS.md))
- \`kpi.json\` — KPI declarations ([AGENTS.md §17](../AGENTS.md#17-kpi-tracking--measure-everything-that-matters))
- \`metric.sh\` — autoresearch metric ([AGENTS.md §18](../AGENTS.md#18-autonomous-iteration--autoresearch))
$KPI_ARCH_LINE

## Data flow

*(Describe how data moves through the project. For analysis/backtest/pipeline
this is usually: inputs → stages/transforms → outputs. For service this is
request → handler → response.)*

## Key design decisions

*(Document decisions that weren't obvious. Format: **Decision**, **Why**,
**Alternatives considered**, **Trade-offs**. Future-you will thank you.)*

### Decision: Project shape = \`$TYPE\`

- **Why:** *(fill in why this shape fits the problem better than others)*
- **Alternatives considered:** *(which shapes were considered and rejected)*
- **Trade-off:** *(what does this shape cost)*

## External dependencies

| Dependency | Purpose | Failure mode | Mitigation |
|---|---|---|---|
| *(none yet)* | — | — | — |

## Performance characteristics

*(Record observed latencies, throughput, memory footprint. Numbers beat vibes.)*

## See also

- [STRATEGY.md](../STRATEGY.md)
- [AGENTS.md](../AGENTS.md)
- [docs/SETUP.md](SETUP.md)
EOF

cat > CHANGELOG.md <<EOF
# Changelog

All user-visible changes are documented in this file. Every PR that changes
behavior must add an entry under \`## [Unreleased]\` in the same PR
(AGENTS.md §7).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial \`$TYPE\`-shape scaffold with STRATEGY.md, kpi.json, $QA_FILE,
  containerized quality checks, .gitlab-ci.yml, and docs/.

### Changed
- *(Nothing yet.)*

### Deprecated
- *(Nothing yet.)*

### Removed
- *(Nothing yet.)*

### Fixed
- *(Nothing yet.)*

### Security
- *(Nothing yet.)*
EOF

# ── README.md — shape-aware quickstart ────────────────────────────────────

case "$TYPE:$LANG" in
    service:python)
        ENTRY_HINT="After \`docker compose up -d\`, hit \`curl http://127.0.0.1:$PORT/health\`. Entry point: \`app.py\` (FastAPI + uvicorn)."
        ;;
    service:node)
        ENTRY_HINT="After \`docker compose up -d\`, hit \`curl http://127.0.0.1:$PORT/health\`. Entry point: \`src/index.js\` (Fastify on Node 20)."
        ;;
    worker:python)
        ENTRY_HINT="After \`docker compose up -d\`, tail \`docker compose logs -f\` to see the worker loop. Entry point: \`worker.py\`."
        ;;
    worker:node)
        ENTRY_HINT="After \`docker compose up -d\`, tail \`docker compose logs -f\` to see the worker loop. Entry point: \`src/worker.js\` (Node 20)."
        ;;
    webapp:node)
        ENTRY_HINT="After \`docker compose up -d\`, open http://127.0.0.1:$PORT in your browser. Entry point: \`src/main.jsx\` (React 18 + Vite + i18next). Brand kit in \`brand/\`, translations in \`locales/\`."
        ;;
    image:*)
        ENTRY_HINT="After \`docker compose up -d\`, open http://127.0.0.1:$PORT to upload an image, choose a transform, and preview or download the result. Entry point: \`app.py\` (FastAPI + Pillow). Processing stays inside the container."
        ;;
    tui:go)
        ENTRY_HINT="Run \`make run\` from a terminal for the interactive Bubble Tea interface. Entry point: \`cmd/tui/main.go\`; press arrow keys or j/k to navigate, Enter to select, and q to quit."
        ;;
    analysis:*)
        ENTRY_HINT="\`docker compose up\` runs \`analyze.py\` once against \`fixtures/\` and writes \`outputs/\`."
        ;;
    backtest:*)
        ENTRY_HINT="\`docker compose up\` runs \`backtest.py\` against \`fixtures/SPY.csv\` and writes \`results/metrics.json\` + \`outputs/equity_curve.png\`."
        ;;
    report:*)
        ENTRY_HINT="\`docker compose up\` runs \`generate_report.py\` and writes \`outputs/report.pdf\`, \`outputs/slides.html\`, \`outputs/summary.xlsx\`."
        ;;
    notebook:*)
        ENTRY_HINT="After \`docker compose up -d\`, open http://127.0.0.1:$PORT in your browser for JupyterLab. Localhost use is tokenless by default; set \`JUPYTER_TOKEN\` in \`.env\` to require authentication. **Warning:** reverse-proxy exposure with an empty token grants unauthenticated visitors code execution inside the container."
        ;;
    pipeline:*)
        ENTRY_HINT="\`docker compose up\` runs the pipeline end-to-end and writes \`outputs/manifest.json\` + \`outputs/final.parquet\`."
        ;;
    audio:*)
        ENTRY_HINT="After \`docker compose up -d\`, POST text to \`/synthesize\` and get audio back — the service **refuses to return silence**, so an engine that fails on an edge case produces a 500 with a reason rather than a valid, inaudible 200. The engine is a parameter: \`engines.py\` ships a synthetic one that produces real, deterministic, audible output with no model, so the whole pipeline is verifiable before you wire in Piper, Coqui or a hosted API. \`make qa\` checks duration, loudness, sample rate, clipping and that the signal survives encode/decode intact."
        ;;
    game:*)
        ENTRY_HINT="\`docker compose up\` runs the headless contract check — scenes load, every \`res://\` reference resolves, scripts compile, the simulation advances, the same seed still produces the same game, and a tick stays inside its frame budget. No display, no GPU. Gameplay rules live in \`scripts/sim.gd\`, deliberately separate from rendering, which is what makes all of that checkable. Open the project in the Godot editor to play it. The checks are engine-independent — see docs/USAGE.md for porting them to Unity or Unreal."
        ;;
    browser:*)
        ENTRY_HINT="\`docker compose up\` runs every workflow in \`workflows/\` against the committed fixture site on an ephemeral port — no external site, nothing to configure. Workflows are data, not code, and there is deliberately no sleep step: every wait is on a condition, because a fixed delay is a bet that CI is as fast as your laptop. \`make qa\` additionally proves the harness can *fail* (a missing selector must go red), that every workflow asserts something, and that repeated runs agree. Point \`TARGET_BASE_URL\` at a real site when you are ready."
        ;;
    stream:*)
        ENTRY_HINT="After \`docker compose up -d\`, open http://127.0.0.1:$PORT for a browser viewer that negotiates a WebRTC session. The media source is a parameter — \`build_track()\` in \`tracks.py\` ships a synthetic generator so the whole path is testable with no camera and no GPU; swap it for a capture device, a rendered viewport, or frames from another process. \`make qa\` drives a real loopback session through handshake, media flow, stall detection, reconnect backoff and teardown in about 20 seconds. **Leave \`ICE_SERVERS\` empty locally** — unreachable public STUN turns a 1.3s handshake into 15s."
        ;;
    agent:*)
        ENTRY_HINT="\`make qa\` checks the whole graph **offline** — structure, tool wiring, scenario replay and termination — using a scripted model, so it needs no API key and costs nothing. Declare tools in \`TOOLS\` (graph.py) and behaviour fixtures in \`eval/scenarios.json\`. \`make evaluate\` is the opt-in step that asks a *real* model whether it picks the right tools, scored against \`eval/thresholds.json\`. Run it with \`python3 agent.py \"your prompt\"\`."
        ;;
    mcp:*)
        ENTRY_HINT="This is an MCP server: a client launches it as a subprocess and talks JSON-RPC over stdio, so there is no port and no \`/health\`. \`make qa\` speaks the real protocol to it — handshake, \`tools/list\`, and a round-trip call of every declared tool. Declare tools in \`TOOLS\` (server.py / src/server.js); the checker asserts the running server matches that declaration. **Log to stderr only** — stdout is the transport, and a stray print corrupts it."
        ;;
    scraper:*)
        ENTRY_HINT="\`docker compose up\` extracts from the committed fixture in \`fixtures/\`, not the live site. Selectors live in \`SELECTORS\` (extract.py); \`make qa\` proves they still match, and treats *zero records from a page that did not say it was empty* as a failure — the silent breakage a live-site test cannot see. Set \`TARGET_BASE_URL\` in \`.env\` to crawl for real."
        ;;
    bridge:*)
        ENTRY_HINT="After \`docker compose up -d\`, \`/health\` answers liveness and \`/ready\` reports whether the upstream is reachable — deliberately different questions. \`/proxy/{path}\` forwards upstream, strips credentials in both directions, and maps failures to 502/503/504 rather than a bare 500. Point \`UPSTREAM_URL\` at the service you are wrapping."
        ;;
    cli:go)
        ENTRY_HINT="\`make build\` produces \`bin/$NAME\`; \`make run\` shows its help. Logic lives in \`internal/app\` with streams injected, so tests drive the whole program and assert exact bytes. \`make qa\` checks the contract scripts depend on: \`--help\` on stdout exiting 0, \`--version\`, a non-zero exit for a bad flag, and stdout matching \`testdata/*.golden\`."
        ;;
    model:*)
        ENTRY_HINT="\`make dataset && make preflight\` builds and validates the training corpus — both run in seconds with no GPU. \`make train\` fine-tunes a LoRA adapter (needs a GPU and the NVIDIA Container Toolkit), \`make merge\` produces a servable model, \`make serve\` starts vLLM behind an OpenAI-compatible API, and \`make evaluate && make qa\` scores it and gates on \`eval/thresholds.json\`."
        ;;
esac

KPI_README_LINE=""
if [[ $WITH_KPI -eq 1 ]]; then
    KPI_README_LINE="- **KPI collector/dashboard:** \`make dashboard\`"
fi

cat > README.md <<EOF
# $NAME

> One-line description of what this project does.
> **Shape:** \`$TYPE\` (see [STRATEGY.md](STRATEGY.md) and [AGENTS.md §0](AGENTS.md#0-project-shape-and-strategy))

## Quickstart

\`\`\`bash
# 1. Clone
git clone <repo-url> $NAME && cd $NAME

# 2. Configure
cp .env.example .env
# edit .env as needed

# 3. Validate the sandbox and build
make doctor
make setup

# 4. Run and verify
make run
make test
make qa
\`\`\`

$ENTRY_HINT

All project dependencies and checks run in Docker. The generated commands do
not install packages or change Git configuration on the host.

## Configuration

All configuration goes through environment variables in \`.env\`. See
\`.env.example\` for the full list.

## What this project is for

See [STRATEGY.md](STRATEGY.md) — it documents the problem, inputs, outputs,
success metric, and iteration loop. **Fill it in before writing code.**

## Monitoring

- **KPI definitions:** [kpi.json](kpi.json) (see [docs/KPI_SETUP.md](docs/KPI_SETUP.md))
- **E2E check:** [$QA_FILE]($QA_FILE)
- **Autoresearch loop:** [AUTORESEARCH.md](AUTORESEARCH.md)
$KPI_README_LINE

## Development

See [AGENTS.md](AGENTS.md) for conventions (network security, testing,
performance logging, secret handling, coding standards).
See [CONTRIBUTING.md](CONTRIBUTING.md) for PR workflow.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map.

## License

[$LICENSE_KIND](LICENSE)
EOF

# ── Makefile — shape-aware, Docker-only targets ───────────────────────────

RUN_CMD="$RUN_HINT"
HEALTH_CMD="$QA_DOCKER_CMD"

# The model shape has a workflow no other shape has: build a corpus, validate
# it, train on a GPU, merge, serve, evaluate, gate. Training and serving are
# behind Compose profiles so they are never part of `make setup`.
if [[ "$TYPE" == "model" ]]; then
    MODEL_HELP='	@echo "── Model pipeline ──────────────────"
	@echo "make dataset       — build train/val/eval splits from dataset/sources/"
	@echo "make preflight     — validate the corpus (schema, contract, leakage)"
	@echo "make train         — LoRA fine-tune (needs a GPU; builds the heavy image)"
	@echo "make merge         — adapter + base -> a servable model"
	@echo "make serve         — start vLLM behind an OpenAI-compatible API"
	@echo "make serve-down    — stop the server"
	@echo "make evaluate      — score the served model, write an eval report"'
    MODEL_TARGETS='
# ── Model pipeline ─────────────────────────────────────────────────────────
# dataset and preflight are light: no GPU, seconds, any machine. Run them
# constantly. train and serve need a GPU and are behind Compose profiles.

dataset:
	docker compose run --rm --no-deps --entrypoint python3 '"$NAME"' dataset/build.py

preflight:
	docker compose run --rm --no-deps --entrypoint python3 '"$NAME"' preflight.py

# Refuses to start on a bad corpus — see train.py. An hour of GPU time is an
# expensive way to discover something that takes two seconds to check.
train:
	@echo "building the training image (large, CUDA) — first run takes a while"
	docker compose --profile train build '"$NAME"'-train
	docker compose --profile train run --rm '"$NAME"'-train

merge:
	docker compose --profile train run --rm --entrypoint python3 '"$NAME"'-train merge.py $(if $(ADAPTER),--adapter $(ADAPTER),)

serve:
	docker compose --profile serve up -d '"$NAME"'-serve
	@echo "vLLM starting on http://127.0.0.1:$(SERVE_PORT) — first load takes a minute or two"
	@echo "follow it with: docker compose --profile serve logs -f '"$NAME"'-serve"

serve-down:
	docker compose --profile serve down --remove-orphans

evaluate:
	docker compose run --rm --no-deps --network host --entrypoint python3 '"$NAME"' evaluate.py $(if $(EVAL_ARGS),$(EVAL_ARGS),)
'
else
    MODEL_HELP=""
    MODEL_TARGETS=""
fi

# Tests run in the network-less sandbox by default, which is the right default:
# a unit test that reaches the network is usually a bug. WebRTC is the genuine
# exception — aioice discards a loopback-only host and gathers no candidates, so
# a `stream` project's own loopback tests cannot connect without an interface.
case "$TYPE" in
    stream) TEST_SANDBOX="SANDBOX_RUN_NET" ;;
    *)      TEST_SANDBOX="SANDBOX_RUN" ;;
esac

# Style-token check only exists for UI-bearing shapes; keep `make lint` honest
# rather than shipping a target that silently does nothing.
if (( HAS_STYLE_CHECK )); then
    STYLE_LINT_DEP=" check-styles"
    STYLE_TARGET=$'\ncheck-styles:\n\t@python3 scripts/check_styles.py\n'
    STYLE_HELP='	@echo "make check-styles  — every referenced CSS custom property resolves"'
else
    STYLE_LINT_DEP=""
    STYLE_TARGET=""
    STYLE_HELP=""
fi

cat > Makefile <<MAKEFILE
.PHONY: help doctor setup build build-test up down logs test qa metric lint format typecheck health run iterate iterate-bg stop-iterate dashboard clean \
        reindex reindex-full rag-search rag-stats \
        bot bot-check bot-logs bot-down bot-standalone \
        gitea gitea-runner gitea-bootstrap gitea-logs gitea-down gitea-nuke \
        review prs profile \
        memory-new memory-promote memory-promote-list memory-lint \
        check-env env-example check-locales check-clutter check-styles audit deadcode \
        code-review dataset preflight train merge serve serve-down evaluate \
        bench bench-baseline bench-compare \
        version changelog release refresh-agents \
        secrets-pull secrets-check secrets-diff monitor

# Operator-overridable paths to host-side tools.
AUTORESEARCH_RUNNER ?=
KPI_COLLECTOR ?=
DASHBOARD_URL ?= http://127.0.0.1:7133/dashboard

# Code review add-on. Pinned deliberately: a floating version makes today's
# review disagree with yesterday's for reasons unrelated to the code.
OCR_VERSION ?= 1.8.10
FAIL_ON ?= critical
FROM ?=

PORT ?= $PORT
PROJECT := $NAME
TEST_IMAGE ?= $NAME-test
HOST_UID ?= \$(shell id -u)
HOST_GID ?= \$(shell id -g)
# Tiny image used only by the doctor bind-mount probe.
PROBE_IMAGE ?= alpine:3.21
WITH_KPI := $WITH_KPI
WITH_RAG := $WITH_RAG
WITH_BOT := $WITH_BOT
WITH_GITEA := $WITH_GITEA
WITH_VAULT := $WITH_VAULT
WITH_MONITOR := $WITH_MONITOR
WITH_REVIEW := $WITH_REVIEW

# Version derives from git: a tagged commit gives "1.2.0", commits after a tag
# give "1.2.0-14-gabc1234", and a repo with no reachable tag gives
# "0.0.0-gabc1234". Release builds may override VERSION explicitly.
GIT_DESCRIBE := \$(shell git describe --tags --always --dirty 2>/dev/null)
ifeq (\$(strip \$(GIT_DESCRIBE)),)
VERSION ?= 0.0.0
else ifneq (,\$(findstring .,\$(GIT_DESCRIBE)))
VERSION ?= \$(GIT_DESCRIBE:v%=%)
else
VERSION ?= 0.0.0-g\$(GIT_DESCRIBE)
endif
GIT_REVISION := \$(shell git rev-parse HEAD 2>/dev/null || echo unknown)

SANDBOX_RUN = docker run --rm --read-only --cap-drop ALL \\
	--security-opt no-new-privileges --pids-limit 256 \\
	--network none --tmpfs /tmp:$SANDBOX_TMPFS_OPTIONS \\
	-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/.cache \\
	-e RUFF_CACHE_DIR=/tmp/ruff-cache -e MYPY_CACHE_DIR=/tmp/mypy-cache \\
	-e npm_config_cache=/tmp/npm-cache

# Same hardening, but with a network. Vulnerability and dead-code scanners
# have to reach an advisory database or a package registry, so \`--network
# none\` is not an option for them. Everything else — read-only rootfs, dropped
# capabilities, no-new-privileges, PID cap, bounded tmpfs — is unchanged, and
# these targets are never on the build path.
SANDBOX_RUN_NET = docker run --rm --read-only --cap-drop ALL \\
	--security-opt no-new-privileges --pids-limit 256 \\
	--tmpfs /tmp:$SANDBOX_TMPFS_OPTIONS \\
	-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/.cache \\
	-e PIP_CACHE_DIR=/tmp/pip-cache -e npm_config_cache=/tmp/npm-cache \\
	-e GOFLAGS=-mod=mod -e GOPATH=/tmp/go -e GOCACHE=/tmp/go-build

help:
	@echo "── Build / run ─────────────────────"
	@echo "make doctor        — validate Docker and project configuration"
	@echo "make setup         — validate and build runtime + test images"
	@echo "make build         — docker compose build"
	@echo "make run           — run the project (one-shot or start daemon)"
	@echo "make up            — alias for the shape-aware run target"
	@echo "make down          — docker compose down"
	@echo "make logs          — docker compose logs -f"
	@echo "── Test / health ───────────────────"
	@echo "make test          — run unit tests in an isolated test image"
	@echo "make qa            — run the end-to-end checker in Docker"
	@echo "make metric        — compute the project metric in Docker"
	@echo "make lint          — lint in the isolated test image"
	@echo "make format        — auto-format + safe lint fixes (rewrites files)"
	@echo "make typecheck     — type/syntax check in the isolated test image"
	@echo "make health        — shape-aware health probe"
	@echo "make profile       — explain the explicit debug override required for profiling"
$MODEL_HELP
	@echo "── Drift / supply chain ────────────"
	@echo "make check-env     — .env.example matches the config schema"
	@echo "make env-example   — regenerate .env.example from the config schema"
	@echo "make check-locales — every locale declares the same keys as en.json"
	@echo "make check-clutter — no scratch files at the repository root"
$STYLE_HELP
	@echo "make audit         — dependency vulnerability scan"
	@echo "make deadcode      — unused files, exports and dependencies"
	@echo "── Autoresearch ────────────────────"
	@echo "make iterate       — run autoresearch loop in foreground"
	@echo "make iterate-bg    — run autoresearch loop in background"
	@echo "make stop-iterate  — stop the background loop"
	@echo "── Performance ─────────────────────"
	@echo "make bench          — run declared benchmarks into bench/current/"
	@echo "make bench-baseline — capture a new committed baseline"
	@echo "make bench-compare  — diff current against baseline (never fails)"
	@echo "── Version / release ───────────────"
	@echo "make version       — print the version derived from git"
	@echo "make changelog     — draft the Unreleased section from commits"
	@echo "make release       — build a labelled, versioned artifact"
	@echo "make refresh-agents KIT=<path> — update the generated region of AGENTS.md"
	@echo "── KPIs ────────────────────────────"
	@echo "make dashboard     — KPI dashboard URL"
	@echo "── RAG / bot ───────────────────────"
	@echo "make reindex       — incremental RAG re-index"
	@echo "make reindex-full  — full RAG rebuild"
	@echo "make rag-search Q=\"...\" — search the index"
	@echo "make rag-stats     — show RAG index stats"
	@echo "make bot           — start the project bot (fails if it crash-loops)"
	@echo "make bot-check     — report which bot tools and settings are configured"
	@echo "make bot-logs      — follow bot logs"
	@echo "make bot-down      — stop the bot"
	@echo "make bot-standalone — run bot in foreground on the host (needs bot/requirements.txt)"
	@echo "── Memory ──────────────────────────"
	@echo "make memory-new CATEGORY=x NAME=y — create a new memory file"
	@echo "make memory-promote-list — list memories pending promotion"
	@echo "make memory-promote — push approved memories to long-term store"
	@echo "make memory-lint    — validate memory frontmatter"
	@echo "── Secrets (Vault add-on) ──────────"
	@echo "make secrets-pull  — fetch mapped secrets from Vault into .env"
	@echo "make secrets-check — verify every mapped secret resolves (names only)"
	@echo "make secrets-diff  — which local values differ from Vault, by name"
	@echo "── Code review add-on ──────────────"
	@echo "make code-review   — AI review of the current diff (FROM=<ref> FAIL_ON=<sev>)"
	@echo "── Monitoring add-on ───────────────"
	@echo "make monitor       — probe /health and every HTTP KPI once"
	@echo "── Per-project Gitea + PR review ───"
	@echo "make gitea          — start the project's Gitea container"
	@echo "make gitea-runner   — opt in to Docker-socket CI runner (host-level trust)"
	@echo "make gitea-bootstrap — first-run: create bot user + token + repo"
	@echo "make gitea-logs     — follow Gitea logs"
	@echo "make gitea-down     — stop Gitea (data preserved)"
	@echo "make gitea-nuke     — WIPE gitea data (destructive)"
	@echo "make prs            — list open PRs"
	@echo "make review PR=<n>  — trigger the review agent on a PR"
	@echo "── Cleanup ─────────────────────────"
	@echo "make clean         — remove generated outputs/state"

doctor:
	@command -v docker >/dev/null 2>&1 || { echo "docker is required"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Docker daemon is not reachable"; exit 1; }
	@test -f .env || { echo ".env is missing; copy .env.example to .env"; exit 1; }
	@docker compose config --quiet
	@if docker compose config | grep -Eq 'host_ip: 0\\.0\\.0\\.0'; then \
		echo "refusing non-loopback published port"; exit 1; \
	fi
	@# Can a container actually write to a bind mount owned by this user?
	@# Probed rather than inferred: user-namespace remapping, rootless Docker and
	@# SELinux all break this the same way, and the symptom is a bare
	@# PermissionError deep in the app rather than anything mentioning Docker.
	@# Mirror whatever the project's own compose config does, so applying the
	@# suggested fix actually makes this pass. A probe that tests something the
	@# project does not do reports a problem the user has already solved.
	@probe="\$\$(mktemp -d)"; \
	userns=""; \
	if docker compose config 2>/dev/null | grep -q 'userns_mode: *host'; then \
		userns="--userns=host"; \
	fi; \
	if docker run --rm \$\$userns --user "\$(HOST_UID):\$(HOST_GID)" -v "\$\$probe":/probe \
		\$(PROBE_IMAGE) sh -c 'touch /probe/.w' >/dev/null 2>&1; then \
		rm -rf "\$\$probe"; \
	else \
		seen="\$\$(docker run --rm \$\$userns -v "\$\$probe":/probe \$(PROBE_IMAGE) stat -c '%u' /probe 2>/dev/null)"; \
		rm -rf "\$\$probe"; \
		echo "ERROR: this Docker daemon cannot write to a bind mount owned by uid \$(HOST_UID)."; \
		echo "       Inside a container that directory appears as uid \$\$seen."; \
		echo ""; \
		echo "       This is almost always user-namespace remapping — check 'docker info'"; \
		echo "       for 'Docker Root Dir: /var/lib/docker/<n>.<n>'. Container uid"; \
		echo "       \$(HOST_UID) maps to a different host uid, so data/, outputs/ and"; \
		echo "       results/ are not writable and the app dies with a bare PermissionError."; \
		echo ""; \
		echo "       Fix it in docker-compose.override.yml (gitignored, host-specific):"; \
		echo ""; \
		echo "           services:"; \
		echo "             \$(PROJECT):"; \
		echo "               userns_mode: host"; \
		echo ""; \
		echo "       That opts this one service out of remapping. The container still"; \
		echo "       runs non-root with dropped capabilities and a read-only rootfs, so"; \
		echo "       the loss is real but bounded. See docs/SETUP.md."; \
		exit 1; \
	fi
	@echo "sandbox configuration looks ready"

setup: doctor build build-test

# VERSION is exported so Compose can substitute it into the build args, which
# reach the image as APP_VERSION and come back out of /health.
build:
	VERSION="\$(VERSION)" docker compose build

build-test:
	docker build --target test --build-arg VERSION="\$(VERSION)" -t \$(TEST_IMAGE) .

run:
	VERSION="\$(VERSION)" $RUN_CMD

up: run

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f

test: build-test
	\$($TEST_SANDBOX) \$(TEST_IMAGE)

qa:
	$QA_DOCKER_CMD

metric:
	$METRIC_DOCKER_CMD

lint: build-test check-locales check-clutter$STYLE_LINT_DEP
	\$(SANDBOX_RUN) \$(TEST_IMAGE) sh -lc '$LINT_CMD'
$STYLE_TARGET

typecheck: build-test
	\$(SANDBOX_RUN) \$(TEST_IMAGE) sh -lc '$TYPECHECK_CMD'

# Rewrites files, so it mounts the working tree (like env-example). Still no
# network. Run it before \`make lint\` instead of hand-rolling a docker run.
format: build-test
	docker run --rm --cap-drop ALL --security-opt no-new-privileges \\
		--network none --pids-limit 256 \\
		-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/.cache -e RUFF_CACHE_DIR=/tmp/ruff \\
		-v "\$(CURDIR)":/work -w /work \\
		--user "\$\$(id -u):\$\$(id -g)" \\
		\$(TEST_IMAGE) sh -lc '$FORMAT_CMD'

# ── Drift checks ───────────────────────────────────────────────────────────
# Three failure modes lint and typecheck structurally cannot see: a locale
# missing a key, an .env.example that no longer matches the code, and scratch
# files piling up at the root. All three are cheap, so they run every time.

check-locales:
	@python3 scripts/check_locales.py

check-clutter:
	@python3 scripts/check_root_clutter.py

check-env: build-test
	\$(SANDBOX_RUN) \$(TEST_IMAGE) sh -lc 'python3 scripts/check_env.py'

# Writes into the working tree, so it mounts it. Still no network.
env-example: build-test
	docker run --rm --cap-drop ALL --security-opt no-new-privileges \\
		--network none --pids-limit 256 \\
		-e HOME=/tmp -v "\$(CURDIR)":/work -w /work \\
		--user "\$\$(id -u):\$\$(id -g)" \\
		\$(TEST_IMAGE) sh -lc 'python3 scripts/check_env.py --write'

# ── Supply chain ───────────────────────────────────────────────────────────
# Both need a network (advisory database, package registry), so they use the
# networked sandbox. Neither is on the build path.

audit: build-test
	\$(SANDBOX_RUN_NET) \$(TEST_IMAGE) sh -lc '$AUDIT_CMD'

deadcode: build-test
	@echo "findings are advisory — tune the ignore list in $DEADCODE_IGNORE_NOTE"
	@\$(SANDBOX_RUN_NET) \$(TEST_IMAGE) sh -lc '$DEADCODE_CMD'

health:
	@$HEALTH_CMD || echo "health probe failed"

# Profilers require ptrace, which is intentionally absent from the default
# sandbox. Keep any debug override explicit and short-lived.

profile:
	@echo "profiling is disabled in the least-privilege runtime sandbox"
	@echo "use a temporary, reviewed Compose override that grants only SYS_PTRACE"
	@echo "and remove it immediately after profiling"
	@exit 2

iterate:
	@if [ -z "\$(AUTORESEARCH_RUNNER)" ]; then \\
		echo "AUTORESEARCH_RUNNER env var not set"; \\
		echo "  export AUTORESEARCH_RUNNER=/path/to/runner.py"; \\
		exit 1; \\
	fi
	@if [ ! -f "\$(AUTORESEARCH_RUNNER)" ]; then \\
		echo "autoresearch runner not found at \$(AUTORESEARCH_RUNNER)"; exit 1; \\
	fi
	python3 "\$(AUTORESEARCH_RUNNER)"

iterate-bg:
	@if [ -z "\$(AUTORESEARCH_RUNNER)" ] || [ ! -f "\$(AUTORESEARCH_RUNNER)" ]; then \\
		echo "AUTORESEARCH_RUNNER not set or not found — see 'make iterate'"; exit 1; \\
	fi
	@nohup python3 "\$(AUTORESEARCH_RUNNER)" --iterations 0 > autoresearch.log 2>&1 & \\
		echo "started — tail -f autoresearch.log to watch"

stop-iterate:
	@touch STOP_AUTORESEARCH
	@echo "stop signal placed — loop will exit after current iteration"

# ── Performance ────────────────────────────────────────────────────────────
# metric.sh answers "how good is it now". These answer "is it worse than it
# was" — a different question, and the one a fresh project cannot otherwise
# answer at all.

bench:
	@python3 scripts/bench_run.py

bench-baseline:
	@python3 scripts/bench_run.py --out bench/baseline
	@echo "baseline captured — commit bench/baseline/ so it means something later"

# Always exits 0. Timing on shared runners is noisy enough that a hard gate
# fires on unrelated load within a week, and a check that cries wolf gets
# deleted. Gate on the JSON in a separate, deliberately-tuned job if you want
# enforcement.
bench-compare:
	@python3 scripts/bench_compare.py

# ── Version / release ──────────────────────────────────────────────────────

version:
	@echo "\$(VERSION)"

# Drafts the Unreleased section from Conventional Commits since the last tag.
# Hand-maintained changelogs decay; a derived one is merely occasionally
# imprecise, which is a much better failure mode.
changelog:
	@last="\$\$(git describe --tags --abbrev=0 2>/dev/null || true)"; \\
	range="\$\$last..HEAD"; [ -n "\$\$last" ] || range=HEAD; \\
	echo "## [Unreleased]"; echo ""; \\
	for kind in feat:Added fix:Fixed perf:Changed refactor:Changed docs:Changed build:Changed; do \\
		prefix="\$\${kind%%:*}"; heading="\$\${kind##*:}"; \\
		body="\$\$(git log --no-merges --pretty=format:'- %s' "\$\$range" 2>/dev/null \\
			| sed -n "s/^- \$\$prefix\\(([^)]*)\\)\\?: /- /p")"; \\
		[ -n "\$\$body" ] || continue; \\
		echo "### \$\$heading"; echo "\$\$body"; echo ""; \\
	done
	@echo "(paste the above into CHANGELOG.md under [Unreleased])"

# Builds a versioned, OCI-labelled image and saves it as a tarball. Defaults
# to a local artifact rather than a registry push so \`make release\` needs no
# credentials and no network — decide to publish deliberately, not by default.
release: build
	@mkdir -p dist
	docker build \\
		--build-arg VERSION="\$(VERSION)" \\
		--label org.opencontainers.image.version="\$(VERSION)" \\
		--label org.opencontainers.image.revision="\$(GIT_REVISION)" \\
		--label org.opencontainers.image.title="$NAME" \\
		--label org.opencontainers.image.licenses="$LICENSE_KIND" \\
		-t "$NAME:\$(VERSION)" -t "$NAME:latest" .
	docker save "$NAME:\$(VERSION)" -o "dist/$NAME-\$(VERSION).tar"
	@cd dist && sha256sum "$NAME-\$(VERSION).tar" > "$NAME-\$(VERSION).tar.sha256"
	@echo "release artifact: dist/$NAME-\$(VERSION).tar (+ .sha256)"

# Updates only the region of AGENTS.md between the scaffold markers; your own
# sections are never touched.
refresh-agents:
	@if [ -z "\$(KIT)" ]; then \\
		echo "usage: make refresh-agents KIT=/path/to/yala-scaffold"; exit 1; \\
	fi
	@python3 scripts/refresh_agents.py --from "\$(KIT)"

dashboard:
	@if [ "\$(WITH_KPI)" != "1" ]; then echo "KPI add-on not enabled; scaffold with --with-kpi"; exit 2; fi
	@echo "Dashboard: \$(DASHBOARD_URL)?project=$NAME"
	@curl -s "\$(DASHBOARD_URL)?project=$NAME&format=json" 2>/dev/null | python3 -m json.tool 2>/dev/null | head -50 || \\
		echo "(dashboard not reachable — only available in upstream operator environment)"

# ── RAG / bot (AGENTS.md §22) ───────────────────────────────────────────────

reindex:
	@if [ "\$(WITH_RAG)" != "1" ]; then echo "RAG add-on not enabled; scaffold with --with-rag"; exit 2; fi
	@python3 rag/index.py --incremental || python3 rag/index.py

reindex-full:
	@if [ "\$(WITH_RAG)" != "1" ]; then echo "RAG add-on not enabled; scaffold with --with-rag"; exit 2; fi
	@python3 rag/index.py

rag-search:
	@if [ "\$(WITH_RAG)" != "1" ]; then echo "RAG add-on not enabled; scaffold with --with-rag"; exit 2; fi
	@if [ -z "\$(Q)" ]; then echo 'usage: make rag-search Q="your query"'; exit 1; fi
	@python3 rag/index.py --search "\$(Q)"

rag-stats:
	@if [ "\$(WITH_RAG)" != "1" ]; then echo "RAG add-on not enabled; scaffold with --with-rag"; exit 2; fi
	@python3 rag/index.py --stats

bot:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "bot add-on not enabled; scaffold with --with-bot"; exit 2; fi
	@test -f .env || { echo ".env is missing; copy .env.example to .env"; exit 1; }
	@grep -qE '^IRC_SERVER=.+' .env || { \
		echo "IRC_SERVER is not set in .env — the bot needs an IRC server to connect to."; \
		echo "Without it the container starts, fails, and is restarted forever."; \
		echo "See bot/README.md, or run 'make bot-check' to see what else is missing."; \
		exit 1; \
	}
	@docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml up -d $NAME-bot
	@# \`up -d\` returning 0 only means the container was created. Confirm it is
	@# still alive a moment later, or a crash-loop reports itself as success.
	@sleep 5
	@state="\$\$(docker inspect -f '{{.State.Status}}' $NAME-bot 2>/dev/null)"; \
	restarts="\$\$(docker inspect -f '{{.RestartCount}}' $NAME-bot 2>/dev/null)"; \
	if [ "\$\$state" != "running" ] || [ "\$\$restarts" -gt 0 ] 2>/dev/null; then \
		echo "bot is NOT healthy (state=\$\$state restarts=\$\$restarts)"; \
		echo "--- last log lines ---"; \
		docker logs --tail 15 $NAME-bot 2>&1 | sed 's/^/  /'; \
		exit 1; \
	fi
	@echo "bot running — tail logs with: make bot-logs"

bot-check:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "bot add-on not enabled; scaffold with --with-bot"; exit 2; fi
	@python3 bot/bot.py --check

bot-logs:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "bot add-on not enabled; scaffold with --with-bot"; exit 2; fi
	@docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml logs -f $NAME-bot

bot-down:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "bot add-on not enabled; scaffold with --with-bot"; exit 2; fi
	@docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml stop $NAME-bot 2>/dev/null || true
	@docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml rm -f $NAME-bot 2>/dev/null || true
	@echo "bot stopped"

bot-standalone:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "bot add-on not enabled; scaffold with --with-bot"; exit 2; fi
	@# Unlike every other target, this one runs on the HOST, so it needs
	@# bot/requirements.txt available here. Say so plainly rather than failing
	@# on an ImportError three frames deep.
	@python3 -c 'import httpx, yaml, dotenv' 2>/dev/null || { \
		echo "bot-standalone runs on the host and needs its dependencies here:"; \
		echo "    pip install -r bot/requirements.txt"; \
		echo "Or use 'make bot', which runs it in a container with no host installs."; \
		exit 1; \
	}
	@echo "starting bot in foreground (ctrl-c to exit)…"
	@python3 bot/bot.py

# ── Secrets (Vault add-on) ─────────────────────────────────────────────────
# These run on the HOST, not in a container: the AppRole credentials live in
# \$VAULT_CREDS_DIR outside the project, and mounting them into a container to
# read a secret would be a longer path to the same place with more ways to
# leak. None of these targets ever print a secret value.

secrets-pull:
	@if [ "\$(WITH_VAULT)" != "1" ]; then echo "Vault add-on not enabled; scaffold with --with-vault"; exit 2; fi
	@./vault/pull.sh

secrets-check:
	@if [ "\$(WITH_VAULT)" != "1" ]; then echo "Vault add-on not enabled; scaffold with --with-vault"; exit 2; fi
	@./vault/check.sh

secrets-diff:
	@if [ "\$(WITH_VAULT)" != "1" ]; then echo "Vault add-on not enabled; scaffold with --with-vault"; exit 2; fi
	@./vault/check.sh --diff

$MODEL_TARGETS
# ── Code review add-on ─────────────────────────────────────────────────────
# Runs in a container, so no host Node is needed. Reads OCR_LLM_* from .env.
# FROM defaults to the working tree (staged + unstaged); set it to a ref to
# review a whole branch. FAIL_ON defaults to critical — see review/README.md
# for why a stricter default gets the check disabled instead of obeyed.

code-review:
	@if [ "\$(WITH_REVIEW)" != "1" ]; then echo "review add-on not enabled; scaffold with --with-review"; exit 2; fi
	@test -f .env || { echo ".env is missing; copy .env.example to .env"; exit 1; }
	@docker run --rm --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --env-file .env -e HOME=/tmp -e OCR_VERSION="\$(OCR_VERSION)" -e OCR_FROM="\$(FROM)" -v "\$(CURDIR)":/src -w /src node:20 sh review/run.sh
	@python3 review/gate.py .ocr/result.json --fail-on "\$(FAIL_ON)"

# ── Monitoring add-on ──────────────────────────────────────────────────────

monitor:
	@if [ "\$(WITH_MONITOR)" != "1" ]; then echo "monitor add-on not enabled; scaffold with --with-monitor"; exit 2; fi
	@python3 monitor/probe.py --base-url "http://127.0.0.1:\$(PORT)"

# ── Per-project Gitea (AGENTS.md §24) ──────────────────────────────────────

gitea:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@docker compose -f docker-compose.yml -f gitea/docker-compose.gitea.yml up -d $NAME-gitea
	@echo "gitea started — visit http://127.0.0.1:\$(or \$(GITEA_HTTP_PORT),3030) once healthy"
	@echo "next: make gitea-bootstrap"

gitea-runner:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@echo "WARNING: the Actions runner mounts /var/run/docker.sock and has host-level Docker control."
	@echo "Only continue for trusted workflows and actions."
	@docker compose --profile ci-runner -f docker-compose.yml -f gitea/docker-compose.gitea.yml up -d $NAME-act-runner

gitea-bootstrap:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@./gitea/bootstrap.sh

gitea-logs:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@docker compose -f docker-compose.yml -f gitea/docker-compose.gitea.yml logs -f $NAME-gitea

gitea-down:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@docker compose --profile ci-runner -f docker-compose.yml -f gitea/docker-compose.gitea.yml stop $NAME-act-runner $NAME-gitea 2>/dev/null || true
	@docker compose --profile ci-runner -f docker-compose.yml -f gitea/docker-compose.gitea.yml rm -f $NAME-act-runner $NAME-gitea 2>/dev/null || true
	@echo "gitea stopped (data preserved in gitea/data/)"

gitea-nuke:
	@if [ "\$(WITH_GITEA)" != "1" ]; then echo "Gitea add-on not enabled; scaffold with --with-gitea"; exit 2; fi
	@read -p "This will DELETE gitea/data/ — sure? [y/N] " c; [ "\$\$c" = "y" ] || exit 1
	@docker compose --profile ci-runner -f docker-compose.yml -f gitea/docker-compose.gitea.yml down -v 2>/dev/null || true
	@rm -rf gitea/data
	@echo "gitea data wiped"

review:
	@if [ "\$(WITH_BOT)" != "1" ] || [ "\$(WITH_GITEA)" != "1" ]; then echo "review requires --with-bot and --with-gitea"; exit 2; fi
	@if [ -z "\$(PR)" ]; then \\
		echo "usage: make review PR=<number>"; exit 1; \\
	fi
	@python3 -c "import sys; sys.path.insert(0, 'bot'); from tools import review_pr; print(review_pr.call('\$(PR)', {'project': '$NAME'}))"

prs:
	@if [ "\$(WITH_BOT)" != "1" ] || [ "\$(WITH_GITEA)" != "1" ]; then echo "prs requires --with-bot and --with-gitea"; exit 2; fi
	@python3 -c "import sys; sys.path.insert(0, 'bot'); from tools import gitea; print(gitea.call('list_prs', {'project': '$NAME'}))"

# ── Memory (AGENTS.md §23) ──────────────────────────────────────────────────

memory-new:
	@if [ "\$(WITH_BOT)" != "1" ]; then echo "memory-new requires --with-bot"; exit 2; fi
	@if [ -z "\$(CATEGORY)" ] || [ -z "\$(NAME)" ]; then \\
		echo "usage: make memory-new CATEGORY=decision|experiment|bug|feedback NAME=\"short-title\""; \\
		exit 1; \\
	fi
	@python3 -c "import sys; sys.path.insert(0, 'bot'); from tools import write_memory; print(write_memory.call('category=\$(CATEGORY); title=\$(NAME); body=TODO-edit-me', {'project': '$NAME'}))"

memory-promote-list:
	@python3 scripts/check_memory.py --pending

memory-promote:
	@if [ -z "\$\$MEMORY_STORE_URL" ]; then \\
		echo "MEMORY_STORE_URL not set — cannot promote"; exit 1; \\
	fi
	@python3 scripts/check_memory.py --promote --store "\$\$MEMORY_STORE_URL" --project "$NAME"

memory-lint:
	@python3 scripts/check_memory.py

clean:
	@docker compose down --remove-orphans 2>/dev/null || true
	@docker image rm "\$(TEST_IMAGE)" >/dev/null 2>&1 || true
	@docker image rm "$NAME:latest" >/dev/null 2>&1 || true
	@find outputs state results -mindepth 1 ! -name .gitkeep -delete 2>/dev/null || true
	@rm -f autoresearch.log qa_check_output.txt qa_check_output.json
	@echo "cleaned generated artifacts"
MAKEFILE

# ── .gitignore — shape-aware (adds outputs/ / state/ / fixtures rules) ─────

cat > .gitignore <<'EOF'
# ── Secrets — NEVER COMMIT ─────────────────────
.env
.env.local
.env.*.local
*.key
*.pem
*.p12
secrets/
credentials/

# ── Operator-only files ────────────────────────
LOCAL.md
# Host-specific docker-compose overrides (networks, extra_hosts, bind
# mounts). Edit this file — not docker-compose.yml — for operator wiring.
# See docs/LOCAL.md for the pattern.
docker-compose.override.yml

# ── Logs ───────────────────────────────────────
*.log
logs/*
!logs/.gitkeep

# ── Python ─────────────────────────────────────
__pycache__/
*.pyc
*.pyo
*.pyd
*.egg-info/
*.egg
.venv/
venv/
env/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/

# ── Node ───────────────────────────────────────
node_modules/
.next/
.nuxt/
.cache/
.turbo/

# ── Editors / OS ───────────────────────────────
.vscode/
.idea/
*.swp
*.swo
.DS_Store
Thumbs.db

# ── Project state / data ───────────────────────
*.db
*.sqlite
*.sqlite3
data/*
!data/.gitkeep
results/*
!results/.gitkeep

# ── Generated outputs (PDFs, graphs, xlsx, parquet) ──
outputs/*
!outputs/.gitkeep

# ── Pipeline intermediate state ────────────────
state/*
!state/.gitkeep

# ── Autoresearch loop state ────────────────────
results.tsv
metric.log
autoresearch.log
STOP_AUTORESEARCH
STOP_WORKER
qa_check_output.txt

# ── KPI collector state ────────────────────────
kpi-collector.log
data/kpis.jsonl

# ── RAG index + bot state ──────────────────────
data/rag.sqlite*
data/bot-heartbeat
logs/agent-*.log
qa_check_output.json

# ── Memory: pre-flight briefs are transient per-dispatch ────
memory/_relevant-for-*.md

# ── Gitea: SQLite DB + git repos + logs + runner state stay local ──
# runner-data/ contains the act_runner registration token in plaintext
# and MUST never be committed — gitleaks will flag it as a leaked secret.
gitea/data/
gitea/runner-data/

# ── Scratch space ──────────────────────────────────
# One-off diagnostics, throwaway scripts, scratch data. Every project grows
# these; giving them a home is what keeps them out of the repo root. Nothing
# here is ever committed, so nothing here can be depended on.
scratch/

# ── Vault: tokens and AppRole material never leave the host ──
# secret-map.tsv IS committed — it holds names and paths, never values.
vault/.token
vault/*.secret-id
vault/*.role-id
.env.vault

# ── Benchmarks: baseline is committed, runs are not ──
# bench/baseline/ is deliberately NOT ignored: without a committed baseline
# there is nothing to regress against.
bench/current/
bench/reports/

# ── Monitor add-on probe log ───────────────────────
data/probes.jsonl

# ── Code review add-on ─────────────────────────────
# .ocr/ holds review output; review/vendor/ holds the third-party GitLab
# publisher fetched by review/fetch_poster.sh. Neither is this project's
# source, and the publisher is re-fetchable and checksum-verified, so
# committing a copy would only create something to go stale.
.ocr/
review/vendor/

# ── Model training artifacts (shape: model) ────────
# Adapters are tens of MB and merged models are tens of GB. Neither belongs in
# git. eval/reports/ is deliberately NOT ignored: a committed report is the
# evidence a model cleared its thresholds, and CI gates on it.
output/
data/huggingface/
*.safetensors
*.gguf

# ── Godot / game build output ──────────────────────
# .godot/ is the engine's import cache: regenerated on demand, machine-specific.
# builds/ holds exported binaries, which are large and reproducible.
.godot/
builds/*
!builds/.gitkeep
*.translation

# ── Browser automation debugging output ────────────
# Screenshots, page HTML and traces from failed steps. Regenerated on every
# failure, so there is nothing to preserve.
artifacts/*
!artifacts/.gitkeep

# ── Release artifacts ──────────────────────────────
dist/

# ── Jupyter checkpoints ────────────────────────
.ipynb_checkpoints/
EOF

# Ensure writable bind-mount directories exist before Docker starts. Tracking
# sentinels prevents Docker from creating root-owned directories after clone.
mkdir -p outputs
touch outputs/.gitkeep
case "$TYPE" in
    service|worker|image)
        mkdir -p data
        touch data/.gitkeep
        ;;
    analysis)
        mkdir -p data results
        touch data/.gitkeep results/.gitkeep
        ;;
    backtest)
        mkdir -p results
        touch results/.gitkeep
        ;;
    report)
        mkdir -p assets
        touch assets/.gitkeep
        ;;
    notebook)
        mkdir -p data
        touch data/.gitkeep
        ;;
    pipeline)
        mkdir -p state
        touch state/.gitkeep
        ;;
    scraper)
        mkdir -p outputs
        touch outputs/.gitkeep
        ;;
    agent)
        # eval/reports/ holds live-model evaluation runs; committed reports are
        # the evidence a prompt or model change did not regress.
        mkdir -p eval/reports logs
        touch eval/reports/.gitkeep logs/.gitkeep
        ;;
    mcp|cli)
        mkdir -p data
        touch data/.gitkeep
        ;;
    bridge|stream|audio)
        mkdir -p data logs
        touch data/.gitkeep logs/.gitkeep
        ;;
    game)
        # builds/ holds exported game binaries (large, gitignored).
        mkdir -p builds logs
        touch builds/.gitkeep logs/.gitkeep
        ;;
    browser)
        # artifacts/ holds screenshots, page HTML and traces from failed steps.
        # Gitignored: they are debugging output, regenerated on every failure.
        mkdir -p artifacts logs
        touch artifacts/.gitkeep logs/.gitkeep
        ;;
    model)
        # output/ holds adapters and merged models (large, gitignored);
        # eval/reports/ holds committed evaluation reports.
        mkdir -p data output eval/reports
        touch data/.gitkeep output/.gitkeep eval/reports/.gitkeep
        ;;
esac
if [[ $WITH_BOT -eq 1 ]]; then
    mkdir -p data logs
    touch data/.gitkeep logs/.gitkeep
fi

# ── scratch/ — somewhere for one-off diagnostics to live ──────────────────
# Debug scripts get written under delivery pressure whether or not there is a
# place for them. Providing one is what keeps them out of the repo root and
# out of history; scripts/check_root_clutter.py enforces the other half.
mkdir -p scratch
cat > scratch/README.md <<'EOF'
# scratch/

Throwaway space. **Nothing here is committed** — the whole directory is
gitignored.

Put one-off diagnostics, scratch data, half-finished scripts and
`tmp_check_that_thing.py` here. That is not a failure of discipline; every
real project accumulates them. The failure is leaving them at the repository
root, where six months later nobody can tell which files matter and every
tool has to be configured to ignore them.

Because it is gitignored, nothing here can be depended on: not by CI, not by
the Makefile, not by a teammate. When something in here becomes load-bearing,
that is the signal to move it into `scripts/` with a test and a docstring.

`make check-clutter` fails the build if scratch-looking files appear at the
root instead of here.
EOF

# ── bench/ — performance baseline and current runs ────────────────────────
mkdir -p bench/baseline bench/current
touch bench/baseline/.gitkeep

case "$TYPE" in
    service|image|webapp|notebook)
        BENCH_DECLARATIONS='    {
      "name": "health",
      "command": "curl -sf http://127.0.0.1:'"$PORT"'/health -o /dev/null",
      "iterations": 30,
      "requires_running": true,
      "requires_hint": "the service is not answering — run `make run` first",
      "note": "End-to-end request latency."
    },
    {
      "name": "config_load",
      "command": "'"$CONFIG_CHECK_CMD"' >/dev/null",
      "iterations": 20,
      "note": "Startup configuration parse + validate cost."
    }'
        ;;
    tui)
        BENCH_DECLARATIONS='    {
      "name": "render",
      "command": "./bin/'"$NAME"' --demo > /dev/null",
      "iterations": 30,
      "requires_running": true,
      "requires_hint": "binary not built — run `make build` first",
      "note": "One non-interactive frame render."
    },
    {
      "name": "config_load",
      "command": "'"$CONFIG_CHECK_CMD"' >/dev/null",
      "iterations": 20,
      "note": "Startup configuration parse + validate cost."
    }'
        ;;
    *)
        BENCH_DECLARATIONS='    {
      "name": "config_load",
      "command": "'"$CONFIG_CHECK_CMD"' >/dev/null",
      "iterations": 20,
      "note": "Startup configuration parse + validate cost."
    }'
        ;;
esac

cat > bench/benchmarks.json <<EOF
{
  "\$comment": [
    "Benchmarks for $NAME, declared as data so adding one never means editing",
    "scripts/bench_run.py. Each is run 'iterations' times (plus one untimed",
    "warmup) and reduced to min/p50/p95/max/mean.",
    "",
    "These starters measure the scaffold, not your project. Replace them with",
    "the operations whose latency you would actually notice getting worse —",
    "a benchmark that never moves teaches nobody anything.",
    "",
    "  make bench           run into bench/current/",
    "  make bench-baseline  capture bench/baseline/ (commit it)",
    "  make bench-compare   diff the two"
  ],
  "benchmarks": [
$BENCH_DECLARATIONS
  ]
}
EOF

cat > bench/README.md <<EOF
# Benchmarks

\`metric.sh\` answers *how good is it right now*. This answers *is it worse
than it was* — a different question, and one nothing else here tracks.

| Directory | Committed? | Holds |
|---|---|---|
| \`baseline/\` | **yes** | The reference run everything is compared against. |
| \`current/\` | no | The most recent run. |
| \`reports/\` | no | Dated comparison reports. |

\`baseline/\` is committed on purpose: a baseline that lives only on the
machine that produced it cannot detect a regression introduced on another one.

## Use

\`\`\`bash
make bench-baseline   # once, on a quiet machine, then commit bench/baseline/
make bench            # after a change
make bench-compare    # see the delta
\`\`\`

\`make bench-compare\` **always exits 0.** A regression prints \`⚠ WARN\` and
sets \`"regression": true\` in the report, but never fails the build — timings
on shared runners are noisy enough that a hard gate fires on unrelated load
within a week, and a check that cries wolf gets deleted rather than fixed. If
you want enforcement, gate on the report JSON in a separate job you have tuned
against real variance.

Re-capture the baseline deliberately, when a change is *meant* to move the
numbers, and say so in the commit message.
EOF
if (( INVOKING_UID == 0 )); then
    for writable_dir in data outputs results state notebooks logs; do
        [[ -d "$writable_dir" ]] || continue
        chown -R "$HOST_UID:$HOST_GID" "$writable_dir"
    done
fi

# ── .dockerignore — keep build contexts lean + avoid permission errors ────
# The bot's docker build context is the project root (so it can COPY the
# whole project in). Without this, root-owned directories like gitea/data/
# and the runner's cache would break `docker build` with "permission denied".

cat > .dockerignore <<'EOF'
# Secrets & local state (never leak into image layers)
.env
.env.local
.env.*.local
.secrets
secrets/
*.pem
*.key

# Per-project Gitea (root-owned at runtime — would fail docker build)
gitea/data/
gitea/runner-data/

# Build / test artifacts
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
node_modules/
dist/
build/
.vite/
.turbo/

# IDE
.vscode/
.idea/
.DS_Store

# Project-local generated content
outputs/
data/
logs/
results/
.autoresearch/
autoresearch.log

# Memory store (project-local, not needed in image)
memory/*/*.md
!memory/SCHEMA.md

# Scratch space, benchmark runs and review output — never belong in a layer
scratch/
.ocr/
review/vendor/
bench/current/
bench/reports/
dist/

# Vault credentials must never reach a build context
vault/.token
vault/*.secret-id
vault/*.role-id

# Git internals
.git/
EOF

# ── OPERATOR-ONLY FILES (gitignored) ──────────────────────────────────────

fill "$TPL/LOCAL_TEMPLATE.md" > LOCAL.md
cp .env.example .env

# ── git init + initial commit ─────────────────────────────────────────────

git init -q --initial-branch=main
git add -A
GIT_AUTHOR_NAME="$(git config --get user.name || true)"
GIT_AUTHOR_EMAIL="$(git config --get user.email || true)"
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-Yala Scaffold}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-yala@localhost.invalid}"
git -c user.name="$GIT_AUTHOR_NAME" -c user.email="$GIT_AUTHOR_EMAIL" commit -q -m "Bootstrap $NAME ($TYPE shape)

Generated-by: yala-scaffold"

# Leak check — no absolute operator paths or private hostnames in committed files
LEAKS=$(git ls-files | xargs grep -l "$HOME" 2>/dev/null || true)
if [[ -n "$LEAKS" ]]; then
    echo ""
    echo "[scaffold] WARNING — $HOME references found in committed files:"
    echo "$LEAKS"
    echo "[scaffold] These must be removed before pushing publicly."
fi

if [[ "$SCAFFOLD_DOMAIN" != "example.local" ]]; then
    HOSTNAME_LEAKS=$(git ls-files | xargs grep -l "$SCAFFOLD_DOMAIN" 2>/dev/null || true)
    if [[ -n "$HOSTNAME_LEAKS" ]]; then
        echo ""
        echo "[scaffold] WARNING — $SCAFFOLD_DOMAIN hostname references in committed files:"
        echo "$HOSTNAME_LEAKS"
    fi
fi

SCAFFOLD_COMPLETE=1

echo "[scaffold] done — $PROJ"
echo ""
echo "Shape: $TYPE (lang: $LANG)"
echo ""
echo "Public files (committed):"
echo "  README.md, AGENTS.md, STRATEGY.md, CONTRIBUTING.md, CHANGELOG.md, LICENSE"
echo "  Dockerfile, docker-compose.yml, .env.example"
if [[ "$LANG" == "node" ]]; then
    echo "  package.json, src/ (entry point)"
elif [[ "$LANG" == "go" ]]; then
    if [[ "$TYPE" == "cli" ]]; then
        echo "  go.mod, cmd/cli/ (entry point), internal/app/ (logic), testdata/ (golden files)"
    else
        echo "  go.mod, go.sum, cmd/tui/ (entry point)"
    fi
else
    echo "  requirements.txt, requirements-dev.txt, pyproject.toml (ruff + mypy + pytest config)"
fi
echo "  .gitlab-ci.yml, .gitleaks.toml, .gitignore, .dockerignore, .pre-commit-config.yaml"
if [[ "$LANG" == "node" ]]; then
    echo "  qa_check.js, kpi.json, AUTORESEARCH.md, metric.sh, Makefile"
elif [[ "$LANG" == "go" ]]; then
    echo "  cmd/qa/ (qa-check), kpi.json, AUTORESEARCH.md, metric.sh, Makefile"
else
    echo "  qa_check.py, kpi.json, AUTORESEARCH.md, metric.sh, Makefile"
fi
echo "  $CONFIG_MODULE (typed config boundary — declare every env var here)"
echo "  scripts/check_env.py, check_locales.py, check_root_clutter.py, refresh_agents.py"
echo "  scripts/bench_run.py, scripts/bench_compare.py, bench/ (baseline + declarations)"
echo "  scripts/translate_docs.sh, scripts/translate_docs_impl.py"
echo "  docs/plans/, docs/specs/"
echo "  brand/ (config.json, logo.svg, favicon.svg, wordmark.svg, README.md)"
echo "  locales/ (en.json, es.json, README.md)"
echo "  memory/ (decisions/, experiments/, bugs/, feedback/, sub_agent_runs/, pr_reviews/ + SCHEMA.md)"
if [[ $WITH_KPI -eq 1 ]]; then
    echo "  scripts/kpi_collector.py, scripts/kpi_dashboard.py"
fi
if [[ $WITH_RAG -eq 1 ]]; then
    echo "  rag/ (config.yml, index.py, README.md)"
fi
if [[ $WITH_BOT -eq 1 ]]; then
    echo "  bot/ (bot.py, tools/, runners/, Dockerfile, docker-compose.bot.yml)"
fi
if [[ $WITH_GITEA -eq 1 ]]; then
    echo "  gitea/ (docker-compose.gitea.yml, bootstrap.sh, README.md)"
fi
if [[ $WITH_VAULT -eq 1 ]]; then
    echo "  vault/ (secret-map.tsv, pull.sh, check.sh, rotate.md, README.md)"
fi
if [[ $WITH_MONITOR -eq 1 ]]; then
    echo "  monitor/ (probe.py, README.md)"
fi
if [[ $WITH_REVIEW -eq 1 ]]; then
    echo "  review/ (gate.py, run.sh, ci.gitlab-ci.yml, fetch_poster.sh, README.md)"
fi
echo "  docs/SETUP.md, docs/ARCHITECTURE.md, docs/KPI_SETUP.md"
case "$TYPE" in
    service|notebook|webapp|image|bridge|stream|audio) echo "  docs/API.md" ;;
    *)                       echo "  docs/USAGE.md" ;;
esac
echo ""
echo "Operator-only files (gitignored):"
echo "  .env, LOCAL.md, results.tsv, autoresearch.log"
echo "  scratch/ (one-off diagnostics — keeps them out of the repo root)"
echo "  bench/current/, bench/reports/, dist/"
if [[ $WITH_KPI -eq 1 ]]; then
    echo "  data/kpis.jsonl"
fi
echo ""
echo "Next:"
echo "  1. cd $PROJ"
echo "  2. Fill in STRATEGY.md with your problem statement + success metric"
echo "  3. Edit README.md with the one-line description"
echo "  4. make doctor"
echo "  5. make setup"
echo "  6. make run"
echo "  7. make test && make qa"
echo "  8. git remote add origin <git-url> && git push -u origin main"
echo ""
echo "All dependencies and checks run in Docker; no host package installation is required."
echo "Containers use non-root users, dropped capabilities, read-only root filesystems,"
echo "bounded resources, and localhost-only published ports."
