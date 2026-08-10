/**
 * MCP server stub for <name>.
 *
 * Shape: mcp (Model Context Protocol server over stdio).
 *
 * An MCP server's contract is its tool surface: the names, the input schemas,
 * and what each call returns. That surface is what a client binds against, and
 * breaking it breaks every consumer silently, because nothing validates it at
 * runtime on either side.
 *
 * So the tools are declared once, as data, in `TOOLS`. `qa_check.js` reads the
 * same declaration and asserts the running server matches it — a tool added to
 * the handler map but never declared, or declared and never implemented, fails
 * the check rather than shipping.
 *
 * Transport is stdio, so **stdout belongs to the protocol**. A stray
 * console.log() corrupts the JSON-RPC stream and produces a client-side parse
 * error that points nowhere near the cause. Log to stderr — console.error —
 * always.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { load } from './config.js';

const settings = load();
const SERVER_NAME = '<name>';

/** stderr, never stdout: stdout is the JSON-RPC transport. */
const log = (...args) => console.error(`[${SERVER_NAME}]`, ...args);

// ── Tool surface ───────────────────────────────────────────────────────────
// Declared as data so the server and qa_check.js cannot disagree about it.
// `exampleArgs` is what qa_check round-trips each tool with: a call that must
// succeed against a freshly started server with no external state.

export const TOOLS = [
  {
    name: 'echo',
    description: 'Return the supplied text unchanged. Useful as a liveness probe.',
    inputSchema: {
      type: 'object',
      properties: { text: { type: 'string', description: 'Text to echo back' } },
      required: ['text'],
    },
    exampleArgs: { text: 'hello' },
  },
  {
    name: 'server_info',
    description: "Report this server's name, version and declared tool count.",
    inputSchema: { type: 'object', properties: {} },
    exampleArgs: {},
  },
];

export const HANDLERS = {
  async echo(args) {
    if (typeof args?.text !== 'string') {
      // Throw rather than returning an error string: MCP distinguishes a
      // failed call from a successful one that returned text, and a client
      // cannot tell the difference if you collapse them.
      throw new Error('`text` is required and must be a string');
    }
    return args.text;
  },
  async server_info() {
    return JSON.stringify(
      {
        server: SERVER_NAME,
        version: settings.APP_VERSION,
        tools: TOOLS.length,
        env: settings.ENV,
      },
      null,
      2,
    );
  },
};

export function buildServer() {
  const server = new Server(
    { name: SERVER_NAME, version: settings.APP_VERSION },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map(({ name, description, inputSchema }) => ({
      name,
      description,
      inputSchema,
    })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const started = process.hrtime.bigint();
    const handler = HANDLERS[request.params.name];
    if (!handler) {
      // A declared-but-unimplemented tool is a contract violation, and
      // qa_check exists to catch it before a client does.
      throw new Error(`unknown tool: ${request.params.name}`);
    }
    const text = await handler(request.params.arguments ?? {});
    const durationMs = Number(process.hrtime.bigint() - started) / 1e6;
    log(
      `[<name>-perf] phase=call_tool duration_ms=${durationMs.toFixed(1)} tool=${request.params.name}`,
    );
    return { content: [{ type: 'text', text }] };
  });

  return server;
}

async function main() {
  const server = buildServer();
  log(`starting on stdio with ${TOOLS.length} tool(s)`);
  await server.connect(new StdioServerTransport());
}

if (process.argv[1] && process.argv[1].endsWith('server.js')) {
  main().catch((error) => {
    log('fatal:', error);
    process.exit(1);
  });
}
