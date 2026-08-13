#!/usr/bin/env python3
"""IRC bot for <name>.

Connects to an operator-supplied IRC server, joins the project's channel,
and listens for mentions. On each mention, runs a tool-calling loop against
an LLM (OpenAI-compatible endpoint) with access to project-specific tools
defined in bot/config.yml.

The bot is self-contained. It only needs:
    - IRC_SERVER + IRC_PORT    — the operator's IRC server
    - LLM_ROUTER_URL + LLM_MODEL — an OpenAI-compatible LLM endpoint
    - Optional: CAPABILITY_BROKER_URL, VECTOR_DB_URL, MEMORY_ARCHIVE_URL, AGENT_COMMAND
      for specific tools (each tool loads conditionally based on its
      requires_env list in config.yml)

Run:
    python3 bot/bot.py

Or via docker compose (with the bot overlay):
    docker compose -f docker-compose.yml -f bot/docker-compose.bot.yml up -d <name>-bot
"""
import importlib
import json
import logging
import os
import re
import signal
import socket
import ssl
import sys
import threading
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml httpx", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install pyyaml httpx", file=sys.stderr)
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(os.environ.get("BOT_CONFIG", "bot/config.yml"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("<name>-bot")


# ── Config loading ────────────────────────────────────────────────────────


_BOOL_TRUE = {"true", "yes", "on", "1"}
_BOOL_FALSE = {"false", "no", "off", "0"}


def _coerce_scalar(s: str):
    """Parse a string into bool/int when unambiguous, otherwise return as-is.

    Why: YAML substitutions like `tls: ${IRC_TLS:-false}` produce the STRING
    "false" which Python evaluates as truthy. Without coercion, setting
    IRC_TLS=false would still make the bot try SSL — a silent, confusing
    failure mode. We only coerce unambiguous scalars so free-form strings
    are untouched.
    """
    stripped = s.strip()
    low = stripped.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    # Don't auto-parse ints — port numbers etc. are already cast explicitly
    # at the call site, and auto-parsing risks surprising behavior with
    # things like LLM model names that contain digits.
    return s


def _expand_env(value):
    """Recursively expand ${VAR} and ${VAR:-default} in config values."""
    if isinstance(value, str):
        def repl(m):
            expr = m.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var, default)
            return os.environ.get(expr, "")
        expanded = re.sub(r"\$\{([^}]+)\}", repl, value)
        # If the ENTIRE value was one substitution (no surrounding text),
        # coerce unambiguous bool-like strings so `if cfg.get("tls"):` works
        # the way the operator expects.
        if expanded != value and re.fullmatch(r"\$\{[^}]+\}", value):
            return _coerce_scalar(expanded)
        return expanded
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error(f"bot config not found at {CONFIG_PATH}")
        sys.exit(1)
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    return _expand_env(raw)


# ── Tool loader ───────────────────────────────────────────────────────────


def load_tools(config: dict) -> dict:
    """Import each tool module declared in config.yml.

    A tool module must expose:
        NAME          — human-readable tool name
        DESCRIPTION   — string describing what the tool does
        call(query: str, ctx: dict) -> str  — the actual call

    Tools with `requires_env` in config that aren't satisfied are skipped
    with a warning. Tools with `requires_path` are skipped when that path is
    absent — which is how add-on-dependent tools stay honest: advertising
    `local_rag` to the model when the RAG add-on was never installed just
    produces a confusing failure mid-conversation.
    """
    tools = {}
    project_root = Path.cwd()
    sys.path.insert(0, str(project_root / "bot"))

    for entry in config.get("tools", []):
        name = entry["name"]
        requires = entry.get("requires_env") or []
        missing = [e for e in requires if not os.environ.get(e)]
        if missing:
            log.warning(f"tool {name} skipped — missing env: {missing}")
            continue
        needed_paths = entry.get("requires_path") or []
        absent = [p for p in needed_paths if not (project_root / p).exists()]
        if absent:
            log.warning(
                f"tool {name} skipped — missing {absent} "
                f"(that add-on was not installed; re-scaffold with the matching --with-* flag)"
            )
            continue
        try:
            mod = importlib.import_module(entry["module"])
        except Exception as exc:
            log.warning(f"tool {name} failed to import ({entry['module']}): {exc}")
            continue
        if not hasattr(mod, "call"):
            log.warning(f"tool {name} has no `call` function — skipping")
            continue
        tools[name] = {
            "module": mod,
            "description": entry.get("description") or getattr(mod, "DESCRIPTION", ""),
        }
        log.info(f"tool loaded: {name}")
    return tools


# ── Project context ───────────────────────────────────────────────────────


def load_project_context() -> str:
    """Load a compact summary of the project for the system prompt.
    Small enough to fit in a prompt; for deeper info the bot uses local_rag.
    """
    parts = []
    for rel in ("STRATEGY.md", "README.md", "AGENTS.md", "CHANGELOG.md"):
        p = Path(rel)
        if p.exists():
            text = p.read_text()[:2000]
            parts.append(f"## {rel}\n\n{text}")
    # Current KPIs if available
    metrics = Path("results/metrics.json")
    if metrics.exists():
        try:
            parts.append("## Current metrics\n\n```json\n" + metrics.read_text() + "\n```")
        except Exception:
            pass
    return "\n\n---\n\n".join(parts) if parts else "(no project context files found)"


# ── LLM tool-calling loop ─────────────────────────────────────────────────


def llm_chat(llm_cfg: dict, messages: list[dict], tools_spec: list[dict]) -> dict:
    """Call the LLM with tool definitions. Returns the raw choice message.
    Uses the OpenAI chat-completions tool-calling format, which most
    OpenAI-compatible servers support.
    """
    headers = {"Content-Type": "application/json"}
    if llm_cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {llm_cfg['api_key']}"

    payload = {
        "model": llm_cfg["model"],
        "messages": messages,
        "temperature": llm_cfg.get("temperature", 0.2),
        "max_tokens": llm_cfg.get("max_tokens", 2048),
    }
    if tools_spec:
        payload["tools"] = tools_spec
        payload["tool_choice"] = "auto"

    _t = time.monotonic()
    r = httpx.post(
        f"{llm_cfg['url'].rstrip('/')}/chat/completions",
        json=payload,
        headers=headers,
        timeout=llm_cfg.get("timeout_s", 60),
    )
    r.raise_for_status()
    data = r.json()
    elapsed = int((time.monotonic() - _t) * 1000)
    log.info(f"[<name>-perf] phase=llm_chat duration_ms={elapsed} tool_call={bool(data['choices'][0]['message'].get('tool_calls'))}")
    return data["choices"][0]["message"]


def tool_loop(query: str, config: dict, tools: dict, project_context: str) -> str:
    """Run the tool-calling loop until the LLM produces a final answer."""
    llm_cfg = config["llm"]
    identity = config.get("identity", {})

    system_prompt = (
        f"{identity.get('role', '')}\n\n"
        f"You are {identity.get('name', 'a project bot')} in the IRC channel "
        f"{config['irc']['channel']}. Your answers are posted to IRC so keep "
        f"them under 400 characters when possible. Use the tools below to "
        f"look up project-specific information before answering. Never "
        f"invent facts — if you don't know, say so and suggest which tool "
        f"or channel might help.\n\n"
        f"## Project context\n\n{project_context}"
    )

    tools_spec = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "The query or task for this tool"}},
                    "required": ["query"],
                },
            },
        }
        for name, info in tools.items()
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    max_iter = llm_cfg.get("max_iterations", 6)
    for iteration in range(max_iter):
        try:
            msg = llm_chat(llm_cfg, messages, tools_spec)
        except httpx.HTTPStatusError as exc:
            # LLM backend returned 4xx/5xx. Common on rag-ollama cold
            # loads (llama.cpp `decode: cannot decode batches` bug) and
            # on context-window overruns. Return a surfaced error so
            # the user gets told "the backend is unhappy", instead of
            # the bot pretending to still be thinking.
            status = exc.response.status_code if exc.response else "?"
            log.error(f"LLM call failed: HTTP {status} from {llm_cfg.get('url')}")
            return f"(LLM error: backend returned HTTP {status} — try again in a moment)"
        except httpx.TimeoutException as exc:
            log.error(f"LLM call timed out: {exc}")
            return f"(LLM error: backend timed out after {llm_cfg.get('timeout_s', 60)}s)"
        except Exception as exc:
            log.error(f"LLM call failed: {exc}")
            return f"(LLM error: {exc})"

        # Append the assistant turn to message history
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg.get("tool_calls")})

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return msg.get("content") or "(no response)"

        # Execute each tool call
        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_query = args.get("query", "")

            if name not in tools:
                result = f"(tool {name} not available)"
            else:
                try:
                    _t = time.monotonic()
                    result = tools[name]["module"].call(tool_query, ctx={"project": config["project"], "config": config})
                    elapsed = int((time.monotonic() - _t) * 1000)
                    log.info(f"[<name>-perf] phase=tool_{name} duration_ms={elapsed}")
                except Exception as exc:
                    result = f"(tool {name} error: {exc})"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": name,
                "content": str(result)[:4000],
            })

    return "(hit iteration limit — try a more specific question)"


