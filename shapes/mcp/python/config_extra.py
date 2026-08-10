"""Shape-specific configuration for <name> (shape: mcp).

An MCP server runs as a subprocess launched by its client, so it has no port
and no bind address — the universal PORT/HOST fields are unused here. What it
does need is a bound on how long a tool may run, because a hung tool call
blocks the client's whole session with no feedback.
"""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "TOOL_TIMEOUT_S",
        "Seconds a single tool call may run before it is abandoned. A hung call blocks the client session with no feedback, so bound it.",
        cast=as_int,
        default=30,
        section="MCP server",
    ),
    Field(
        "MAX_RESULT_BYTES",
        "Largest tool result returned to the client. Oversized results blow up the model's context window rather than failing cleanly.",
        cast=as_int,
        default=1048576,
    ),
]
