#!/usr/bin/env node
// E2E check for <name> (shape: webapp, lang: node).
//
// Verifies the server is up, the brand config is readable, the locales
// endpoint lists at least one language, and the SPA index.html renders
// with the brand title in <title>.

import 'dotenv/config';

const name = '<name>';

async function fetchJson(url, timeoutMs = 5000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    const body = await res.json();
    return { ok: res.ok, status: res.status, body };
  } finally {
    clearTimeout(t);
  }
}

async function fetchText(url, timeoutMs = 5000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    const body = await res.text();
    return { ok: res.ok, status: res.status, body };
  } finally {
    clearTimeout(t);
  }
}

async function run() {
  const port = process.env.PORT || '<PORT>';
  const host = process.env.HOST || '127.0.0.1';
  const base = `http://${host}:${port}`;
  const results = { checks: [], status: 'ok' };

  // 1. /health returns ok
  try {
    const res = await fetchJson(`${base}/health`);
    const ok = res.ok && res.body.status === 'ok';
    results.checks.push({ name: 'health', ok, status_code: res.status, brand_ok: res.body.brand_ok });
    if (!ok) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'health', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
    return results; // no point continuing
  }

  // 2. /api/brand returns a valid brand config with required keys
  try {
    const res = await fetchJson(`${base}/api/brand`);
    const required = ['name', 'display_name', 'colors', 'fonts', 'logo'];
    const missing = required.filter((k) => !(k in res.body));
    const ok = res.ok && missing.length === 0;
    results.checks.push({
      name: 'brand_config',
      ok,
      missing_keys: missing,
      display_name: res.body.display_name,
    });
    if (!ok) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'brand_config', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
  }

  // 3. /api/locales returns at least one available locale
  try {
    const res = await fetchJson(`${base}/api/locales`);
    const ok = res.ok && Array.isArray(res.body.available) && res.body.available.length >= 1;
    results.checks.push({
      name: 'locales_endpoint',
      ok,
      available: res.body.available,
      default: res.body.default,
    });
    if (!ok) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'locales_endpoint', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
  }

  // 4. Default locale file is fetchable and parses as JSON with a non-empty 'app' namespace
  try {
    const res = await fetchJson(`${base}/locales/en.json`);
    const ok = res.ok && res.body.app && Object.keys(res.body.app).length > 0;
    results.checks.push({
      name: 'locales_en',
      ok,
      app_keys: res.body.app ? Object.keys(res.body.app) : [],
    });
    if (!ok) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'locales_en', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
  }

  // 5. Static index.html serves and includes the brand title
  try {
    const res = await fetchText(`${base}/`);
    // The Vite build replaces __BRAND_TITLE__ with the real title at build time
    const htmlOk = res.ok && res.body.includes('<title>') && !res.body.includes('__BRAND_TITLE__');
    results.checks.push({
      name: 'index_html',
      ok: htmlOk,
      size_bytes: res.body.length,
    });
    if (!htmlOk) results.status = 'fail';
  } catch (err) {
    results.checks.push({ name: 'index_html', ok: false, error: String(err).slice(0, 200) });
    results.status = 'fail';
  }

  return results;
}

export const CHECKER_CLASS = { name, run };

if (import.meta.url === `file://${process.argv[1]}`) {
  const result = await run();
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.status === 'ok' ? 0 : 1);
}