# ── Minimal IRC client ────────────────────────────────────────────────────


class IRCClient:
    """Minimal IRC client using raw sockets. Handles PING, JOIN, PRIVMSG.
    Not RFC-complete but enough for this bot's needs.
    """

    def __init__(self, config: dict):
        self.config = config["irc"]
        self.nick = self.config["nick"]
        self.channel = self.config["channel"]
        self.sock: socket.socket | None = None
        self._buf = ""
        self._running = False
        self._handlers: list = []
        # Serialize all socket writes so background tool threads (e.g.
        # plan_to_pr_workflow's completion-polling thread) can call say_to /
        # join_channel without interleaving bytes with the main recv loop.
        self._send_lock = threading.Lock()

    def connect(self):
        server = self.config["server"]
        port = int(self.config["port"])
        if not server:
            raise RuntimeError("IRC_SERVER not set — bot cannot connect")

        log.info(f"connecting to {server}:{port} as {self.nick}")
        raw = socket.create_connection((server, port), timeout=30)
        if self.config.get("tls"):
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=server)
        self.sock = raw

        self._send(f"NICK {self.nick}")
        self._send(f"USER {self.nick} 0 * :{self.config.get('realname', self.nick)}")

        # Wait for welcome (001) before joining
        for _ in range(50):
            line = self._recv_line()
            if not line:
                continue
            if " 001 " in line:
                break
            if line.startswith("PING "):
                self._send("PONG " + line[5:])

        if self.config.get("password"):
            self._send(f"PRIVMSG NickServ :IDENTIFY {self.config['password']}")
            time.sleep(1)

        self._send(f"JOIN {self.channel}")
        log.info(f"joined {self.channel}")
        self._send_msg(self.channel, f"{self.nick} online — ask me anything about this project")

    def _send(self, line: str):
        if self.sock is None:
            return
        with self._send_lock:
            try:
                self.sock.sendall((line + "\r\n").encode("utf-8", errors="replace"))
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                # Socket died (irc-server dropped us for a PING timeout
                # during a long tool call, we ran out of buffer, the
                # network flickered, etc.). Don't propagate — logging
                # here keeps the recv loop alive and docker's
                # restart-unless-stopped will get us back if the death
                # is permanent. Return silently so the caller (handler,
                # watcher thread) doesn't crash on a transient glitch.
                log.warning(f"IRC send failed ({type(exc).__name__}): {exc}")
                return
        log.debug(f"> {line}")

    def join_channel(self, channel: str):
        """JOIN an additional channel. Used by tools that create per-run
        ephemeral channels (e.g. plan_to_pr_workflow → #agent-run-<id>)."""
        if not channel.startswith("#"):
            channel = "#" + channel
        self._send(f"JOIN {channel}")

    def invite(self, nick: str, channel: str):
        """Send IRC INVITE so the target user gets a highlighted prompt
        from their client. On irc-server we also need to be a channel op,
        which we get automatically by being the first joiner."""
        if not channel.startswith("#"):
            channel = "#" + channel
        self._send(f"INVITE {nick} {channel}")

    def _send_msg(self, target: str, text: str):
        # IRC lines cap around 400 chars — split long messages
        for chunk in _split_for_irc(text):
            self._send(f"PRIVMSG {target} :{chunk}")

    def _recv_line(self) -> str | None:
        if self.sock is None:
            return None
        while "\r\n" not in self._buf:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not data:
                return None
            self._buf += data.decode("utf-8", errors="replace")
        line, self._buf = self._buf.split("\r\n", 1)
        return line

    def on_privmsg(self, handler):
        self._handlers.append(handler)

    def say(self, text: str):
        self._send_msg(self.channel, text)

    def say_to(self, target: str, text: str):
        self._send_msg(target, text)

    def run(self):
        self._running = True
        self.sock.settimeout(1.0)
        # Heartbeat file tells the Docker healthcheck we're alive.
        # Touch it at startup and then every loop iteration — the healthcheck
        # in Dockerfile allows up to 120s of staleness.
        heartbeat_path = Path("/app/data/bot-heartbeat")
        try:
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_path.touch()
        except Exception as exc:
            log.warning(f"could not write heartbeat file: {exc}")
        last_heartbeat = time.time()

        while self._running:
            # Refresh heartbeat every 15s so the healthcheck sees a fresh mtime
            now = time.time()
            if now - last_heartbeat >= 15:
                try:
                    heartbeat_path.touch()
                except Exception:
                    pass
                last_heartbeat = now

            line = self._recv_line()
            if line is None:
                continue
            log.debug(f"< {line}")

            if line.startswith("PING "):
                self._send("PONG " + line[5:])
                continue

            # :nick!user@host PRIVMSG #channel :text
            m = re.match(r"^:([^!]+)![^ ]+ PRIVMSG ([^ ]+) :(.*)$", line)
            if m:
                sender, target, text = m.group(1), m.group(2), m.group(3)
                # Run each handler in a daemon thread so the recv loop
                # keeps pumping — PINGs get answered even while a tool
                # call is blocked on a slow LLM backend. Without this,
                # any tool_loop that takes >60s causes irc-server to drop
                # the connection on PING timeout, and the bot's next
                # _send hits BrokenPipeError. Handler exceptions are
                # caught inside the worker so they never crash the
                # recv loop.
                for handler in self._handlers:
                    def _worker(h=handler, s=sender, t=target, x=text):
                        try:
                            h(sender=s, target=t, text=x)
                        except Exception as exc:
                            log.exception(f"handler error: {exc}")
                    threading.Thread(
                        target=_worker,
                        daemon=True,
                        name=f"handler-{sender}",
                    ).start()

    def quit(self, message: str = "bye"):
        self._running = False
        try:
            if self.sock:
                self._send(f"QUIT :{message}")
                self.sock.close()
        except Exception:
            pass
        self.sock = None


