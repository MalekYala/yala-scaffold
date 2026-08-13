"""Entry point for <name> (shape: scraper).

Crawls, extracts, and writes records to `outputs/`. Fetching and extraction
live in `fetch.py` and `extract.py`; this is only the loop that joins them.

Refuses to run without a target, and refuses to *silently* produce nothing:
a run that extracts zero records from a page that did not say it was empty
exits non-zero, because that is a broken extractor rather than an empty result.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import config
import extract as extractor
from fetch import Fetcher

settings = config.load()
PROJECT_ROOT = Path(__file__).resolve().parent

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("<name>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl and extract records")
    parser.add_argument("--url", default=settings.target_base_url, help="starting URL")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "outputs" / "records.jsonl")
    parser.add_argument(
        "--from-fixture",
        type=Path,
        help="extract from a local file instead of the network (what CI uses)",
    )
    args = parser.parse_args()

    _t = time.monotonic()
    records: list[dict[str, Any]] = []
    broken_pages = 0

    if args.from_fixture:
        result = extractor.extract(args.from_fixture.read_text(encoding="utf-8"))
        records.extend(result.records)
        broken_pages += int(result.looks_broken)
    else:
        if not args.url:
            print(
                "ERROR: no target URL. Pass --url or set TARGET_BASE_URL in .env.\n"
                "       The scaffold ships with no target on purpose — one that "
                "came pointed at a real site would invite accidental traffic.",
                file=sys.stderr,
            )
            return 2

        fetcher = Fetcher(base_url=args.url)
        try:
            url = args.url
            for page in range(1, args.max_pages + 1):
                response = fetcher.get(url)
                log.info(f"[<name>-perf] phase=fetch duration_ms={response.elapsed_ms:.0f} status={response.status} page={page}")
                if response.status == 404:
                    log.warning(f"page {page} returned 404 — stopping")
                    break

                result = extractor.extract(response.text, base_url=args.url)
                records.extend(result.records)
                if result.looks_broken:
                    broken_pages += 1
                    log.error(f"page {page} produced no records and did not say it was empty — selectors matching nothing: {result.missed_selectors}")
                if not result.next_page:
                    break
                url = result.next_page
        finally:
            fetcher.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    elapsed = int((time.monotonic() - _t) * 1000)
    print(f"[<name>-perf] phase=total duration_ms={elapsed} records={len(records)} broken_pages={broken_pages}")
    print(f"{len(records)} record(s) -> {args.out}")

    # Exit non-zero on a silent failure. A scraper that reports success while
    # collecting nothing is the failure mode this shape exists to prevent.
    if broken_pages:
        print(
            f"\nERROR: {broken_pages} page(s) yielded nothing and did not say they "
            f"were empty.\n       The site's markup has most likely changed — update "
            f"SELECTORS in extract.py\n       and the fixtures in the same commit.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
