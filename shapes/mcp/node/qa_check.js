#!/usr/bin/env node
/**
 * End-to-end check for <name> (shape: mcp).
 *
 * Speaks the actual MCP protocol to a freshly launched server over stdio and
 * asserts the contract a client depends on:
 *
 *   1. handshake       — `initialize` completes and the server identifies itself
 *   2. tools_declared  — `tools/list` returns at least one tool
 *   3. schemas         — every tool has a usable JSON Schema for its input
 *   4. surface_matches — the running server exposes exactly what server.js declares
 *   5. round_trip      — every tool can actually be called and returns content
 *   6. stdout_clean    — nothing but JSON-RPC came back on stdout
 *
 * **Finding zero tools is a failure, not a pass.** A server that starts,
 * handshakes and exposes nothing looks healthy to a process monitor and is
 * useless. Reporting success there is worse than failing: it looks like
 * coverage.
 *
 * Two details worth keeping if you rewrite this:
 *
 * A failed tool call comes back as a *successful* JSON-RPC reply with
 * `isError: true` and the message in `content` — not as a protocol error.
 * Ignoring that flag makes every broken tool look like a working one.
 *
 * stdout is checked after teardown as well as during the conversation, because
 * a buffered console.log() can flush at process exit, long after the last
 * reply.
 *
 * Usage:
 *   node qa_check.js
 *   node qa_check.js --command "node src/server.js"
 *
 * Exit codes: 0 all checks passed, 1 a check failed.
 */

import { spawn } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { TOOLS } from './src/server.js';

const PROJECT_ROOT = path.dirname(fileURLToPath(import.meta.url));
const PROTOCOL_VERSION = '2024-11-05';

class StdioClient {
  constructor(command, timeoutMs) {
    this.timeoutMs = timeoutMs;
    this.nextId = 0;
    this.buffer = '';
    this.pending = new Map();
    this.stderr = [];
    this.stdoutGarbage = [];

    const [cmd, ...args] = command.split(' ');
    this.child = spawn(cmd, args, { cwd: PROJECT_ROOT, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child.stdout.setEncoding('utf8');
    this.child.stderr.setEncoding('utf8');
    this.child.stdout.on('data', (chunk) => this.onStdout(chunk));
    this.child.stderr.on('data', (chunk) => this.stderr.push(chunk));
    this.exited = new Promise((resolve) => this.child.on('close', resolve));
  }

  onStdout(chunk) {
    this.buffer += chunk;
    let index;
    while ((index = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      try {
        const payload = JSON.parse(line);
        const resolver = this.pending.get(payload.id);
        if (resolver) {
          this.pending.delete(payload.id);
          resolver(payload);
        }
      } catch {
        // Almost always a console.log() in the server.
        this.stdoutGarbage.push(line);
      }
    }
  }

  request(method, params) {
    const id = ++this.nextId;
    const message = { jsonrpc: '2.0', id, method, ...(params ? { params } : {}) };
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new Error(
            `no reply to ${method} within ${this.timeoutMs}ms; stderr:\n${this.stderrText()}`,
          ),
        );
      }, this.timeoutMs);
      this.pending.set(id, (payload) => {
        clearTimeout(timer);
        resolve(payload);
      });
      this.child.on('close', () => {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(
          new Error(
            `server exited before replying to ${method}; stderr:\n${this.stderrText()}`,
          ),
        );
      });
    });
  }

  notify(method, params) {
    const message = { jsonrpc: '2.0', method, ...(params ? { params } : {}) };
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  stderrText() {
    return this.stderr.join('').trim() || '(server wrote nothing to stderr)';
  }

  async close() {
    try {
      this.child.stdin.end();
      this.child.kill();
      await this.exited;
    } catch {
      /* teardown must never mask a real failure */
    }
    // Anything still buffered — a console.log() that flushed at exit.
    if (this.buffer.trim()) {
      for (const line of this.buffer.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          JSON.parse(trimmed);
        } catch {
          this.stdoutGarbage.push(trimmed);
        }
      }
    }
  }
}

export function validSchema(schema) {
  if (typeof schema !== 'object' || schema === null) return 'inputSchema is not an object';
  if (schema.type !== 'object') return `inputSchema.type is ${schema.type}, expected 'object'`;
  const properties = schema.properties ?? {};
  if (typeof properties !== 'object') return 'inputSchema.properties is not an object';
  for (const [name, spec] of Object.entries(properties)) {
    if (typeof spec !== 'object' || spec === null || !('type' in spec)) {
      return `property '${name}' has no declared type`;
    }
  }
  const required = schema.required ?? [];
  if (!Array.isArray(required)) return 'inputSchema.required is not a list';
  for (const name of required) {
    if (!(name in properties)) return `required lists '${name}', which is not in properties`;
  }
  return null;
}

