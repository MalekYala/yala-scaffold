"""Tests for <name>'s MCP tool surface.

The contract these protect is the tool surface: names, schemas, and the
declared-vs-implemented correspondence. Breaking it breaks every client
silently, because nothing validates it at runtime on either side.

The full protocol round-trip lives in qa_check.py, which launches a real
server and speaks JSON-RPC to it. These are the fast unit-level checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402
from qa_check import valid_schema  # noqa: E402


class TestToolDeclarations:
    def test_at_least_one_tool_is_declared(self):
        # A server exposing nothing passes every process-level health check
        # and is still useless. Treat emptiness as a bug, here and in qa_check.
        assert len(server.TOOLS) > 0

    def test_tool_names_are_unique(self):
        names = [t["name"] for t in server.TOOLS]
        assert len(names) == len(set(names))

    def test_every_declared_tool_has_a_handler(self):
        for tool in server.TOOLS:
            assert tool["name"] in server.HANDLERS, f"{tool['name']} declared but not implemented"

    def test_every_handler_is_declared(self):
        declared = {t["name"] for t in server.TOOLS}
        for name in server.HANDLERS:
            assert name in declared, f"{name} implemented but not declared in TOOLS"

    def test_every_tool_has_a_description(self):
        for tool in server.TOOLS:
            assert tool.get("description", "").strip(), f"{tool['name']} has no description"

    def test_every_schema_is_usable(self):
        for tool in server.TOOLS:
            assert valid_schema(tool["inputSchema"]) is None, tool["name"]

    def test_example_args_satisfy_required_fields(self):
        # qa_check round-trips each tool with these, so they must be valid or
        # the check fails for the wrong reason.
        for tool in server.TOOLS:
            required = tool["inputSchema"].get("required", [])
            example = tool.get("example_args", {})
            for field in required:
                assert field in example, f"{tool['name']}: example_args lacks required {field!r}"


class TestHandlers:
    @pytest.mark.asyncio
    async def test_echo_returns_input_unchanged(self):
        assert await server.call_echo({"text": "round trip"}) == "round trip"

    @pytest.mark.asyncio
    async def test_echo_rejects_a_missing_argument(self):
        # Raising is correct: MCP distinguishes a failed call from a
        # successful one returning an error string, and clients rely on that.
        with pytest.raises(ValueError):
            await server.call_echo({})

    @pytest.mark.asyncio
    async def test_echo_rejects_a_wrongly_typed_argument(self):
        with pytest.raises(ValueError):
            await server.call_echo({"text": 42})

    @pytest.mark.asyncio
    async def test_server_info_reports_the_declared_tool_count(self):
        info = json.loads(await server.call_server_info({}))
        assert info["tools"] == len(server.TOOLS)
        assert info["server"]


class TestSchemaValidator:
    def test_rejects_a_non_object_schema(self):
        assert valid_schema({"type": "string"}) is not None

    def test_rejects_a_property_without_a_type(self):
        assert valid_schema({"type": "object", "properties": {"x": {}}}) is not None

    def test_rejects_required_naming_an_undeclared_property(self):
        schema = {"type": "object", "properties": {}, "required": ["missing"]}
        assert valid_schema(schema) is not None

    def test_accepts_an_empty_object_schema(self):
        assert valid_schema({"type": "object", "properties": {}}) is None
