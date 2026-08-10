// Starter tests for <name>'s HTTP service (shape: service, lang: node).
//
// Uses node's built-in test runner (`node --test`) — no external test
// framework required. Exercises the Fastify app via `inject()` which
// calls the handlers in-process without binding a port.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildApp } from '../src/index.js';

test('GET /health returns 200', async () => {
  const app = buildApp({ logger: false });
  try {
    const response = await app.inject({ method: 'GET', url: '/health' });
    assert.equal(response.statusCode, 200);
  } finally {
    await app.close();
  }
});

test('GET /health returns {status: "ok"}', async () => {
  const app = buildApp({ logger: false });
  try {
    const response = await app.inject({ method: 'GET', url: '/health' });
    const body = response.json();
    assert.equal(body.status, 'ok');
    assert.ok(body.service, 'service field must be present and non-empty');
  } finally {
    await app.close();
  }
});

test('GET /unknown returns 404', async () => {
  const app = buildApp({ logger: false });
  try {
    const response = await app.inject({ method: 'GET', url: '/definitely-not-a-route' });
    assert.equal(response.statusCode, 404);
  } finally {
    await app.close();
  }
});
