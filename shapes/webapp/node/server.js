// Production server for <name> (shape: webapp).
//
// Serves the built Vite SPA and its runtime brand and locale configuration.

import Fastify from 'fastify';
import fastifyStatic from '@fastify/static';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import 'dotenv/config';

const here = dirname(fileURLToPath(import.meta.url));

export async function buildApp({
  logger = { level: process.env.LOG_LEVEL || 'info' },
  brandConfigPath = process.env.BRAND_CONFIG_PATH || resolve(here, 'brand/config.json'),
  brandDir = resolve(here, 'brand'),
  localesDir = resolve(here, 'locales'),
  distDir = resolve(here, 'dist'),
  defaultLocale = process.env.DEFAULT_LOCALE || 'en',
} = {}) {
  const app = Fastify({ logger });

  app.get('/health', async () => {
    const startedAt = process.hrtime.bigint();
    let brandOk = false;
    try {
      JSON.parse(readFileSync(brandConfigPath, 'utf8'));
      brandOk = true;
    } catch (err) {
      app.log.warn(`brand config unreadable at ${brandConfigPath}: ${err.message}`);
    }
    const durationMs = Number(process.hrtime.bigint() - startedAt) / 1_000_000;
    app.log.info(`[<name>-perf] phase=health duration_ms=${durationMs.toFixed(1)} brand_ok=${brandOk}`);
    return {
      status: brandOk ? 'ok' : 'degraded',
      service: '<name>',
      brand_ok: brandOk,
      default_locale: defaultLocale,
    };
  });

  app.get('/api/brand', async (_request, reply) => {
    try {
      const config = JSON.parse(readFileSync(brandConfigPath, 'utf8'));
      reply.header('cache-control', 'no-cache, must-revalidate');
      return config;
    } catch (err) {
      reply.code(500);
      return { error: 'brand config unreadable', detail: err.message };
    }
  });

  app.get('/api/locales', async () => {
    try {
      const available = readdirSync(localesDir)
        .filter((file) => file.endsWith('.json'))
        .map((file) => file.replace(/\.json$/, ''));
      return { default: defaultLocale, available };
    } catch (err) {
      return { default: defaultLocale, available: [defaultLocale], error: err.message };
    }
  });

  await app.register(fastifyStatic, {
    root: localesDir,
    prefix: '/locales/',
    decorateReply: false,
  });
  await app.register(fastifyStatic, {
    root: brandDir,
    prefix: '/brand/',
    decorateReply: false,
  });
  await app.register(fastifyStatic, {
    root: distDir,
    prefix: '/',
    decorateReply: true,
    wildcard: false,
  });

  app.setNotFoundHandler((request, reply) => {
    if (
      request.method !== 'GET'
      || request.url.startsWith('/api/')
      || request.url.startsWith('/locales/')
      || request.url.startsWith('/brand/')
    ) {
      return reply.code(404).send({ error: 'not found' });
    }
    return reply.sendFile('index.html');
  });

  return app;
}

export async function start({
  host = process.env.HOST || '127.0.0.1',
  port = parseInt(process.env.PORT || '<PORT>', 10),
  ...appOptions
} = {}) {
  const app = await buildApp(appOptions);
  await app.listen({ host, port });
  app.log.info(`<name> webapp listening on http://${host}:${port}`);
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
