#!/usr/bin/env node
// End-to-end health check for <name> (shape: service, lang: node).
//
// Modes:
//     node qa_check.js            // live probe: /health + every GET route
//     node qa_check.js --audit    // static: report discovered route coverage
//     node qa_check.js --smoke    // full E2E: live probe + fail on empty-list
//                                 // responses unless the path is in EMPTY_OK.
//
// --smoke is what the plan-to-PR workflow invokes. It is the difference
// between "/api/channels responded 200" and "/api/channels returned []" — the
// latter is a silent regression and MUST fail the check.
//
// Routes are discovered by scanning the project for `app.get('/path')` and
// `router.get('/path')` calls. A discoverer that only reads one entrypoint
// finds nothing in any service that grew past a single file, and then passes
// every probe over an empty set — so --audit exits non-zero when it finds no
// routes at all. Vacuous success is worse than failure.
//
// Run inside the running container:
//     docker compose exec <name> node /app/qa_check.js
//
// Or against a locally running instance:
//     node qa_check.js

import 'dotenv/config';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const name = '<name>';
const here = dirname(fileURLToPath(import.meta.url));

// Paths where an empty list response is a valid steady state. Extend per-project.
const EMPTY_OK = new Set();

// Directories that never contain servable routes.
const SKIP_DIRS = new Set([
  '.git', 'node_modules', 'tests', 'test', 'bot', 'rag', 'scripts',
  'outputs', 'data', 'memory', 'locales', 'brand', 'dist', 'build', 'coverage',
]);

// Matches app.get('/x'), router.get("/x"), r.get(`/x`) — the method name and
// the string literal are what matter, not what the object is called.
const ROUTE_RE = /\b[A-Za-z_$][\w$]*\s*\.\s*get\s*\(\s*['"`]([^'"`]+)['"`]/g;

function sourceFiles(root) {
  const found = [];
  for (const entry of readdirSync(root)) {
    if (SKIP_DIRS.has(entry) || entry.startsWith('.')) continue;
    const full = join(root, entry);
    let info;
    try {
      info = statSync(full);
    } catch {
      continue;
    }
    if (info.isDirectory()) {
      found.push(...sourceFiles(full));
    } else if (['.js', '.mjs', '.ts'].includes(extname(entry))) {
      if (entry !== 'qa_check.js') found.push(full);
    }
  }
  return found;
}

function discoverGetRoutes(root = here) {
  const seen = new Set();
  for (const file of sourceFiles(root).sort()) {
    let text;
    try {
      text = readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    for (const match of text.matchAll(ROUTE_RE)) {
      const path = match[1];
      // Only real URL paths; skip things like obj.get('key').
      if (path.startsWith('/')) seen.add(path);
    }
  }
  return [...seen];
}

// A parameterised route ("/jobs/:id", "/jobs/{id}") is a 404 by construction —
// the placeholder is not a real path. Probing it reports a permanent,
// meaningless failure that trains everyone to ignore the check.
const isProbeable = (path) => !path.includes(':') && !path.includes('{');

// JSONPath-ish locations of every empty list in a decoded response.
function findEmptyLists(body, prefix = '$') {
  const hits = [];
  if (Array.isArray(body)) {
    if (body.length === 0) hits.push(prefix);
  } else if (body && typeof body === 'object') {
    for (const [key, value] of Object.entries(body)) {
      hits.push(...findEmptyLists(value, `${prefix}.${key}`));
    }
  }
  return hits;
}

async function getJson(url, timeoutMs = 5000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function run({ smoke = false } = {}) {
  const port = process.env.PORT || '<PORT>';
  const host = process.env.HOST || '127.0.0.1';
  const base = `http://${host}:${port}`;
  const results = { checks: [], status: 'ok' };

  // Basic health check — required for every service (AGENTS.md §14)
  try {
    const res = await getJson(`${base}/health`);
    const ok = res.status === 200;
    results.checks.push({ name: 'health', ok, status_code: res.status });
    if (!ok) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'health', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
    return results;
  }

  const discovered = discoverGetRoutes();
  const probeable = discovered.filter((p) => p !== '/health' && isProbeable(p));

  // Finding no routes at all almost always means the discoverer is pointed at
  // the wrong place, not that the service has none.
  results.checks.push({
    name: 'route_discovery',
    ok: discovered.length > 0,
    discovered: discovered.length,
    probeable: probeable.length,
    skipped_parameterised: discovered.filter((p) => !isProbeable(p)),
    ...(discovered.length
      ? {}
      : {
          hint:
            'No app.get/router.get routes found. If this service registers ' +
            'routes another way, extend discoverGetRoutes in qa_check.js.',
        }),
  });
  if (!discovered.length) results.status = 'fail';

  for (const path of probeable) {
    try {
      const res = await getJson(`${base}${path}`);
      let ok = res.status === 200;
      const entry = { name: path, ok, status_code: res.status };
      if (ok && smoke) {
        let body = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        const lists = body === null ? [] : findEmptyLists(body);
        if (lists.length && !EMPTY_OK.has(path)) {
          ok = false;
          entry.ok = false;
          entry.empty_lists = lists;
          entry.hint =
            `GET ${path} returned empty list(s) at ${lists}. If this is ` +
            `correct steady state, add '${path}' to EMPTY_OK in qa_check.js.`;
        }
      }
      results.checks.push(entry);
      if (!ok) results.status = 'fail';
    } catch (err) {
      results.checks.push({ name: path, ok: false, error: String(err).slice(0, 200) });
      results.status = 'fail';
    }
  }

  // TODO: verify downstream dependencies (DB connectivity, Redis, etc.)
  return results;
}

function auditMode() {
  const routes = discoverGetRoutes();
  console.log(
    JSON.stringify(
      {
        root: here,
        get_routes: routes,
        probeable: routes.filter(isProbeable),
        parameterised: routes.filter((r) => !isProbeable(r)),
      },
      null,
      2,
    ),
  );
  return routes.length ? 0 : 1;
}

// Export the checker in the same shape as the Python version so tooling can
// treat them uniformly.
export const CHECKER_CLASS = { name, run };

if (import.meta.url === `file://${process.argv[1]}`) {
  if (process.argv.includes('--audit')) {
    process.exit(auditMode());
  }
  const result = await run({ smoke: process.argv.includes('--smoke') });
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.status === 'ok' ? 0 : 1);
}
