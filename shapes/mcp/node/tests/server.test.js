import assert from 'node:assert/strict';
import { test } from 'node:test';

import { validSchema } from '../qa_check.js';
import { HANDLERS, TOOLS } from '../src/server.js';

// The contract these protect is the tool surface: names, schemas, and the
// declared-vs-implemented correspondence. Breaking it breaks every client
// silently, because nothing validates it at runtime on either side.

test('at least one tool is declared', () => {
  // A server exposing nothing passes every process-level health check and is
  // still useless. Emptiness is a bug, here and in qa_check.
  assert.ok(TOOLS.length > 0);
});

test('tool names are unique', () => {
  const names = TOOLS.map((t) => t.name);
  assert.equal(names.length, new Set(names).size);
});

test('every declared tool has a handler', () => {
  for (const tool of TOOLS) {
    assert.ok(HANDLERS[tool.name], `${tool.name} declared but not implemented`);
  }
});

test('every handler is declared', () => {
  const declared = new Set(TOOLS.map((t) => t.name));
  for (const name of Object.keys(HANDLERS)) {
    assert.ok(declared.has(name), `${name} implemented but not declared in TOOLS`);
  }
});

test('every tool has a description', () => {
  for (const tool of TOOLS) {
    assert.ok(tool.description?.trim(), `${tool.name} has no description`);
  }
});

test('every schema is usable', () => {
  for (const tool of TOOLS) {
    assert.equal(validSchema(tool.inputSchema), null, tool.name);
  }
});

test('exampleArgs satisfy required fields', () => {
  // qa_check round-trips each tool with these, so they must be valid or the
  // check fails for the wrong reason.
  for (const tool of TOOLS) {
    for (const field of tool.inputSchema.required ?? []) {
      assert.ok(field in (tool.exampleArgs ?? {}), `${tool.name}: exampleArgs lacks ${field}`);
    }
  }
});

test('echo returns its input unchanged', async () => {
  assert.equal(await HANDLERS.echo({ text: 'round trip' }), 'round trip');
});

test('echo rejects a missing argument', async () => {
  // Throwing is correct: MCP distinguishes a failed call from a successful
  // one returning an error string, and clients rely on that.
  await assert.rejects(() => HANDLERS.echo({}));
});

test('echo rejects a wrongly typed argument', async () => {
  await assert.rejects(() => HANDLERS.echo({ text: 42 }));
});

test('server_info reports the declared tool count', async () => {
  const info = JSON.parse(await HANDLERS.server_info({}));
  assert.equal(info.tools, TOOLS.length);
});

test('validSchema rejects a non-object schema', () => {
  assert.notEqual(validSchema({ type: 'string' }), null);
});

test('validSchema rejects a property without a type', () => {
  assert.notEqual(validSchema({ type: 'object', properties: { x: {} } }), null);
});

test('validSchema rejects required naming an undeclared property', () => {
  assert.notEqual(validSchema({ type: 'object', properties: {}, required: ['missing'] }), null);
});
