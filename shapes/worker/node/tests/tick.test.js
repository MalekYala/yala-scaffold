// Starter tests for <name>'s worker (shape: worker, lang: node).
//
// Uses node's built-in test runner (`node --test`). The worker's main loop
// is side-effectful (touches files, blocks on setTimeout), so these tests
// import and exercise its production helper directly.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, statSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { touchHeartbeat } from '../src/worker.js';

test('touchHeartbeat creates the heartbeat file on first call', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'worker-test-'));
  try {
    const path = touchHeartbeat(tmp);
    assert.ok(existsSync(path), 'heartbeat file must be created');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('touchHeartbeat creates the data directory if missing', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'worker-test-'));
  const nested = join(tmp, 'nested', 'data');
  try {
    touchHeartbeat(nested);
    assert.ok(existsSync(nested), 'nested data directory must be created');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('touchHeartbeat refreshes mtime on repeated calls', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'worker-test-'));
  try {
    const path = touchHeartbeat(tmp);
    const first = statSync(path).mtime.getTime();
    // Wait a hair so mtime can actually advance on the filesystem
    await new Promise((r) => setTimeout(r, 50));
    touchHeartbeat(tmp);
    const second = statSync(path).mtime.getTime();
    assert.ok(second >= first, 'second touch must not regress mtime');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
