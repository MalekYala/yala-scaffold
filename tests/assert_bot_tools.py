#!/usr/bin/env python3
"""Assert a generated project's bot only offers tools a new user can reach.

Run by tests/scaffold_matrix.sh against a scaffolded project's `bot/`.

Two failures this guards against, both of which look fine until someone new
tries to use the thing:

**Operator-only tools.** The bot registry is the list of capabilities the model
is told it has. Anything backed by infrastructure only the original author runs
— a private data service, a personal knowledge store, a specific colleague's
bot on a specific IRC channel — is a tool the model will confidently call and a
new user will watch fail.

This is enforced structurally rather than by a list of banned names: every
registered tool must have its module shipped in `bot/tools/`, and the kit ships
modules only for tools it can satisfy on its own. Re-adding an operator-only
tool means registering a module that is not there, which fails below. A
name-based denylist would have to name the private services to exclude them,
which is exactly the information a public kit should not carry.

**Orphaned modules.** A tool file that nothing registers is dead code shipped
into every generated project, and the next person to read it cannot tell
whether it is load-bearing.

Usage:
    python3 tests/assert_bot_tools.py <path-to-project>/bot
"""

from __future__ import annotations

import pathlib
import sys

import yaml

def main() -> int:
    if len(sys.argv) != 2:
        print("usage: assert_bot_tools.py <project>/bot", file=sys.stderr)
        return 2

    bot_dir = pathlib.Path(sys.argv[1])
    config = yaml.safe_load((bot_dir / "config.yml").read_text(encoding="utf-8"))
    tools = config.get("tools", [])

    if not tools:
        print("bot registers no tools at all", file=sys.stderr)
        return 1

    problems: list[str] = []

    registered_modules = {tool["module"].split(".")[-1] for tool in tools}

    missing = sorted(
        module for module in registered_modules if not (bot_dir / "tools" / f"{module}.py").is_file()
    )
    if missing:
        problems.append(f"registered but the module is missing: {missing}")

    on_disk = {p.stem for p in (bot_dir / "tools").glob("*.py") if p.stem != "__init__"}
    orphans = sorted(on_disk - registered_modules)
    if orphans:
        problems.append(f"module(s) shipped but never registered: {orphans}")

    if problems:
        for problem in problems:
            print(f"bot tool registry: {problem}", file=sys.stderr)
        return 1

    print(f"bot tool registry: {len(tools)} tool(s), all reachable and all registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
