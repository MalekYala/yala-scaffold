"""Chat models for <name> — one real, one scripted.

The scripted one is the reason this project's tests and QA checks run with no
API key, no network and no cost. An agent whose only checkable behaviour needs
a live model has, in practice, no checkable behaviour: nobody runs the suite on
every commit if it bills per run and fails when a provider has a bad afternoon.

`ScriptedChatModel` replays a fixed list of AI turns, so a whole
tool-calling conversation becomes a deterministic fixture. It is not a
substitute for evaluating against a real model — see `evaluate.py` — but it is
what makes graph structure, routing, tool wiring and termination testable at
all.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import SecretStr


class ScriptedChatModel(BaseChatModel):
    """Replay a fixed sequence of AI turns. Deterministic, offline, free.

    Running past the end of the script raises rather than returning something
    plausible. A double that keeps answering forever turns "my graph loops"
    into "my test hangs", and the whole point here is to make that failure
    loud and fast.
    """

    responses: list[AIMessage] = []  # noqa: RUF012 — pydantic field, not a class default
    calls: int = 0
    bound_tools: list[Any] = []  # noqa: RUF012 — pydantic field, not a class default

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, Any]:
        # Recorded rather than ignored so a test can assert the graph actually
        # binds the tools it claims to expose.
        self.bound_tools = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.calls >= len(self.responses):
            raise AssertionError(f"scripted model exhausted after {self.calls} turn(s): the graph asked for more than the scenario scripted, which usually means it is looping")
        message = self.responses[self.calls]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def scripted(*responses: AIMessage) -> ScriptedChatModel:
    """Convenience builder: scripted(turn1, turn2, ...)."""
    return ScriptedChatModel(responses=list(responses))


def real_model(settings: Any) -> BaseChatModel:
    """The production model.

    Imported lazily so that nothing which only needs the scripted model pays
    for a provider SDK import — or fails because a key is absent.
    """
    provider = settings.model_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not os.environ.get("OPENAI_API_KEY") and not settings.model_api_key:
            raise RuntimeError(
                "MODEL_PROVIDER=openai needs an API key. Set MODEL_API_KEY in .env (or use the Vault add-on), or switch MODEL_PROVIDER to a local OpenAI-compatible endpoint via MODEL_BASE_URL."
            )
        return ChatOpenAI(
            model=settings.model_name,
            temperature=float(settings.model_temperature),
            base_url=settings.model_base_url or None,
            api_key=SecretStr(settings.model_api_key or os.environ.get("OPENAI_API_KEY") or ""),
            timeout=float(settings.model_timeout_s),
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # langchain_anthropic ships no type information, so the constructor is
        # Any; naming the type here keeps the declared return honest.
        anthropic: BaseChatModel = ChatAnthropic(
            model=settings.model_name,
            temperature=float(settings.model_temperature),
            timeout=float(settings.model_timeout_s),
        )
        return anthropic

    raise ValueError(f"unsupported MODEL_PROVIDER={provider!r}. Supported: openai (including any OpenAI-compatible endpoint via MODEL_BASE_URL), anthropic.")
