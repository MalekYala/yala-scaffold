"""MCP server stub for <name>.

Shape: mcp (Model Context Protocol server over stdio).

An MCP server's contract is its **tool surface**: the names, the input schemas,
and what each call returns. That surface is what a client — Claude Code, an
IDE, an agent — binds against, and breaking it breaks every consumer silently,
because nothing on either side validates it at runtime.

So the tools are declared once, as data, in `TOOLS` below. `qa_check.py` reads
the same declaration and asserts the running server actually matches it. A tool
you add to the handler but forget to declare, or declare but never implement,
fails the check rather than shipping.

Transport is stdio, which is what MCP clients launch. That means **stdout
belongs to the protocol** — a stray `print()` corrupts the JSON-RPC stream and
produces a client-side parse error that points nowhere near the cause. Log to
stderr, always. The logging setup below enforces it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

import config

settings = config.load()

# stderr, never stdout: stdout is the JSON-RPC transport. This is the single
# most common way to break an MCP server, and it fails far from its cause.
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("<name>")

SERVER_NAME = "<name>"


# ── Tool surface ───────────────────────────────────────────────────────────
# Declared as data so the server and qa_check.py cannot disagree about it.
# `example_args` is what qa_check uses to round-trip each tool: a call that
# must succeed against a freshly started server with no external state.

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Return the supplied text unchanged. Useful as a liveness probe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo back"},
            },
            "required": ["text"],
        },
        "example_args": {"text": "hello"},
    },
    {
        "name": "server_info",
        "description": "Report this server's name, version and declared tool count.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "example_args": {},
    },
]


async def call_echo(arguments: dict[str, Any]) -> str:
    text = arguments.get("text")
    if not isinstance(text, str):
        # Raise rather than returning an error string: MCP distinguishes a
        # failed call from a successful call that returned text, and a client
        # cannot tell the difference if you collapse them.
        raise ValueError("`text` is required and must be a string")
    return text


async def call_server_info(_arguments: dict[str, Any]) -> str:
    return json.dumps(
        {
            "server": SERVER_NAME,
            "version": settings.app_version,
            "tools": len(TOOLS),
            "env": settings.env,
        },
        indent=2,
    )


HANDLERS = {
    "echo": call_echo,
    "server_info": call_server_info,
}


def build_server() -> Server[Any]:
    """Construct the MCP server. Separated from `main` so tests can drive it."""
    server: Server[Any] = Server(SERVER_NAME)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
            )
            for tool in TOOLS
        ]

    @server.call_tool()  # type: ignore[no-untyped-call, untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        started = time.monotonic()
        handler = HANDLERS.get(name)
        if handler is None:
            # A declared-but-unimplemented tool is a contract violation, and
            # qa_check exists to catch it before a client does.
            raise ValueError(f"unknown tool: {name}")

        result = await handler(arguments or {})
        elapsed = int((time.monotonic() - started) * 1000)
        log.info(f"[<name>-perf] phase=call_tool duration_ms={elapsed} tool={name}")
        return [types.TextContent(type="text", text=result)]

    return server


async def main() -> None:
    server = build_server()
    log.info(f"{SERVER_NAME} starting on stdio with {len(TOOLS)} tool(s)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