def _split_for_irc(text: str, max_len: int = 400) -> list[str]:
    """Split text into IRC-safe chunks preserving word boundaries."""
    text = text.replace("\n", " · ").strip()
    if len(text) <= max_len:
        return [text] if text else [""]
    out, current = [], ""
    for word in text.split(" "):
        if len(current) + len(word) + 1 > max_len:
            if current:
                out.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        out.append(current)
    return out


# ── File watcher ──────────────────────────────────────────────────────────


def _watch_loop(config: dict, say_fn):
    """Poll the `watch` entries in config and announce changes.
    Simple poll-based; no inotify dep. Runs in a background thread.
    """
    watch_entries = config.get("watch") or []
    last_state: dict[str, float] = {}
    while True:
        try:
            for entry in watch_entries:
                path = Path(entry["path"])
                if path.is_file():
                    mtime = path.stat().st_mtime
                    if last_state.get(str(path)) != mtime:
                        last_state[str(path)] = mtime
                        if mtime - (last_state.get(f"_announced_{path}") or 0) > entry.get("debounce_s", 10):
                            if entry.get("type") == "json":
                                try:
                                    data = json.loads(path.read_text())
                                    summary = _summarize_json(data)
                                    say_fn(f"[update] {path}: {summary}")
                                except Exception:
                                    pass
                            last_state[f"_announced_{path}"] = mtime
        except Exception as exc:
            log.warning(f"watch loop error: {exc}")
        time.sleep(5)


