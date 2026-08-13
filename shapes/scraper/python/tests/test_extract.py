"""Tests for <name>'s extractor.

Every one of these runs against committed fixtures or inline HTML — never the
network. That is deliberate: a scraper suite that touches the live site fails
for reasons unrelated to your code, and passes when the markup quietly changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import extract as extractor  # noqa: E402

FIXTURES = PROJECT_ROOT / "fixtures"


def listing_html() -> str:
    return (FIXTURES / "listing.html").read_text(encoding="utf-8")


class TestExtraction:
    def test_finds_every_record(self):
        assert len(extractor.extract(listing_html()).records) == 3

    def test_populates_required_fields(self):
        for record in extractor.extract(listing_html()).records:
            for name in extractor.REQUIRED_FIELDS:
                assert record.get(name) not in (None, ""), name

    def test_parses_prices_as_numbers(self):
        prices = [r["price"] for r in extractor.extract(listing_html()).records]
        assert prices == [12.50, 8.00, 24.99]

    def test_reads_stock_state(self):
        stock = [r["in_stock"] for r in extractor.extract(listing_html()).records]
        assert stock == [True, False, True]

    def test_finds_the_next_page_link(self):
        assert extractor.extract(listing_html()).next_page == "/listings?page=2"

    def test_joins_relative_urls_against_the_base(self):
        record = extractor.extract(listing_html(), base_url="https://example.invalid").records[0]
        assert record["url"] == "https://example.invalid/items/a-1"


class TestEmptyVersusBroken:
    """The distinction this whole shape exists for."""

    def test_a_page_that_says_it_is_empty_is_not_broken(self):
        result = extractor.extract((FIXTURES / "empty.html").read_text(encoding="utf-8"))
        assert result.records == []
        assert result.legitimately_empty
        assert not result.looks_broken

    def test_a_page_with_changed_markup_is_broken(self):
        # Same zero records, completely different meaning. Conflating these is
        # how a broken scraper runs for a week before anyone notices.
        result = extractor.extract("<html><body><div>redesigned</div></body></html>")
        assert result.records == []
        assert not result.legitimately_empty
        assert result.looks_broken
        assert "container" in result.missed_selectors

    def test_a_field_selector_that_stops_matching_is_reported(self):
        html = """
        <html><body><main>
          <article class="listing" data-id="x"><h2 class="listing-title">T</h2></article>
        </main></body></html>
        """
        result = extractor.extract(html)
        assert result.records
        # Price vanished from every record — that is a markup change, not data.
        assert "price_raw" in result.missed_selectors


class TestPriceParsing:
    def test_handles_currency_symbols(self):
        assert extractor.parse_price("£12.50") == 12.50

    def test_handles_comma_decimals(self):
        assert extractor.parse_price("12,50 €") == 12.50

    def test_returns_none_for_unparseable_text(self):
        assert extractor.parse_price("call for price") is None

    def test_returns_none_for_missing_input(self):
        assert extractor.parse_price(None) is None


class TestValidate:
    def test_reports_missing_required_fields(self):
        problems = extractor.validate([{"id": "1", "title": "t"}])
        assert any("price" in p for p in problems)

    def test_accepts_complete_records(self):
        assert extractor.validate([{"id": "1", "title": "t", "price": 1.0}]) == []
