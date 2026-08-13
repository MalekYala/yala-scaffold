"""Shape-specific configuration for <name> (shape: scraper).

Politeness settings are configuration, not constants, because the right values
depend on the site — and because someone will need to change them at 2am
without editing code.
"""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "USER_AGENT",
        "How this scraper identifies itself. Include a contact address: it is the difference between someone emailing you about load and someone silently null-routing your IP.",
        default="<name>/0.1 (+https://example.invalid/contact)",
        section="Scraping politeness",
    ),
    Field(
        "REQUEST_DELAY_S",
        "Minimum seconds between requests. The single most effective politeness measure; raise it before you raise concurrency.",
        default="1.0",
    ),
    Field(
        "REQUEST_TIMEOUT_S",
        "Per-request timeout in seconds.",
        default="30.0",
    ),
    Field(
        "MAX_RETRIES",
        "Attempts per URL before giving up, with exponential backoff.",
        cast=as_int,
        default=3,
    ),
    Field(
        "TARGET_BASE_URL",
        "Base URL to crawl. Left blank on purpose — a scaffold that ships pointed at a real site invites accidental traffic.",
        default="",
    ),
]
