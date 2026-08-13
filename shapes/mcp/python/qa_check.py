#!/usr/bin/env python3
"""End-to-end check for <name> (shape: mcp).

Speaks the actual MCP protocol to a freshly launched server over stdio and
asserts the contract a client depends on:

  1. handshake       — `initialize` completes and the server identifies itself
  2. tools_declared  — `tools/list` returns at least one tool
  3. schemas         — every tool has a usable JSON Schema for its input
  4. surface_matches — the running server exposes exactly what server.py declares
  5. round_trip      — every tool can actually be called and returns content
  6. stdout_clean    — nothing but JSON-RPC came back on stdout

**Finding zero tools is a failure, not a pass.** A server that starts, completes
the handshake and exposes nothing looks perfectly healthy to a process monitor,
a container healthcheck, and a port scan. It is also completely useless, and
without this rule the check would report success — which is worse than failing,
because it looks like coverage.

Check 6 exists because stdio is the transport: a stray `print()` anywhere in the
server corrupts the JSON-RPC stream, and the resulting client-side parse error
points nowhere near the cause.

Usage:
    python3 qa_check.py
    python3 qa_check.py --command "python3 server.py"
    python3 qa_check.py --timeout 30

Exit codes:
    0  every check passed
    1  a check failed
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
PROTOCOL_VERSION = "2024-11-05"


class StdioClient:
    """A minimal MCP client over stdio.

    Deliberately hand-rolled rather than importing the SDK's client: this is
    the check that proves the wire format is right, and running both sides
    through the same library would let a shared bug pass unnoticed.
    """

    def __init__(self, command: str, timeout: float) -> None:
        self.timeout = timeout
        self._next_id = 0
        self._stderr: list[str] = []
        # Non-JSON seen on stdout. Recorded rather than only raised, because
        # a print() that block-buffers and flushes at process exit corrupts a
        # real client session but arrives after the last request completes.
        self.stdout_garbage: list[str] = []
        self.process = subprocess.Popen(
            command,
            shell=True,
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # Drain stderr on a background thread. Without this, a server that
        # dies at launch — a missing dependency, a syntax error, the wrong
        # interpreter — reports only "closed stdout", which tells you nothing.
        # The traceback is right there on stderr; it just has to be collected
        # before the pipe is torn down.
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stderr(self) -> None:
        if not self.process.stderr:
            return
        for line in self.process.stderr:
            self._stderr.append(line.rstrip("\n"))

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        return self._send(message, expect_reply=True)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message, expect_reply=False)

    def _send(self, message: dict[str, Any], expect_reply: bool) -> dict[str, Any]:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if not expect_reply:
            return {}

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"server closed stdout before replying — it most likely crashed; stderr:\n{self._drain_stderr()}")
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                # Almost always a print() to stdout in the server.
                self.stdout_garbage.append(line)
                raise RuntimeError(f"non-JSON on stdout, which corrupts the protocol stream: {line[:200]!r} ({exc})") from None
            # Skip notifications and unrelated ids.
            if payload.get("id") == message["id"]:
                return dict(payload)
        raise TimeoutError(f"no reply to {message['method']} within {self.timeout}s; stderr:\n{self._drain_stderr()}")

    def _drain_stderr(self) -> str:
        # Give the pump a moment to catch a traceback written just before exit.
        time.sleep(0.2)
        return "\n".join(self._stderr[-25:]) or "(server wrote nothing to stderr)"

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:  # teardown must never mask a real failure
            self.process.kill()
        # Drain whatever is left on stdout. A buffered print() flushes here,
        # at exit — long after the last reply — so checking only during the
        # conversation misses the most common way stdio servers get corrupted.
        try:
            if self.process.stdout:
                for line in self.process.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        self.stdout_garbage.append(line)
        except Exception:
            pass


def declared_tools() -> list[dict[str, Any]]:
    """The tool surface server.py declares, read without starting a server."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import server
    except Exception as exc:
        raise RuntimeError(f"cannot import server.py to read its declared tools: {exc}") from None
    return list(getattr(server, "TOOLS", []))


def valid_schema(schema: object) -> str | None:
    """Minimal structural check on a tool's inputSchema."""
    if not isinstance(schema, dict):
        return "inputSchema is not an object"
    if schema.get("type") != "object":
        return f"inputSchema.type is {schema.get('type')!r}, expected 'object'"
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return "inputSchema.properties is not an object"
    for name, spec in properties.items():
        if not isinstance(spec, dict) or "type" not in spec:
            return f"property {name!r} has no declared type"
    required = schema.get("required", [])
    if not isinstance(required, list):
        return "inputSchema.required is not a list"
    for name in required:
        if name not in properties:
            return f"required lists {name!r}, which is not in properties"
    return None


