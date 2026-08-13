"""Extraction logic for <name>.

Shape: scraper (pull structured records out of remote pages).

Kept deliberately separate from fetching. Extraction is pure — HTML in,
records out — which is what lets `qa_check.py` exercise it against committed
fixtures instead of the live site. A scraper whose tests need the internet has
a test suite that fails for reasons unrelated to your code, and passes when
the site quietly changes its markup.

The important distinction this module makes, and which most scrapers get
wrong:

    a page that legitimately has no results
    vs.
    a page whose markup changed, so the selectors match nothing

Both produce zero records. Only one is a bug. `extract()` returns an
`Extraction` carrying which one happened, so the caller and the QA check can
tell them apart — see `SELECTORS["container"]` and `empty_marker`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from selectolax.parser import HTMLParser

# ── Selectors ──────────────────────────────────────────────────────────────
# Declared as data so a markup change is a one-line diff, and so qa_check can
# report which specific selector stopped matching rather than "0 results".

SELECTORS: dict[str, str] = {
    # The repeating element. If this matches nothing AND the empty marker is
    # absent, the page shape has changed — that is a failure, not an empty result.
    "container": "article.listing",
    "empty_marker": ".no-results",
    # Per-record fields, relative to the container.
    "title": "h2.listing-title",
    "price": "span.price",
    "stock": "span.stock",
    "link": "a.detail-link",
    # Pagination.
    "next_page": "a.next-page",
}

REQUIRED_FIELDS = ("id", "title", "price")

PRICE_RE = re.compile(r"([0-9]+(?:[.,][0-9]{1,2})?)")


@dataclass
class Extraction:
    """The result of parsing one page."""

    records: list[dict[str, Any]] = field(default_factory=list)
    next_page: str | None = None
    #: True when the page itself said "no results" — a legitimate empty page,
    #: not a broken selector.
    legitimately_empty: bool = False
    #: Selectors that matched nothing where something was expected.
    missed_selectors: list[str] = field(default_factory=list)

    @property
    def looks_broken(self) -> bool:
        """Zero records with no explanation — the silent failure mode.

        A scraper that returns nothing because the site changed reports
        exactly the same thing as one whose query genuinely had no matches.
        Treating them the same is how a broken extractor runs for a week
        before anyone notices.
        """
        return not self.records and not self.legitimately_empty


def clean(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_price(raw: str | None) -> float | None:
    """Pull a number out of a price string, currency symbol and all."""
    if not raw:
        return None
    match = PRICE_RE.search(raw.replace(",", "."))
    return float(match.group(1)) if match else None


def _absolute_url(base_url: str, href: str | None) -> str | None:
    """Join a scraped href onto the base URL, tolerating a missing href.

    Kept separate because the None case is the common one — a card whose link
    markup changed — and inlining it produced a str + None concatenation that
    only fails on the pages that already broke.
    """
    if href is None:
        return None
    if not base_url:
        return href
    return base_url.rstrip("/") + href


def extract(html: str, base_url: str = "") -> Extraction:
    """Parse one page into records.

    Pure: no network, no clock, no filesystem. That is what makes the fixture
    tests meaningful.
    """
    tree = HTMLParser(html)
    result = Extraction()

    containers = tree.css(SELECTORS["container"])

    if not containers:
        # Distinguish the two zero-record cases before giving up.
        if tree.css_first(SELECTORS["empty_marker"]) is not None:
            result.legitimately_empty = True
        else:
            result.missed_selectors.append("container")
        return result

    for node in containers:
        title_node = node.css_first(SELECTORS["title"])
        price_node = node.css_first(SELECTORS["price"])
        stock_node = node.css_first(SELECTORS["stock"])
        link_node = node.css_first(SELECTORS["link"])

        record: dict[str, Any] = {
            "id": node.attributes.get("data-id"),
            "title": clean(title_node.text()) if title_node else None,
            "price": parse_price(price_node.text()) if price_node else None,
            "price_raw": clean(price_node.text()) if price_node else None,
            "in_stock": (clean(stock_node.text()).lower().startswith("in")) if stock_node else None,
            "url": _absolute_url(base_url, link_node.attributes.get("href") if link_node else None),
        }
        result.records.append(record)

    # Report which per-field selectors stopped matching across the board. One
    # record missing a price is normal; *every* record missing it means the
    # markup moved.
    for field_name in ("title", "price_raw", "in_stock"):
        if all(record.get(field_name) in (None, "") for record in result.records):
            result.missed_selectors.append(field_name)

    next_node = tree.css_first(SELECTORS["next_page"])
    if next_node:
        result.next_page = next_node.attributes.get("href")

    return result


def validate(records: list[dict[str, Any]]) -> list[str]:
    """Field-level problems worth failing on. Returns a list of messages."""
    problems: list[str] = []
    for index, record in enumerate(records, 1):
        for name in REQUIRED_FIELDS:
            if record.get(name) in (None, ""):
                problems.append(f"record {index}: missing {name}")
    return problems
