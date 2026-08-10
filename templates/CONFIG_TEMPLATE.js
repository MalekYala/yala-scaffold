/**
 * Typed, validated configuration boundary for <name>.
 *
 * **Never read `process.env` anywhere else in this project.** Every
 * environment variable is declared once, here, with a type, a default and a
 * one-line description. Code imports this module and reads validated values.
 *
 * Why this exists
 * ---------------
 * An undeclared env var fails at the point of use, three layers deep, as
 * `undefined`. A declared one fails at startup, by name, with every problem
 * listed at once.
 *
 * It also makes `.env.example` correct by construction: `make env-example`
 * regenerates the managed block in that file from `FIELDS`, and
 * `make check-env` fails when the two drift apart.
 *
 * Adding a variable
 * -----------------
 *   1. Add a field to `FIELDS` below.
 *   2. Run `make env-example`.
 *   3. Read it as `config.MY_VAR`.
 *
 * Dependency-free on purpose: this module is imported by every entry point
 * and by the QA checker. If your project already depends on zod, swapping the
 * casts for a zod schema is fine — keep `FIELDS`, `describe()` and
 * `ConfigError` so the surrounding tooling keeps working.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(MODULE_DIR, '..');

export class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConfigError';
  }
}

// ── casts ──────────────────────────────────────────────────────────────────
// Each returns a parsed value or throws with a message written for whoever
// has to fix the .env — not for the developer who wrote the cast.

export const asString = (raw) => raw;

export const asInt = (raw) => {
  if (!/^-?\d+$/.test(raw.trim())) {
    throw new Error(`expected an integer, got ${JSON.stringify(raw)}`);
  }
  return Number.parseInt(raw, 10);
};

export const asBool = (raw) => {
  const lowered = raw.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(lowered)) return true;
  if (['0', 'false', 'no', 'off'].includes(lowered)) return false;
  throw new Error(`expected a boolean (true/false), got ${JSON.stringify(raw)}`);
};

export const asPort = (raw) => {
  const value = asInt(raw);
  if (value < 1 || value > 65535) {
    throw new Error(`port must be between 1 and 65535, got ${value}`);
  }
  return value;
};

export const asLogLevel = (raw) => {
  const level = raw.trim().toLowerCase();
  const allowed = ['debug', 'info', 'warn', 'warning', 'error', 'fatal'];
  if (!allowed.includes(level)) {
    throw new Error(`expected one of ${allowed.join(', ')}, got ${JSON.stringify(raw)}`);
  }
  return level;
};

export const asUrl = (raw) => {
  const value = raw.trim();
  if (!value.startsWith('http://') && !value.startsWith('https://')) {
    throw new Error(`expected an http(s) URL, got ${JSON.stringify(raw)}`);
  }
  return value;
};

// ── schema ─────────────────────────────────────────────────────────────────
//
// name       — the environment variable
// help       — one line, shown in .env.example and in error messages
// cast       — parser/validator (default: asString)
// default    — used when unset; omit together with required:true
// required   — startup fails when unset
// secret     — never echoed by describe(), check-env, or any error message
// commented  — emitted commented-out in .env.example (optional wiring)
// section    — starts a new labelled group in .env.example

export const FIELDS = [
  {
    name: 'PORT',
    help: 'Port the service listens on inside the container.',
    cast: asPort,
    default: <PORT>,
    section: 'Service',
  },
  {
    name: 'HOST',
    help:
      'In-container bind address. The compose port mapping restricts host ' +
      'exposure to 127.0.0.1; do not set this to 127.0.0.1 in Docker or the ' +
      'service becomes unreachable through the mapping.',
    default: '127.0.0.1',
  },
  {
    name: 'LOG_LEVEL',
    help: 'One of debug, info, warn, error, fatal.',
    cast: asLogLevel,
    default: 'info',
  },
  {
    name: 'ENV',
    help: 'Deployment environment name: development, staging, production.',
    default: 'development',
  },
  {
    name: 'APP_VERSION',
    help: 'Build version, injected at image build time. Reported by /health.',
    default: '0.0.0-dev',
  },
  {
    name: 'HOST_UID',
    help: 'Numeric UID the container runs as, so bind mounts stay writable.',
    cast: asInt,
    default: <HOST_UID>,
    section: 'Container ownership',
  },
  {
    name: 'HOST_GID',
    help: 'Numeric GID the container runs as.',
    cast: asInt,
    default: <HOST_GID>,
  },
  // ── Add your own below. Anything commented:true is optional wiring. ─────
  {
    name: 'DATABASE_URL',
    help: 'PostgreSQL connection string.',
    commented: true,
    secret: true,
    section: 'Optional integrations',
  },
  {
    name: 'REDIS_URL',
    help: 'Redis connection string.',
    commented: true,
  },
];

// ── loading ────────────────────────────────────────────────────────────────

/** Parse a .env file. Real process env always wins over the file. */
export function readEnvFile(filePath) {
  const values = {};
  if (!fs.existsSync(filePath)) return values;
  for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith('#') || !stripped.includes('=')) continue;
    const index = stripped.indexOf('=');
    const key = stripped.slice(0, index).trim();
    let raw = stripped.slice(index + 1).trim();
    // Strip one layer of matching quotes, the way dotenv does.
    if (raw.length >= 2 && raw[0] === raw[raw.length - 1] && (raw[0] === "'" || raw[0] === '"')) {
      raw = raw.slice(1, -1);
    }
    values[key] = raw;
  }
  return values;
}