def run(command: str, timeout: float) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    client: StdioClient | None = None

    try:
        declared = declared_tools()
    except RuntimeError as exc:
        return {"status": "fail", "checks": [{"name": "declared_tools", "ok": False, "detail": str(exc)}]}

    try:
        client = StdioClient(command, timeout)

        # 1. handshake
        try:
            reply = client.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "qa_check", "version": "1.0"},
                },
            )
            info = (reply.get("result") or {}).get("serverInfo") or {}
            ok = "result" in reply and bool(info.get("name"))
            checks.append(
                {
                    "name": "handshake",
                    "ok": ok,
                    "detail": f"serverInfo={info}" if ok else f"unexpected reply: {str(reply)[:200]}",
                }
            )
            client.notify("notifications/initialized")
        except Exception as exc:
            checks.append({"name": "handshake", "ok": False, "detail": str(exc)})
            return {"status": "fail", "checks": checks}

        # 2. tools_declared — zero tools is a failure.
        try:
            reply = client.request("tools/list")
            live = (reply.get("result") or {}).get("tools") or []
        except Exception as exc:
            checks.append({"name": "tools_declared", "ok": False, "detail": str(exc)})
            return {"status": "fail", "checks": checks}

        checks.append(
            {
                "name": "tools_declared",
                "ok": len(live) > 0,
                "detail": f"{len(live)} tool(s): {[t.get('name') for t in live]}" + ("" if live else " — a server exposing no tools is useless, not healthy"),
            }
        )

        # 3. schemas
        schema_problems = []
        for tool in live:
            problem = valid_schema(tool.get("inputSchema"))
            if problem:
                schema_problems.append(f"{tool.get('name')}: {problem}")
        checks.append(
            {
                "name": "schemas",
                "ok": not schema_problems,
                "detail": "all input schemas usable" if not schema_problems else "; ".join(schema_problems),
            }
        )

        # 4. surface_matches — the running server vs what server.py declares.
        # A tool without a name is malformed; "" keeps the sets sortable and
        # surfaces it as a mismatch rather than crashing the comparison.
        live_names: set[str] = {str(t.get("name", "")) for t in live}
        declared_names: set[str] = {str(t.get("name", "")) for t in declared}
        missing = declared_names - live_names
        extra = live_names - declared_names
        checks.append(
            {
                "name": "surface_matches",
                "ok": not missing and not extra,
                "detail": "running surface matches TOOLS" if not missing and not extra else f"declared-but-absent={sorted(missing)} exposed-but-undeclared={sorted(extra)}",
            }
        )

        # 5. round_trip — every declared tool must actually be callable.
        failures = []
        for tool in declared:
            name = tool.get("name")
            if name not in live_names:
                continue
            try:
                reply = client.request(
                    "tools/call",
                    {"name": name, "arguments": tool.get("example_args", {})},
                )
                result = reply.get("result") or {}
                content = result.get("content") or []
                if reply.get("error"):
                    failures.append(f"{name}: {reply['error'].get('message')}")
                elif result.get("isError"):
                    # A failed call comes back as a *successful* JSON-RPC reply
                    # with isError set and the message in content. Ignoring this
                    # flag makes every broken tool look like a working one.
                    text = " ".join(c.get("text", "") for c in content if isinstance(c, dict)).strip()
                    failures.append(f"{name}: tool reported an error: {text[:120]}")
                elif not content:
                    failures.append(f"{name}: returned no content")
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        checks.append(
            {
                "name": "round_trip",
                "ok": not failures,
                "detail": f"{len(declared)} tool(s) callable" if not failures else "; ".join(failures),
            }
        )

    finally:
        if client is not None:
            client.close()

    # 6. stdout_clean — asserted after teardown, so a buffered print() that
    # only flushes at exit is still caught.
    garbage = client.stdout_garbage if client is not None else []
    checks.append(
        {
            "name": "stdout_clean",
            "ok": not garbage,
            "detail": "stdout carried only JSON-RPC" if not garbage else f"{len(garbage)} non-JSON line(s) on stdout, which corrupt the protocol stream: {garbage[0][:120]!r}",
        }
    )

    return {"status": "ok" if all(c["ok"] for c in checks) else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check this MCP server's contract")
    parser.add_argument("--command", default="python3 server.py", help="how to launch the server")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    _t = time.monotonic()
    result = run(args.command, args.timeout)
    elapsed = int((time.monotonic() - _t) * 1000)

    print(json.dumps(result, indent=2))
    print(
        f"[<name>-perf] phase=qa_check duration_ms={elapsed} checks={len(result['checks'])} status={result['status']}",
        file=sys.stderr,
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
