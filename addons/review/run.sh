#!/usr/bin/env sh
#
# Run OpenCodeReview against <name>, inside a container.
#
# Invoked by `make code-review`, which mounts the project at /src and runs this
# in a node:20 image — so no host Node install is needed. It can also be run
# directly inside any image that has node and npm.
#
# Reads from the environment (make passes these through from .env):
#
#   OCR_LLM_URL         required  LLM endpoint
#   OCR_LLM_AUTH_TOKEN  required  API token
#   OCR_LLM_MODEL       required  model name — OCR has no default
#   OCR_USE_ANTHROPIC   optional  "true" for Anthropic-native APIs (default false)
#   OCR_LANGUAGE        optional  review output language
#   OCR_VERSION         optional  npm version to install (default: pinned by make)
#   OCR_FROM            optional  base ref; unset reviews the working tree
#
# Writes .ocr/result.json. Prints nothing but progress — `review/gate.py`
# turns the JSON into something readable and decides pass/fail.

set -eu

: "${OCR_LLM_URL:?set OCR_LLM_URL in .env — see review/README.md}"
: "${OCR_LLM_AUTH_TOKEN:?set OCR_LLM_AUTH_TOKEN in .env — see review/README.md}"
: "${OCR_LLM_MODEL:?set OCR_LLM_MODEL in .env — OCR has no default model}"

OCR_VERSION="${OCR_VERSION:-latest}"

echo "[review] installing open-code-review@${OCR_VERSION}…" >&2
npm install -g --silent "@alibaba-group/open-code-review@${OCR_VERSION}"

ocr config set llm.url "$OCR_LLM_URL"
ocr config set llm.auth_token "$OCR_LLM_AUTH_TOKEN"
ocr config set llm.model "$OCR_LLM_MODEL"
ocr config set llm.use_anthropic "${OCR_USE_ANTHROPIC:-false}"
# Thinking blocks break response parsing on several providers.
ocr config set llm.extra_body '{"thinking": {"type": "disabled"}}'
[ -n "${OCR_LANGUAGE:-}" ] && ocr config set language "$OCR_LANGUAGE"

mkdir -p .ocr

if [ -n "${OCR_FROM:-}" ]; then
    echo "[review] reviewing ${OCR_FROM}..HEAD" >&2
    ocr review --from "$OCR_FROM" --to HEAD --format json --audience agent > .ocr/result.json
else
    echo "[review] reviewing the working tree (staged + unstaged)" >&2
    ocr review --format json --audience agent > .ocr/result.json
fi

echo "[review] wrote .ocr/result.json" >&2
