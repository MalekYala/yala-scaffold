#!/usr/bin/env bash
# scripts/translate_docs.sh — translate a markdown or JSON file into another language.
#
# This is a WRAPPER around an operator-supplied translation backend. The
# project has no opinion on which one you use — configure via env vars.
#
# Usage:
#     TRANSLATOR=<backend> TARGET_LANG=<code> ./scripts/translate_docs.sh <input> <output>
#
# Examples:
#     # Local LLM via an Ollama/llm-router endpoint
#     TRANSLATOR=local-llm OPENAI_BASE_URL=http://127.0.0.1:11436/v1 TARGET_LANG=es \
#         ./scripts/translate_docs.sh README.md README.es.md
#
#     # OpenAI API
#     TRANSLATOR=openai OPENAI_API_KEY=sk-... TARGET_LANG=de \
#         ./scripts/translate_docs.sh locales/en.json locales/de.json
#
#     # DeepL API
#     TRANSLATOR=deepl DEEPL_API_KEY=... TARGET_LANG=fr \
#         ./scripts/translate_docs.sh docs/SETUP.md docs/fr/SETUP.md
#
#     # Manual — opens $EDITOR on a copy and trusts you to translate it
#     TRANSLATOR=manual TARGET_LANG=ja \
#         ./scripts/translate_docs.sh docs/API.md docs/ja/API.md
#
# Backends (all operator-supplied — you decide which ones your repo supports):
#
#     local-llm  — POSTs to an OpenAI-compatible /v1/chat/completions endpoint
#                  (Ollama, llama.cpp, vLLM, LiteLLM, llm-router, etc.)
#                  Required: OPENAI_BASE_URL, optionally OPENAI_API_KEY, MODEL
#
#     openai     — Same as local-llm but defaults to api.openai.com
#                  Required: OPENAI_API_KEY, optionally MODEL (default gpt-4o-mini)
#
#     deepl      — Calls DeepL's translate API
#                  Required: DEEPL_API_KEY
#                  Note: DeepL does not preserve JSON structure — use for
#                  markdown only, not for locales/*.json
#
#     manual     — Copies the input to the output and opens $EDITOR
#                  Useful for review workflows; humans do the real translation
#
# The script delegates to `python3 scripts/translate_docs_impl.py` for the
# actual API calls. This wrapper just validates inputs and forwards env vars.

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: TRANSLATOR=<backend> TARGET_LANG=<code> $0 <input> <output>" >&2
    echo "Backends: local-llm | openai | deepl | manual" >&2
    exit 1
fi

INPUT="$1"
OUTPUT="$2"

if [[ -z "${TRANSLATOR:-}" ]]; then
    cat >&2 <<'EOF'
ERROR: TRANSLATOR environment variable is not set.

Pick one:
    export TRANSLATOR=local-llm   # any OpenAI-compatible endpoint (Ollama, llm-router, vLLM, ...)
    export TRANSLATOR=openai      # OpenAI API (api.openai.com)
    export TRANSLATOR=deepl       # DeepL API
    export TRANSLATOR=manual      # copy + open $EDITOR

Then rerun this script.
EOF
    exit 1
fi

if [[ -z "${TARGET_LANG:-}" ]]; then
    echo "ERROR: TARGET_LANG environment variable is not set (e.g. 'es', 'de', 'fr')" >&2
    exit 1
fi

if [[ ! -f "$INPUT" ]]; then
    echo "ERROR: input file not found: $INPUT" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

case "$TRANSLATOR" in
    manual)
        cp "$INPUT" "$OUTPUT"
        echo "Copied $INPUT → $OUTPUT. Opening \$EDITOR for manual translation…"
        "${EDITOR:-vi}" "$OUTPUT"
        ;;
    local-llm|openai|deepl)
        # Delegate to the Python implementation
        python3 "$(dirname "$0")/translate_docs_impl.py" \
            --backend "$TRANSLATOR" \
            --target-lang "$TARGET_LANG" \
            --input "$INPUT" \
            --output "$OUTPUT"
        ;;
    *)
        echo "ERROR: unknown TRANSLATOR: $TRANSLATOR" >&2
        echo "Valid backends: local-llm | openai | deepl | manual" >&2
        exit 1
        ;;
esac

echo "Translated $INPUT → $OUTPUT ($TRANSLATOR, lang=$TARGET_LANG)"
