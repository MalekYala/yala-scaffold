#!/usr/bin/env python3
"""scripts/translate_docs_impl.py — backend implementations for translate_docs.sh.

This is a thin shim over the different backends. Keep the code simple and
readable — the real translation logic lives in the LLM/API being called.

All backends are operator-supplied: the project does NOT ship API keys or
endpoint URLs. Configure via env vars before running.
"""
import argparse
import json
import os
import sys
from pathlib import Path


def translate_with_openai_compat(
    text: str,
    target_lang: str,
    base_url: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Send the text to an OpenAI-compatible /v1/chat/completions endpoint.
    Works with real OpenAI, Ollama, llama.cpp, vLLM, LiteLLM, llm-router,
    and any other compatible server.
    """
    import httpx

    model = model or os.environ.get("MODEL") or "gpt-4o-mini"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    prompt = f"""Translate the following content to {target_lang}. Preserve:
- all markdown formatting (headings, lists, tables, code blocks, links)
- all JSON structure if the input is JSON
- all interpolation variables like {{{{name}}}} or {{count}}
- all code blocks verbatim (do NOT translate code)
- file paths, URLs, command names, and technical identifiers

Return ONLY the translated content, no preamble, no wrapping ``` fences.

---

{text}"""

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }

    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload,
        headers=headers,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def translate_with_deepl(text: str, target_lang: str, api_key: str) -> str:
    """Translate via DeepL's v2 API. Works for plain text and markdown but
    does NOT preserve JSON structure — don't use this for locales/*.json.
    """
    import httpx

    # DeepL uses uppercase ISO codes and free tier uses api-free endpoint
    url = "https://api-free.deepl.com/v2/translate"
    data = {
        "auth_key": api_key,
        "text": text,
        "target_lang": target_lang.upper(),
        "preserve_formatting": "1",
        "tag_handling": "xml",  # closest to markdown-safe
    }
    r = httpx.post(url, data=data, timeout=120)
    r.raise_for_status()
    return r.json()["translations"][0]["text"]


def translate_file(input_path: Path, output_path: Path, backend: str, target_lang: str):
    """Dispatch to the right backend, handling JSON + markdown differently."""
    source = input_path.read_text()
    is_json = input_path.suffix.lower() == ".json"

    if backend in ("local-llm", "openai"):
        base_url = os.environ.get("OPENAI_BASE_URL") or (
            "https://api.openai.com/v1" if backend == "openai" else None
        )
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL not set (required for local-llm)")
        api_key = os.environ.get("OPENAI_API_KEY")
        if backend == "openai" and not api_key:
            raise RuntimeError("OPENAI_API_KEY not set (required for openai backend)")
        translated = translate_with_openai_compat(source, target_lang, base_url, api_key)

        # For JSON files, validate that the result is parseable JSON
        if is_json:
            try:
                json.loads(translated)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"translated output is not valid JSON: {exc}\n"
                    f"First 200 chars:\n{translated[:200]}"
                )

    elif backend == "deepl":
        if is_json:
            raise RuntimeError(
                "DeepL backend does not preserve JSON structure. "
                "Use local-llm or openai for locales/*.json translations."
            )
        api_key = os.environ.get("DEEPL_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPL_API_KEY not set")
        translated = translate_with_deepl(source, target_lang, api_key)

    else:
        raise RuntimeError(f"unknown backend: {backend}")

    output_path.write_text(translated)
    return len(translated)


def main():
    ap = argparse.ArgumentParser(description="Translate docs/locales via a pluggable backend")
    ap.add_argument("--backend", required=True, choices=["local-llm", "openai", "deepl"])
    ap.add_argument("--target-lang", required=True, help="ISO 639-1 code, e.g. es, de, fr, ja")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        size = translate_file(args.input, args.output, args.backend, args.target_lang)
        print(f"wrote {size} bytes to {args.output}")
    except Exception as exc:
        print(f"ERROR: translation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
