"""Shape-specific configuration for <name> (shape: agent).

An agent has no port to bind — it is a graph invoked by something else. What
it does need is a model, and bounds on how far it may run before you get a
bill instead of an answer.
"""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "MODEL_PROVIDER",
        "openai (including any OpenAI-compatible endpoint via MODEL_BASE_URL) or anthropic.",
        default="openai",
        section="Model",
    ),
    Field(
        "MODEL_NAME",
        "Model identifier as the provider names it.",
        default="gpt-4o-mini",
    ),
    Field(
        "MODEL_BASE_URL",
        "OpenAI-compatible endpoint. Point this at a local vLLM or Ollama server to develop without spending anything or sending prompts off the machine.",
        default="",
    ),
    Field(
        "MODEL_API_KEY",
        "Provider key. Prefer the Vault add-on over pasting it here.",
        commented=True,
        secret=True,
    ),
    Field(
        "MODEL_TEMPERATURE",
        "0 for reproducibility. An agent whose answers move between identical runs cannot be evaluated, only sampled.",
        default="0",
    ),
    Field(
        "MODEL_TIMEOUT_S",
        "Per-request timeout in seconds.",
        default="60",
    ),
    Field(
        "RECURSION_LIMIT",
        "Maximum graph steps per run. This is the backstop between a model that will not stop asking for tools and an unbounded bill.",
        cast=as_int,
        default=25,
        section="Safety limits",
    ),
]
