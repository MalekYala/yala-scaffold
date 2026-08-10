#!/usr/bin/env python3
"""Locale key drift check for <name>.

Every file in locales/ must declare exactly the same set of keys as the
reference locale (en.json). A translation that silently loses a key renders
as a raw key name — or as nothing at all — in production, and nothing else
in the toolchain catches it: lint, typecheck and tests all pass on a
half-translated file.

Usage:
    python3 scripts/check_locales.py             # check, non-zero exit on drift
    python3 scripts/check_locales.py --list      # print the reference key set

Exit codes:
    0  every locale matches the reference
    1  drift found (missing or extra keys, or invalid JSON)
    2  usage error / no locales directory

Stdlib only, deliberately: this runs in pre-commit, in CI, and in the
lint container, and none of those should need a dependency install to
answer a question this simple.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REFERENCE = "en"
LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


def flatten(obj: object, prefix: str = "") -> set[str]:
    """Collapse a nested translation dict into dotted key paths.

    Only dicts recurse. A list, string or number is a leaf: translators
    replace its value, never its shape, so its internal structure is not
    part of the contract being checked.
    """
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                keys |= flatten(value, path)
            else:
                keys.add(path)
    return keys


def load(path: Path) -> tuple[set[str] | None, str | None]:
    """Return (keys, error). Exactly one is None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON at line {exc.lineno}: {exc.msg}"
    except OSError as exc:
        return None, f"unreadable: {exc}"
    if not isinstance(data, dict):
        return None, "top level must be a JSON object"
    return flatten(data), None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check locale files for key drift")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the reference locale's key set and exit",
    )
    args = parser.parse_args()

    _t = time.monotonic()

    if not LOCALES_DIR.is_dir():
        print(f"no locales directory at {LOCALES_DIR} — nothing to check")
        return 0

    reference_path = LOCALES_DIR / f"{REFERENCE}.json"
    if not reference_path.is_file():
        print(f"ERROR: reference locale missing: {reference_path}", file=sys.stderr)
        return 2

    reference_keys, error = load(reference_path)
    if reference_keys is None:
        print(f"ERROR: {reference_path.name}: {error}", file=sys.stderr)
        return 1

    if args.list:
        for key in sorted(reference_keys):
            print(key)
        return 0

    others = sorted(
        p for p in LOCALES_DIR.glob("*.json") if p.name != reference_path.name
    )
    if not others:
        print(f"only {REFERENCE}.json present — nothing to compare")
        return 0

    failed = False
    for path in others:
        keys, error = load(path)
        if keys is None:
            print(f"FAIL {path.name}: {error}", file=sys.stderr)
            failed = True
            continue

        missing = sorted(reference_keys - keys)
        extra = sorted(keys - reference_keys)

        if not missing and not extra:
            print(f"ok   {path.name} ({len(keys)} keys)")
            continue

        failed = True
        print(f"FAIL {path.name}", file=sys.stderr)
        for key in missing:
            print(f"       missing: {key}", file=sys.stderr)
        for key in extra:
            print(f"       extra:   {key}  (not in {REFERENCE}.json)", file=sys.stderr)

    elapsed = int((time.monotonic() - _t) * 1000)
    print(
        f"[<name>-perf] phase=check_locales duration_ms={elapsed} "
        f"locales={len(others) + 1} keys={len(reference_keys)} "
        f"status={'fail' if failed else 'ok'}"
    )

    if failed:
        print(
            "\nlocale drift detected — add the missing keys, or remove the extra "
            f"ones. The reference is locales/{REFERENCE}.json.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
