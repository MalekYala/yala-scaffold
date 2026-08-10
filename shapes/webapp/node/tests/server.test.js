import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { buildApp } from '../server.js';

const fixtures = resolve('tests/fixtures');

async function createApp() {
  return buildApp({
    logger: false,
    brandConfigPath: resolve(fixtures, 'brand/config.json'),
    brandDir: resolve(fixtures, 'brand'),
    localesDir: resolve(fixtures, 'locales'),
    distDir: resolve(fixtures, 'dist'),
  });
}

test('GET /health reports the fixture brand as healthy', async () => {
  const app = await createApp();
  try {
    const response = await app.inject({ method: 'GET', url: '/health' });
    assert.equal(response.statusCode, 200);
    assert.deepEqual(response.json(), {
      status: 'ok',
      service: '<name>',
      brand_ok: true,
      default_locale: 'en',
    });
  } finally {
    await app.close();
  }
});

test('GET /api/brand returns the production brand response', async () => {
  const app = await createApp();
  try {
    const response = await app.inject({ method: 'GET', url: '/api/brand' });
    assert.equal(response.statusCode, 200);
    assert.equal(response.headers['cache-control'], 'no-cache, must-revalidate');
    assert.equal(response.json().colors.primary, '#1f77b4');
  } finally {
    await app.close();
  }
});

test('GET /api/locales discovers locale files', async () => {
  const app = await createApp();
  try {
    const response = await app.inject({ method: 'GET', url: '/api/locales' });
    assert.equal(response.statusCode, 200);
    assert.deepEqual(response.json(), { default: 'en', available: ['en'] });
  } finally {
    await app.close();
  }
});

test('unknown API routes return 404 instead of the SPA', async () => {
  const app = await createApp();
  try {
    const response = await app.inject({ method: 'GET', url: '/api/not-a-route' });
    assert.equal(response.statusCode, 404);
  } finally {
    await app.close();
  }
});
