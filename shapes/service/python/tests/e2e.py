"""End-to-end happy-path flow for <name>.

The `ui_test` tool imports this file and calls `run(page)` after
every PR merge, and on demand when the operator asks "test the UI" in
#<name>. Keep the flow narrow and fast — it must complete in under 60s
total to not time out. Use Playwright's sync API; `page` is a logged-in
browser page already pointed at the app URL.

Add assertions that would catch the user-visible regressions this
project is meant to prevent. On assertion failure, raise — the tool
reports the traceback back to IRC.
"""

from __future__ import annotations

from typing import Protocol


class Page(Protocol):
    def wait_for_selector(self, selector: str, *, timeout: int) -> object: ...

    def inner_text(self, selector: str) -> str: ...


def run(page: Page) -> dict[str, int]:
    """Run the happy-path and return a dict of observations.

    The bot prints the returned dict to IRC as part of the ui_test
    summary. Keep values small — strings, ints, bools.
    """
    result: dict[str, int] = {}

    # Example: verify the page rendered content (not a blank React shell).
    page.wait_for_selector("body", timeout=10_000)
    body_text = page.inner_text("body")
    result["body_chars"] = len(body_text)
    if len(body_text) < 40:
        raise AssertionError(f"body text suspiciously short ({len(body_text)} chars)")

    # TODO: replace these with real project assertions. A few patterns:
    #
    #   # Click a button and verify the next state
    #   page.get_by_role("button", name="Start voice").click()
    #   page.wait_for_selector("text=Recording…", timeout=5_000)
    #
    #   # Open a dropdown and verify its options populated
    #   page.select_option("select#tts-provider", "elevenlabs")
    #   page.wait_for_selector("select#voice-picker", timeout=5_000)
    #   voices = page.locator("select#voice-picker option").count()
    #   assert voices > 1, f"voice picker empty (count={voices})"
    #   result["voice_count"] = voices

    return result
