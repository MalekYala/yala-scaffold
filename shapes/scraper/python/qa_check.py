#!/usr/bin/env python3
"""End-to-end check for <name> (shape: scraper).

Checks:

  1. fixtures_present  — the committed fixtures exist
  2. extraction        — the extractor pulls records out of the fixture page
  3. fields            — every required field is populated on every record
  4. empty_vs_broken   — a legitimately empty page is not reported as a failure,
                         and a changed page IS
  5. pagination        — the next-page link is still found
  6. politeness        — the fetcher declares a User-Agent and a rate limit

**Zero extracted records is a failure**, unless the page itself said it was
empty. That distinction is the whole point of this shape. A scraper whose
selectors stop matching returns exactly what a genuinely empty result returns,
so a check that only counts rows cannot tell you the difference — and reports
success while you collect nothing.

Everything here runs against **committed fixtures, never the live site.**
Testing a scraper against the real internet gives you a suite that fails for
reasons unrelated to your code (rate limits, captchas, outages) and passes when
the markup quietly changes. Update the fixture in the same commit as the
selectors, and the diff shows exactly what moved.

Usage:
    python3 qa_check.py
    python3 qa_check.py --fixtures fixtures

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import extract as extractor  # noqa: E402


def run(fixtures: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    listing = fixtures / "listing.html"
    empty = fixtures / "empty.html"

    # 1. fixtures_present
    missing = [p.name for p in (listing, empty) if not p.is_file()]
    checks.append(
        {
            "name": "fixtures_present",
            "ok": not missing,
            "detail": "committed fixtures found" if not missing else f"missing: {missing} — extraction cannot be checked without them",
        }
    )
    if missing:
        return {"status": "fail", "checks": checks}

    # 2. extraction — zero records here is a broken extractor, not an empty page.
    result = extractor.extract(listing.read_text(encoding="utf-8"), base_url="https://example.invalid")
    checks.append(
        {
            "name": "extraction",
            "ok": len(result.records) > 0,
            "detail": f"{len(result.records)} record(s) from {listing.name}" + ("" if result.records else f" — selectors matched nothing; missed={result.missed_selectors}"),
        }
    )

    # 3. fields — a record missing its required fields is a half-broken selector.
    problems = extractor.validate(result.records)
    checks.append(
        {
            "name": "fields",
            "ok": not problems and not result.missed_selectors,
            "detail": "all required fields populated"
            if not problems and not result.missed_selectors
            else f"{'; '.join(problems[:5])}" + (f" | selectors matching nothing: {result.missed_selectors}" if result.missed_selectors else ""),
        }
    )

    # 4. empty_vs_broken — the distinction this shape exists for.
    empty_result = extractor.extract(empty.read_text(encoding="utf-8"))
    changed_result = extractor.extract("<html><body><div>totally different markup</div></body></html>")
    empty_ok = empty_result.legitimately_empty and not empty_result.looks_broken
    changed_ok = changed_result.looks_broken
    checks.append(
        {
            "name": "empty_vs_broken",
            "ok": empty_ok and changed_ok,
            "detail": "an empty page reads as empty; a changed page reads as broken"
            if empty_ok and changed_ok
            else (f"empty page misread (legitimately_empty={empty_result.legitimately_empty}); " if not empty_ok else "")
            + ("a page with changed markup was NOT flagged as broken — the silent failure this shape exists to prevent" if not changed_ok else ""),
        }
    )

    # 5. pagination
    checks.append(
        {
            "name": "pagination",
            "ok": bool(result.next_page),
            "detail": f"next page: {result.next_page}" if result.next_page else "next-page selector matched nothing — crawls will stop after page 1",
        }
    )

    # 6. politeness — a scraper without these gets your IP blocked and is rude.
    try:
        import fetch as fetcher

        has_ua = bool(getattr(fetcher, "USER_AGENT", "").strip())
        has_delay = float(getattr(fetcher, "REQUEST_DELAY_S", 0)) > 0
        checks.append(
            {
                "name": "politeness",
                "ok": has_ua and has_delay,
                "detail": f"user_agent={'set' if has_ua else 'MISSING'} "
                f"delay={'set' if has_delay else 'MISSING'}" + ("" if has_ua and has_delay else " — an unidentified scraper hammering a site gets blocked, deservedly"),
            }
        )
    except ImportError as exc:
        checks.append({"name": "politeness", "ok": False, "detail": f"cannot import fetch.py: {exc}"})

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the extractor against committed fixtures")
    parser.add_argument("--fixtures", type=Path, default=PROJECT_ROOT / "fixtures")
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.fixtures)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
