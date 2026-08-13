#!/usr/bin/env python3
"""Catch styles that compile clean and render invisible, for <name>.

The failure mode this exists for: a CSS custom property that is *referenced*
but never *defined*. `color: var(--color-primary)` with no `--color-primary`
anywhere resolves to nothing. No error, no warning, no failing test — the
element simply renders with no colour, or disappears against its background.
Lint passes. Type-check passes. An HTTP 200 assertion passes. Only looking at
pixels catches it, and nobody looks at pixels on every commit.

So this checks the one thing a machine can check cheaply: every `var(--x)`
reference resolves to a definition somewhere in the project's CSS, inline
styles, or brand config.

**This is a floor, not a substitute for looking.** It cannot tell you the
layout is broken, the contrast is unreadable, or the logo is upside down. See
AGENTS.md § "Visual verification" — render the page and look at it.

Usage:
    python3 scripts/check_styles.py
    python3 scripts/check_styles.py --dir dist    # check built output too

Exit codes:
    0  every referenced token resolves (or there is no CSS to check)
    1  unresolved token references
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SEARCH_DIRS = ["src", "public", "static", "templates", "brand", "dist"]
STYLE_SUFFIXES = {".css", ".scss", ".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".py"}

# `var(--token)` / `var(--token, fallback)`
REFERENCE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,([^()]*(?:\([^()]*\)[^()]*)*))?\)")
# `--token: value`
DEFINITION = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")


def collect(paths: list[Path]) -> tuple[dict[str, list[str]], set[str]]:
    """Return (referenced token -> files, defined tokens)."""
    referenced: dict[str, list[str]] = {}
    defined: set[str] = set()

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for match in DEFINITION.finditer(text):
            defined.add(match.group(1))

        for match in REFERENCE.finditer(text):
            token, fallback = match.group(1), match.group(2)
            # A reference with a fallback still renders something, so it is
            # not the silent-failure case this check is about.
            if fallback is not None and fallback.strip():
                continue
            referenced.setdefault(token, []).append(
                str(path.relative_to(PROJECT_ROOT))
            )

    return referenced, defined


def brand_tokens() -> set[str]:
    """Tokens a project may legitimately generate from brand/config.json.

    The webapp shape emits `--color-<key>` custom properties at runtime from
    the brand config, so those names are defined even though no CSS file
    mentions them.
    """
    config = PROJECT_ROOT / "brand" / "config.json"
    if not config.is_file():
        return set()
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    tokens: set[str] = set()
    for group, prefix in (("colors", "--color-"), ("fonts", "--font-")):
        for key in data.get(group, {}) or {}:
            tokens.add(f"{prefix}{str(key).replace('_', '-')}")
    return tokens


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CSS custom properties resolve")
    parser.add_argument(
        "--dir",
        action="append",
        default=None,
        help="extra directory to scan (repeatable)",
    )
    args = parser.parse_args()

    _t = time.monotonic()

    search = list(SEARCH_DIRS) + list(args.dir or [])
    files: list[Path] = []
    for name in search:
        directory = PROJECT_ROOT / name
        if not directory.is_dir():
            continue
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix in STYLE_SUFFIXES
            and "node_modules" not in path.parts
        )

    if not files:
        print("no stylable files found — nothing to check")
        return 0

    referenced, defined = collect(files)
    defined |= brand_tokens()

    unresolved = {
        token: sorted(set(where))
        for token, where in referenced.items()
        if token not in defined
    }

    elapsed = int((time.monotonic() - _t) * 1000)
    print(
        f"[<name>-perf] phase=check_styles duration_ms={elapsed} "
        f"files={len(files)} referenced={len(referenced)} defined={len(defined)} "
        f"unresolved={len(unresolved)}"
    )

    if not unresolved:
        print(f"all {len(referenced)} referenced custom properties resolve")
        return 0

    print("\nERROR: CSS custom properties referenced but never defined:", file=sys.stderr)
    for token, where in sorted(unresolved.items()):
        print(f"  {token}", file=sys.stderr)
        for location in where[:4]:
            print(f"      used in {location}", file=sys.stderr)
    print(
        "\nThese resolve to nothing at render time: no error, no warning, and\n"
        "an element that is invisible or unstyled. Define them, or give the\n"
        "reference a fallback — var(--x, #333) — if absence is intentional.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
