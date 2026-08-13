// Background worker stub for <name>.
//
// Shape: worker (long-running background process, no HTTP surface).
//
// Main loop responsibilities on every tick:
//   1. Touch data/heartbeat so the compose healthcheck stays green.
//   2. Pull a batch of work (replace `pullBatch` with your real source).
//   3. Process each item, emit structured perf logs per AGENTS.md §8.
//
// Stop conditions: SIGTERM (graceful) or the file `STOP_WORKER` in cwd.

import 'dotenv/config';
import { existsSync, mkdirSync, utimesSync, closeSync, openSync } from 'node:fs';
import { join } from 'node:path';

export function createLogger(logLevel = process.env.LOG_LEVEL || 'info') {
  return {
    info: (msg, ...args) => console.log(`${new Date().toISOString()} [<name>] INFO ${msg}`, ...args),
    warn: (msg, ...args) => console.log(`${new Date().toISOString()} [<name>] WARN ${msg}`, ...args),
    error: (msg, ...args) => console.error(`${new Date().toISOString()} [<name>] ERROR ${msg}`, ...args),
    debug: logLevel.toUpperCase() === 'DEBUG'
    ? (msg, ...args) => console.log(`${new Date().toISOString()} [<name>] DEBUG ${msg}`, ...args)
    : () => {},
  };
}

export function touchHeartbeat(dataDir = process.env.DATA_DIR || 'data') {
  const heartbeat = join(dataDir, 'heartbeat');
  mkdirSync(dataDir, { recursive: true });
  if (!existsSync(heartbeat)) {
    closeSync(openSync(heartbeat, 'w'));
  }
  const now = new Date();
  utimesSync(heartbeat, now, now);
  return heartbeat;
}

// Pull up to BATCH_SIZE items of work. Replace with a real source: Redis
// BLPOP, SQS receiveMessage, Postgres SELECT ... FOR UPDATE SKIP LOCKED, etc.
// Returns [] when there's no work.
export async function pullBatch() {
  // TODO: replace with real source
  return [];
}

// Process a single item. Return true on success, false on failure.
// Must be idempotent — the same item may be delivered more than once
// (see AGENTS.md §12).
export async function processItem(_item) {
  // TODO: replace with real work
  return true;
}

export async function runWorker({
  batchSize = parseInt(process.env.BATCH_SIZE || '10', 10),
  dataDir = process.env.DATA_DIR || 'data',
  pollIntervalMs = parseInt(process.env.POLL_INTERVAL_S || '5', 10) * 1000,
  stopFile = 'STOP_WORKER',
  shouldShutdown = () => false,
  fetchBatch = pullBatch,
  handleItem = processItem,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  log = createLogger(),
} = {}) {
  log.info(`<name> worker starting (batch_size=${batchSize} poll=${pollIntervalMs / 1000}s)`);
  touchHeartbeat(dataDir);

  while (!shouldShutdown()) {
    if (existsSync(stopFile)) {
      log.info('STOP_WORKER file found — exiting');
      break;
    }

    const tLoop = process.hrtime.bigint();
    touchHeartbeat(dataDir);

    const tPull = process.hrtime.bigint();
    const batch = await fetchBatch(batchSize);
    const pullMs = Number(process.hrtime.bigint() - tPull) / 1_000_000;
    log.info(`[<name>-perf] phase=pull duration_ms=${pullMs.toFixed(0)} count=${batch.length}`);

    let okCount = 0;
    for (const item of batch) {
      const tProc = process.hrtime.bigint();
      try {
        if (await handleItem(item)) okCount += 1;
        const procMs = Number(process.hrtime.bigint() - tProc) / 1_000_000;
        log.info(`[<name>-perf] phase=process duration_ms=${procMs.toFixed(0)} status=ok`);
      } catch (err) {
        const procMs = Number(process.hrtime.bigint() - tProc) / 1_000_000;
        log.warn(`[<name>-perf] phase=process duration_ms=${procMs.toFixed(0)} status=fail error=${err}`);
      }
    }

    const loopMs = Number(process.hrtime.bigint() - tLoop) / 1_000_000;
    log.info(`[<name>-perf] phase=loop duration_ms=${loopMs.toFixed(0)} batch=${batch.length} ok=${okCount}`);

    if (batch.length === 0) {
      await sleep(pollIntervalMs);
    }
  }

  log.info('<name> worker exited cleanly');
}

async function main() {
  const log = createLogger();
  let shutdown = false;
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, () => {
      log.info(`received ${signal} — finishing current batch then exiting`);
      shutdown = true;
    });
  }

  try {
    await runWorker({ shouldShutdown: () => shutdown, log });
  } catch (err) {
    log.error(err);
    process.exitCode = 1;
  }
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  await main();
}
