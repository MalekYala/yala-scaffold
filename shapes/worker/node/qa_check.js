#!/usr/bin/env node
// End-to-end check for <name> (shape: worker, lang: node).
//
// A worker has no HTTP surface, so health is a combination of:
//   1. The heartbeat file is fresh (worker is alive and looping).
//   2. Recent perf logs show successful processing (no runaway error rate).
//
// Run inside the running container:
//     docker compose exec <name> node /app/qa_check.js

import 'dotenv/config';
import { statSync } from 'node:fs';
import { join } from 'node:path';

const name = '<name>';

async function run() {
  const dataDir = process.env.DATA_DIR || 'data';
  const heartbeatPath = join(dataDir, 'heartbeat');
  const maxAgeS = parseInt(process.env.HEARTBEAT_MAX_AGE_S || '60', 10);

  const results = { checks: [], status: 'ok' };

  // Check 1: heartbeat file exists and is fresh
  try {
    const ageS = (Date.now() - statSync(heartbeatPath).mtimeMs) / 1000;
    const ok = ageS < maxAgeS;
    results.checks.push({
      name: 'heartbeat_fresh',
      ok,
      age_s: Math.round(ageS * 10) / 10,
      max_age_s: maxAgeS,
    });
    if (!ok) results.status = 'fail';
  } catch {
    results.checks.push({
      name: 'heartbeat_fresh',
      ok: false,
      error: `heartbeat file ${heartbeatPath} not found — worker never started?`,
    });
    results.status = 'fail';
  }

  // TODO: add checks for worker-specific success signals:
  //   - recent jobs_completed count > 0 over the last minute
  //   - error rate from perf logs < threshold
  //   - queue depth below threshold
  return results;
}

export const CHECKER_CLASS = { name, run };

if (import.meta.url === `file://${process.argv[1]}`) {
  const result = await run();
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.status === 'ok' ? 0 : 1);
}
