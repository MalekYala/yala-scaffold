"""Shape-specific configuration for <name> (shape: browser)."""

from __future__ import annotations

from config import Field, as_bool, as_int

FIELDS: list[Field] = [
    Field(
        "TARGET_BASE_URL",
        "Site the workflows run against. Blank means the committed fixture site on an ephemeral port — which is what CI uses, so the suite never depends on an external site being up or unchanged.",
        default="",
        section="Browser automation",
    ),
    Field(
        "HEADLESS",
        "Run without a visible window. Headed is for debugging a workflow you cannot otherwise explain; CI is always headless.",
        cast=as_bool,
        default=True,
    ),
    Field(
        "STEP_TIMEOUT_MS",
        "How long a single step may wait for its condition. Bounded per step rather than per run, so a failure names the step that hung.",
        cast=as_int,
        default=10000,
    ),
    Field(
        "TRACE",
        "Capture a Playwright trace for every run, not just failures. Costs time and disk; worth it while debugging a flake you cannot pin down.",
        cast=as_bool,
        default=False,
    ),
    Field(
        "STORAGE_STATE",
        "Path to a saved browser session (cookies, localStorage). Reusing one avoids logging in on every run — faster, and far less likely to trip a rate limit or a bot check.",
        commented=True,
    ),
]