def _summarize_json(data: dict) -> str:
    """Produce a compact one-line summary of a JSON dict for IRC."""
    if not isinstance(data, dict):
        return str(data)[:200]
    keys = list(data.keys())[:5]
    parts = []
    for k in keys:
        v = data[k]
        if isinstance(v, (int, float, str, bool)):
            parts.append(f"{k}={v}")
        elif isinstance(v, list):
            parts.append(f"{k}=[{len(v)} items]")
        elif isinstance(v, dict):
            parts.append(f"{k}={{{len(v)} keys}}")
    return " ".join(parts)[:300]


# ── Main ──────────────────────────────────────────────────────────────────


def check() -> int:
    """Report what is configured, without connecting to anything.

    A bot you can only test by pointing it at a live IRC server and an LLM is
    a bot nobody tests. This answers "will it work, and if not what is
    missing?" in a second, offline, and is what `make bot-check` runs.
    """
    config = load_config()
    tools = load_tools(config)

    declared = [entry["name"] for entry in config.get("tools", [])]
    loaded = sorted(tools)
    skipped = sorted(set(declared) - set(loaded))

    print(f"project      : {config['project']}")
    print(f"tools loaded : {len(loaded)}/{len(declared)}  {loaded}")
    if skipped:
        print(f"tools skipped: {skipped}")
        print("               (see the warnings above for what each one needs)")

    problems = []
    if not os.environ.get("IRC_SERVER"):
        problems.append("IRC_SERVER is not set — the bot cannot connect to anything")
    if not os.environ.get("LLM_ROUTER_URL"):
        problems.append(
            "LLM_ROUTER_URL is not set — the bot can connect but cannot think; "
            "any OpenAI-compatible endpoint works, including a local one"
        )
    if not loaded:
        problems.append("no tools loaded — the bot would have nothing to do")

    print()
    if problems:
        for problem in problems:
            print(f"NOT READY: {problem}")
        print("\nFix these in .env, then run `make bot`.")
        return 1
    print("READY — `make bot` should start cleanly.")
    return 0


