#!/usr/bin/env python3
"""Keep the repository root free of scratch files, for <name>.

Every real project accumulates one-off diagnostics: `tmp_check_thing.py`,
`test_regex.ts`, `inspect-db.js`, `diag.sh`. They get written under delivery
pressure, they work, and they never get deleted. Six months later the root is
half debris, tooling has to be configured to ignore it, and new contributors
cannot tell which files matter.

The answer is not discipline — it is giving those files somewhere to live.
`scratch/` is gitignored and unlimited. This check simply keeps them out of the
root and out of history.

Usage:
    python3 scripts/check_root_clutter.py

Exit codes:
    0  root is clean
    1  scratch-looking files found at the root
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Patterns that mean "this was a one-off". Deliberately narrow: the goal is to
# catch obvious debris, not to police legitimate file names.
CLUTTER_PATTERNS = [
    re.compile(r"^tmp[_-].+"),
    re.compile(r"^temp[_-].+"),
    re.compile(r"^scratch[_-].+"),
    re.compile(r"^debug[_-].+"),
    re.compile(r"^diag[_-].+"),
    re.compile(r"^.*[_-]diag\.(py|js|mjs|cjs|ts|sh)$"),
    re.compile(r"^inspect[_-].+\.(py|js|mjs|cjs|ts)$"),
    # test_* at the ROOT only — tests belong in tests/.
    re.compile(r"^test[_-].+\.(py|js|mjs|cjs|ts|go)$"),
    re.compile(r"^.+\.(log|out)$"),
]

# Files that legitimately live at the root despite matching a pattern above.
ALLOWLIST = {
    "test.sh",  # some projects genuinely ship a root test runner
}


def tracked_root_files() -> list[str]:
    """Git-tracked files at the repo root, plus anything currently staged."""
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git repo yet (or no git) — fall back to a directory listing.
        return [p.name for p in PROJECT_ROOT.iterdir() if p.is_file()]

    # Root level only: no directory separator in the path.
    return [name for name in tracked if "/" not in name]


def main() -> int:
    offenders = [
        name
        for name in sorted(tracked_root_files())
        if name not in ALLOWLIST
        and any(pattern.match(name) for pattern in CLUTTER_PATTERNS)
    ]

    if not offenders:
        print("repository root is clean")
        return 0

    print("ERROR: scratch files found at the repository root:", file=sys.stderr)
    for name in offenders:
        print(f"  {name}", file=sys.stderr)
    print(
        "\nMove them to scratch/ (gitignored, and exactly what it is for), or "
        "delete them.\nIf one of these is a real, permanent part of the "
        "project, add it to ALLOWLIST\nin scripts/check_root_clutter.py — but "
        "consider a clearer name first.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
