// Minimal Fastify service stub for <name>.
//
// Shape: service (long-running HTTP API).
//
// The `/health` endpoint and structured perf-log format are required by
// AGENTS.md — do not remove them. Replace everything else with your real
// implementation.

import Fastify from 'fastify';

import { load } from './config.js';

// Every environment variable comes from here, validated, or the process does
// not start. Never read process.env directly — see src/config.js for why.
const settings = load();

export function buildApp({ logger = { level: settings.LOG_LEVEL } } = {}) {
  const app = Fastify({ logger });

  app.get('/health', async () => {
    const startedAt = process.hrtime.bigint();
    // TODO: add real dependency checks (DB, Redis, downstream APIs)
    const durationMs = Number(process.hrtime.bigint() - startedAt) / 1_000_000;
    app.log.info(
      `[<name>-perf] phase=health duration_ms=${durationMs.toFixed(1)} status=ok`,
    );
    // The version is part of the response on purpose: during an incident the
    // question is almost never "is something running" but "*which build* is
    // running", and an endpoint that cannot answer that sends you to the
    // deployment logs to guess.
    return {
      status: 'ok',
      service: '<name>',
      version: settings.APP_VERSION,
      env: settings.ENV,
    };
  });

  return app;
}

export async function start({
  host = settings.HOST,
  port = settings.PORT,
  logger,
} = {}) {
  const app = buildApp({ logger });
  await app.listen({ host, port });
  app.log.info(`<name> listening on http://${host}:${port}`);
  return app;
}

async function run() {
  let app;
  const shutdown = async (signal) => {
    app?.log.info(`received ${signal} — shutting down`);
    try {
      await app?.close();
      process.exitCode = 0;
    } catch (err) {
      app?.log.error(err, 'error during shutdown');
      process.exitCode = 1;
    }
  };

  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, () => void shutdown(signal));
  }

  try {
    app = await start();
  } catch (err) {
    console.error(err);
    process.exitCode = 1;
  }
}

if (import.meta.url === new URL(process.argv[1], 'file:').href) {
  await run();
}