async function run(command, timeoutMs) {
  const checks = [];
  const client = new StdioClient(command, timeoutMs);

  try {
    // 1. handshake
    try {
      const reply = await client.request('initialize', {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: 'qa_check', version: '1.0' },
      });
      const info = reply.result?.serverInfo ?? {};
      checks.push({
        name: 'handshake',
        ok: Boolean(reply.result && info.name),
        detail: info.name ? `serverInfo=${JSON.stringify(info)}` : JSON.stringify(reply).slice(0, 200),
      });
      client.notify('notifications/initialized');
    } catch (error) {
      checks.push({ name: 'handshake', ok: false, detail: error.message });
      return { status: 'fail', checks };
    }

    // 2. tools_declared — zero tools is a failure
    let live = [];
    try {
      const reply = await client.request('tools/list');
      live = reply.result?.tools ?? [];
    } catch (error) {
      checks.push({ name: 'tools_declared', ok: false, detail: error.message });
      return { status: 'fail', checks };
    }
    checks.push({
      name: 'tools_declared',
      ok: live.length > 0,
      detail: live.length
        ? `${live.length} tool(s): ${live.map((t) => t.name).join(', ')}`
        : 'a server exposing no tools is useless, not healthy',
    });

    // 3. schemas
    const schemaProblems = live
      .map((tool) => {
        const problem = validSchema(tool.inputSchema);
        return problem ? `${tool.name}: ${problem}` : null;
      })
      .filter(Boolean);
    checks.push({
      name: 'schemas',
      ok: schemaProblems.length === 0,
      detail: schemaProblems.length ? schemaProblems.join('; ') : 'all input schemas usable',
    });

    // 4. surface_matches
    const liveNames = new Set(live.map((t) => t.name));
    const declaredNames = new Set(TOOLS.map((t) => t.name));
    const missing = [...declaredNames].filter((n) => !liveNames.has(n));
    const extra = [...liveNames].filter((n) => !declaredNames.has(n));
    checks.push({
      name: 'surface_matches',
      ok: missing.length === 0 && extra.length === 0,
      detail:
        missing.length || extra.length
          ? `declared-but-absent=[${missing}] exposed-but-undeclared=[${extra}]`
          : 'running surface matches TOOLS',
    });

    // 5. round_trip
    const failures = [];
    for (const tool of TOOLS) {
      if (!liveNames.has(tool.name)) continue;
      try {
        const reply = await client.request('tools/call', {
          name: tool.name,
          arguments: tool.exampleArgs ?? {},
        });
        const result = reply.result ?? {};
        const content = result.content ?? [];
        if (reply.error) {
          failures.push(`${tool.name}: ${reply.error.message}`);
        } else if (result.isError) {
          const text = content.map((c) => c.text ?? '').join(' ').trim();
          failures.push(`${tool.name}: tool reported an error: ${text.slice(0, 120)}`);
        } else if (content.length === 0) {
          failures.push(`${tool.name}: returned no content`);
        }
      } catch (error) {
        failures.push(`${tool.name}: ${error.message}`);
      }
    }
    checks.push({
      name: 'round_trip',
      ok: failures.length === 0,
      detail: failures.length ? failures.join('; ') : `${TOOLS.length} tool(s) callable`,
    });
  } finally {
    await client.close();
  }

  // 6. stdout_clean — after teardown, so a late flush is still caught.
  checks.push({
    name: 'stdout_clean',
    ok: client.stdoutGarbage.length === 0,
    detail: client.stdoutGarbage.length
      ? `${client.stdoutGarbage.length} non-JSON line(s) on stdout, which corrupt the protocol stream: ${JSON.stringify(client.stdoutGarbage[0]?.slice(0, 120))}`
      : 'stdout carried only JSON-RPC',
  });

  return { status: checks.every((c) => c.ok) ? 'ok' : 'fail', checks };
}

const args = process.argv.slice(2);
const commandIndex = args.indexOf('--command');
const command = commandIndex !== -1 ? args[commandIndex + 1] : 'node src/server.js';
const started = Date.now();
const result = await run(command, 20000);
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
process.stderr.write(
  `[<name>-perf] phase=qa_check duration_ms=${Date.now() - started} checks=${result.checks.length} status=${result.status}\n`,
);
process.exit(result.status === 'ok' ? 0 : 1);