def main():
    if "--check" in sys.argv:
        return check()
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "usage: bot.py [--check]\n\n"
            "  --check   report configured tools and settings, then exit\n"
            "            (no IRC connection, no LLM calls)\n\n"
            "With no arguments the bot connects to IRC and runs its tool loop.\n"
            "It needs IRC_SERVER and LLM_ROUTER_URL in .env — see bot/README.md."
        )
        return 0

    config = load_config()
    tools = load_tools(config)
    project_context = load_project_context()

    log.info(f"bot starting — project={config['project']} tools={list(tools.keys())}")

    client = IRCClient(config)
    try:
        client.connect()
    except Exception as exc:
        log.error(f"IRC connect failed: {exc}")
        sys.exit(1)

    # Ignore replayed channel history for a few seconds after connect.
    # irc-server sends CHATHISTORY on JOIN — without this guard, every
    # restart re-dispatches expensive workflows from old mentions.
    _connect_time = time.time()
    _REPLAY_GRACE_S = 5

    def handle(sender, target, text):
        if time.time() - _connect_time < _REPLAY_GRACE_S:
            log.debug(f"ignoring replayed message from {sender} (within {_REPLAY_GRACE_S}s grace)")
            return
        # Only respond when mentioned or in the project channel
        nick = config["irc"]["nick"]
        mention = f"{nick}:" in text or f"{nick}," in text or f"@{nick}" in text
        if target == nick:
            # Direct PM — always respond
            query = text
            reply_target = sender
        elif target == config["irc"]["channel"] and mention:
            # Channel mention
            query = re.sub(rf"@?{re.escape(nick)}[:, ]*", "", text, count=1).strip()
            reply_target = target
        else:
            return

        log.info(f"[<name>-bot] query from {sender}: {query}")
        try:
            answer = tool_loop(query, config, tools, project_context)
        except Exception as exc:
            log.exception(f"tool_loop error: {exc}")
            answer = f"(internal error: {exc})"
        client.say_to(reply_target, answer)

    client.on_privmsg(handle)

    # Background watch thread
    watch_thread = threading.Thread(
        target=_watch_loop,
        args=(config, lambda t: client.say(t)),
        daemon=True,
    )
    watch_thread.start()

    # Graceful shutdown
    def shutdown(*_):
        log.info("shutting down")
        client.quit(config["irc"].get("quit_message", "bye"))
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        client.run()
    except Exception as exc:
        log.exception(f"client run error: {exc}")
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main() or 0)
