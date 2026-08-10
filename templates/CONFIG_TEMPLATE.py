"""Typed, validated configuration boundary for <name>.

**Never read `os.environ` anywhere else in this project.** Every environment
variable this project consumes is declared once, here, with a type, a default,
and a one-line description. Code imports `config` and reads typed attributes.

Why this exists
---------------
An undeclared env var fails at the point of use — three layers deep, at 3am,
as a `TypeError: unsupported operand type(s) for +: 'NoneType'`. A declared one
fails at startup, by name, with every problem listed at once.

It also makes `.env.example` correct by construction: `make env-example`
regenerates the managed block in that file straight from `FIELDS`, and
`make check-env` fails when the two drift apart. A hand-maintained
`.env.example` is always a little bit wrong.

Adding a variable
-----------------
1. Add a `Field(...)` to `FIELDS` below.
2. Run `make env-example` to refresh `.env.example`.
3. Read it as `config.my_var`.

Stdlib only, on purpose: this module is imported by every entry point and by
the QA checker, and it must never be the reason a container fails to build.
If your project already depends on pydantic, `pydantic-settings` is a fine
swap — keep `FIELDS`, `describe()` and `ConfigError` so the tooling around
this file keeps working.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent


class ConfigError(RuntimeError):
    """Raised when the environment does not satisfy the declared schema."""


# ── casts ──────────────────────────────────────────────────────────────────
# Each returns a parsed value or raises ValueError with a human-readable
# message. The message is shown to whoever has to fix the .env, so write it
# for them, not for you.


def as_str(raw: str) -> str:
    return raw


def as_int(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"expected an integer, got {raw!r}") from None


def as_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"expected a boolean (true/false), got {raw!r}")


def as_port(raw: str) -> int:
    value = as_int(raw)
    if not (1 <= value <= 65535):
        raise ValueError(f"port must be between 1 and 65535, got {value}")
    return value


def as_log_level(raw: str) -> str:
    level = raw.strip().upper()
    allowed = {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}
    if level not in allowed:
        raise ValueError(f"expected one of {sorted(allowed)}, got {raw!r}")
    return level


def as_url(raw: str) -> str:
    value = raw.strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"expected an http(s) URL, got {raw!r}")
    return value


# ── schema ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    """One environment variable, declared once."""

    name: str
    help: str
    cast: Callable[[str], Any] = as_str
    default: Any = None
    required: bool = False
    #: Never echoed by `describe()`, `make check-env`, or any error message.
    secret: bool = False
    #: Emitted commented-out in .env.example (optional integrations).
    commented: bool = False
    #: Shown in .env.example above this variable, starting a new group.
    section: str = ""


FIELDS: list[Field] = [
    Field(
        "PORT",
        "Port the service listens on inside the container.",
        cast=as_port,
        default=<PORT>,
        section="Service",
    ),
    Field(
        "HOST",
        "In-container bind address. The compose port mapping restricts host exposure to 127.0.0.1; do not set this to 127.0.0.1 in Docker or the service becomes unreachable through the mapping.",
        default="127.0.0.1",
    ),
    Field(
        "LOG_LEVEL",
        "One of debug, info, warning, error, critical.",
        cast=as_log_level,
        default="INFO",
    ),
    Field(
        "ENV",
        "Deployment environment name: development, staging, production.",
        default="development",
    ),
    Field(
        "APP_VERSION",
        "Build version, injected at image build time. Reported by /health.",
        default="0.0.0-dev",
    ),
    Field(
        "HOST_UID",
        "Numeric UID the container runs as, so bind mounts stay writable.",
        cast=as_int,
        default=<HOST_UID>,
        section="Container ownership",
    ),
    Field(
        "HOST_GID",
        "Numeric GID the container runs as.",
        cast=as_int,
        default=<HOST_GID>,
    ),
    # ── Add your own below. Anything commented=True is optional wiring. ────
    Field(
        "DATABASE_URL",
        "PostgreSQL connection string.",
        commented=True,
        secret=True,
        section="Optional integrations",
    ),
    Field(
        "REDIS_URL",
        "Redis connection string.",
        commented=True,
    ),
]


# ── loading ────────────────────────────────────────────────────────────────


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file. Real process env always wins over the file."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        raw = raw.strip()
        # Strip one layer of matching quotes, the way dotenv does.
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            raw = raw[1:-1]
        values[key.strip()] = raw
    return values


@dataclass(frozen=True)
class Config:
    """Validated configuration. Access as attributes: `config.port`."""

    values: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:
        try:
            return self.values[item.upper()]
        except KeyError:
            raise AttributeError(f"{item!r} is not a declared config field. Add a Field(...) to FIELDS in config.py rather than reading os.environ.") from None

    def public(self) -> dict[str, Any]:
        """Everything except secrets — safe for /health, logs and QA output."""
        secrets = {f.name for f in all_fields() if f.secret}
        return {k: v for k, v in self.values.items() if k not in secrets}


def _shape_fields() -> list[Field]:
    """Fields contributed by an optional `config_extra.py`.

    Some project shapes need variables the universal schema should not carry
    (upload limits for an image service, say). They declare them in
    `config_extra.py` as a module-level `FIELDS` list, and everything here —
    `load()`, `describe()`, and therefore `.env.example` and `make check-env` —
    picks them up automatically. One schema, still one source of truth.
    """
    try:
        # Imported lazily and locally: it is optional, and a missing
        # config_extra.py must be an absent feature, not an import error.
        import config_extra
    except ImportError:
        return []
    return list(getattr(config_extra, "FIELDS", []))


def all_fields(extra: list[Field] | None = None) -> list[Field]:
    """The complete schema: universal fields, shape fields, caller additions."""
    return FIELDS + _shape_fields() + list(extra or [])


def _check_defaults(fields: list[Field]) -> None:
    """Every non-None default must survive its own cast.

    A `Field(cast=as_bool, default="true")` looks right and is not: defaults
    bypass casting, so an unset variable hands the raw string to code expecting
    a bool. That surfaces far away, as a type error from a library, and the
    declaration reads as correct the whole time. Catching it here turns a
    confusing runtime failure into an immediate, named one.
    """
    for spec in fields:
        if spec.default is None or spec.cast is as_str:
            continue
        try:
            casted = spec.cast(str(spec.default))
        except ValueError as exc:
            raise ConfigError(f"{spec.name}: default {spec.default!r} fails its own cast: {exc}") from None
        if type(casted) is not type(spec.default):
            raise ConfigError(
                f"{spec.name}: default is {type(spec.default).__name__} "
                f"{spec.default!r} but the cast yields {type(casted).__name__} "
                f"{casted!r}. Declare the default as the already-typed value, "
                f"since defaults bypass casting."
            )


def load(
    env_file: Path | None = None,
    environ: dict[str, str] | None = None,
    extra: list[Field] | None = None,
) -> Config:
    """Validate the environment against FIELDS (plus any `extra`).

    Collects *every* problem before raising. Fixing config one error per
    restart is a miserable loop; one pass should tell you everything.
    """
    fields = all_fields(extra)
    _check_defaults(fields)

    source = dict(environ if environ is not None else os.environ)
    file_values = _read_env_file(env_file or PROJECT_ROOT / ".env")
    for key, value in file_values.items():
        source.setdefault(key, value)

    values: dict[str, Any] = {}
    problems: list[str] = []

    for spec in fields:
        raw = source.get(spec.name)
        if raw is None or raw == "":
            if spec.required:
                problems.append(f"  {spec.name} is required but not set — {spec.help}")
            else:
                values[spec.name] = spec.default
            continue
        try:
            values[spec.name] = spec.cast(raw)
        except ValueError as exc:
            # Never echo the offending value for a secret.
            detail = "invalid value" if spec.secret else str(exc)
            problems.append(f"  {spec.name}: {detail}")

    if problems:
        raise ConfigError("invalid configuration in .env:\n" + "\n".join(problems) + "\n\nSee .env.example for every supported variable.")

    return Config(values)


# ── .env.example generation ────────────────────────────────────────────────

# Marker text is identical across every language the kit supports, so
# scripts/check_env.py needs no per-language special-casing.
ENV_BLOCK_START = "# scaffold:env:start — generated by 'make env-example', do not edit by hand"
ENV_BLOCK_END = "# scaffold:env:end"


def describe() -> str:
    """Render the managed block of .env.example from FIELDS."""
    lines = [ENV_BLOCK_START, ""]
    for spec in all_fields():
        if spec.section:
            lines.append(f"# ── {spec.section} " + "─" * max(0, 66 - len(spec.section)))
        for chunk in _wrap(spec.help):
            lines.append(f"# {chunk}")
        if spec.required:
            lines.append("# REQUIRED.")
        default = "" if spec.default is None else spec.default
        prefix = "# " if spec.commented else ""
        lines.append(f"{prefix}{spec.name}={default}")
        lines.append("")
    lines.append(ENV_BLOCK_END)
    return "\n".join(lines)


def _wrap(text: str, width: int = 74) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if "--print-env" in args:
        print(describe())
        return 0

    if "--check" in args:
        try:
            cfg = load()
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("configuration valid")
        for key, value in sorted(cfg.public().items()):
            # Unset optionals print as blank, not "None" — the latter looks
            # like a value someone typed.
            print(f"  {key}={'' if value is None else value}")
        return 0

    print(__doc__)
    print("usage: python3 config.py [--print-env | --check]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
