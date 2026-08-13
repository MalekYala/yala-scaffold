#!/usr/bin/env python3
"""Keep `.env.example` honest for <name>.

`.env.example` is the contract between this project and whoever has to run it.
Hand-maintained, it is always a little bit wrong: a variable added in code and
never documented, or documented long after it was deleted. Both failures are
invisible until someone tries to deploy.

So the config module (`<config_module>`) is the single source of truth, and the
part of `.env.example` between the `scaffold:env` markers is generated from it.
Everything outside the markers is yours — operator notes, optional add-on
wiring, commented examples — and is never touched.

Usage:
    python3 scripts/check_env.py            # fail on drift
    python3 scripts/check_env.py --write    # regenerate the managed block

With the Vault add-on enabled this also cross-checks `vault/secret-map.tsv`:
a required variable with no Vault mapping, or a mapping for a variable nothing
declares, is drift in the other direction and just as broken.

Exit codes:
    0  in sync
    1  drift found (or the config module failed to load)
    2  usage / missing files
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
SECRET_MAP = PROJECT_ROOT / "vault" / "secret-map.tsv"

BLOCK_START_PREFIX = "# scaffold:env:start"
BLOCK_END = "# scaffold:env:end"

# Filled by the scaffold for this project's language.
CONFIG_PRINT_CMD = "<config_print_cmd>"


def render_schema() -> str:
    """Ask the config module to render its managed block."""
    result = subprocess.run(
        CONFIG_PRINT_CMD,
        shell=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: config module failed to render the schema\n"
            f"  command: {CONFIG_PRINT_CMD}\n"
            f"  exit:    {result.returncode}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip("\n")


def split_example(text: str) -> tuple[str, str | None, str]:
    """Split .env.example into (before, managed_block, after).

    managed_block is None when the markers are absent, which is how a project
    scaffolded before this check opts in: --write inserts the block.
    """
    lines = text.splitlines()
    start = end = None
    for index, line in enumerate(lines):
        if start is None and line.startswith(BLOCK_START_PREFIX):
            start = index
        elif start is not None and line.strip() == BLOCK_END:
            end = index
            break
    if start is None or end is None:
        return text, None, ""
    return (
        "\n".join(lines[:start]),
        "\n".join(lines[start : end + 1]),
        "\n".join(lines[end + 1 :]),
    )


def declared_names(block: str) -> set[str]:
    """Variable names declared in a managed block, commented-out included."""
    names: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and "=" in stripped:
            stripped = stripped[2:].strip()
        elif stripped.startswith("#"):
            continue
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name.isupper() or "_" in name:
                names.add(name)
    return names


def check_secret_map(schema_block: str) -> list[str]:
    """Cross-check vault/secret-map.tsv against the declared schema."""
    if not SECRET_MAP.is_file():
        return []

    declared = declared_names(schema_block)
    problems: list[str] = []
    mapped: set[str] = set()

    for number, line in enumerate(SECRET_MAP.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) != 3:
            problems.append(
                f"  vault/secret-map.tsv:{number}: expected 3 tab-separated "
                f"columns (ENV_VAR, path, field), got {len(parts)}"
            )
            continue
        mapped.add(parts[0].strip())

    for name in sorted(mapped - declared):
        problems.append(
            f"  {name} is mapped in vault/secret-map.tsv but not declared in "
            f"the config module — nothing reads it"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Check .env.example against the config schema")
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the managed block instead of failing",
    )
    args = parser.parse_args()

    _t = time.monotonic()

    if not ENV_EXAMPLE.is_file():
        print(f"ERROR: {ENV_EXAMPLE} not found", file=sys.stderr)
        return 2

    schema = render_schema()
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    before, current, after = split_example(text)

    problems = check_secret_map(schema)
    in_sync = current is not None and current.strip() == schema.strip()

    if args.write:
        if current is None:
            # Opt-in path: append the block, keeping existing content intact.
            updated = text.rstrip("\n") + "\n\n" + schema + "\n"
        else:
            updated = "\n".join(part for part in (before, schema, after) if part is not None)
            updated = updated.rstrip("\n") + "\n"
        ENV_EXAMPLE.write_text(updated, encoding="utf-8")
        print(f"wrote managed block to {ENV_EXAMPLE.name}")
        if problems:
            print("\nremaining problems:", file=sys.stderr)
            print("\n".join(problems), file=sys.stderr)
            return 1
        return 0

    elapsed = int((time.monotonic() - _t) * 1000)
    status = "ok" if in_sync and not problems else "fail"
    print(f"[<name>-perf] phase=check_env duration_ms={elapsed} status={status}")

    if not in_sync:
        if current is None:
            print(
                f"ERROR: {ENV_EXAMPLE.name} has no managed block.\n"
                f"       Run: make env-example",
                file=sys.stderr,
            )
        else:
            print(
                f"ERROR: {ENV_EXAMPLE.name} is out of sync with the config schema.\n"
                f"       A variable was added, removed or re-documented in the "
                f"config module\n       without regenerating the example.\n"
                f"       Run: make env-example",
                file=sys.stderr,
            )
        return 1

    if problems:
        print("ERROR: configuration drift:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 1

    print(f"{ENV_EXAMPLE.name} is in sync with the config schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