/**
 * Validate the environment against FIELDS.
 *
 * Collects *every* problem before throwing. Fixing config one error per
 * restart is a miserable loop; one pass should tell you everything.
 */
export function load(options = {}) {
  const envFile = options.envFile || path.join(PROJECT_ROOT, '.env');
  const source = { ...readEnvFile(envFile), ...(options.environ || process.env) };

  const values = {};
  const problems = [];

  for (const spec of FIELDS) {
    const raw = source[spec.name];
    if (raw === undefined || raw === '') {
      if (spec.required) {
        problems.push(`  ${spec.name} is required but not set — ${spec.help}`);
      } else {
        values[spec.name] = spec.default;
      }
      continue;
    }
    try {
      values[spec.name] = (spec.cast || asString)(String(raw));
    } catch (error) {
      // Never echo the offending value for a secret.
      problems.push(`  ${spec.name}: ${spec.secret ? 'invalid value' : error.message}`);
    }
  }

  if (problems.length > 0) {
    throw new ConfigError(
      `invalid configuration in .env:\n${problems.join('\n')}\n\n` +
        'See .env.example for every supported variable.'
    );
  }

  /** Everything except secrets — safe for /health, logs and QA output. */
  Object.defineProperty(values, 'public', {
    enumerable: false,
    value: () => {
      const secrets = new Set(FIELDS.filter((f) => f.secret).map((f) => f.name));
      return Object.fromEntries(Object.entries(values).filter(([k]) => !secrets.has(k)));
    },
  });

  return Object.freeze(values);
}

// ── .env.example generation ────────────────────────────────────────────────

// Marker text is identical across every language the kit supports, so
// scripts/check_env.py needs no per-language special-casing.
export const ENV_BLOCK_START =
  "# scaffold:env:start — generated by 'make env-example', do not edit by hand";
export const ENV_BLOCK_END = '# scaffold:env:end';

function wrap(text, width = 74) {
  const lines = [];
  let current = '';
  for (const word of text.split(/\s+/)) {
    if (current && current.length + word.length + 1 > width) {
      lines.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) lines.push(current);
  return lines.length > 0 ? lines : [''];
}

/** Render the managed block of .env.example from FIELDS. */
export function describe() {
  const lines = [ENV_BLOCK_START, ''];
  for (const spec of FIELDS) {
    if (spec.section) {
      lines.push(`# ── ${spec.section} ${'─'.repeat(Math.max(0, 66 - spec.section.length))}`);
    }
    for (const chunk of wrap(spec.help)) lines.push(`# ${chunk}`);
    if (spec.required) lines.push('# REQUIRED.');
    const value = spec.default === undefined || spec.default === null ? '' : spec.default;
    lines.push(`${spec.commented ? '# ' : ''}${spec.name}=${value}`);
    lines.push('');
  }
  lines.push(ENV_BLOCK_END);
  return lines.join('\n');
}

// Run directly (`node src/config.js --check`) rather than imported.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.includes('--print-env')) {
    process.stdout.write(`${describe()}\n`);
    process.exit(0);
  }
  if (args.includes('--check')) {
    try {
      const cfg = load();
      process.stdout.write('configuration valid\n');
      for (const [key, value] of Object.entries(cfg.public()).sort()) {
        process.stdout.write(`  ${key}=${value}\n`);
      }
      process.exit(0);
    } catch (error) {
      process.stderr.write(`${error.message}\n`);
      process.exit(1);
    }
  }
  process.stdout.write('usage: node src/config.js [--print-env | --check]\n');
  process.exit(2);
}
