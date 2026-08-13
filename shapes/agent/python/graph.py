"""The agent graph for <name>.

Shape: agent (LangGraph state machine with tool use).

Two things are declared here and nowhere else, so that `qa_check.py` can hold
the running graph to them:

  TOOLS  — what the agent can do
  build_graph(model) — how it decides to do it

Everything downstream reads these rather than re-deriving them, which is what
makes "the graph exposes a tool that does not exist" a check rather than a
production incident.

Why the model is a parameter
----------------------------
`build_graph` takes the model instead of constructing one. That single choice
is what lets the entire graph — routing, tool dispatch, termination — be
exercised offline with `ScriptedChatModel`, deterministically and for free.
A graph that reaches out and builds its own client can only be tested by
paying a provider and hoping they are having a good day.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# ── Tools ──────────────────────────────────────────────────────────────────
# The docstring is not documentation — it is the prompt. It is what the model
# reads to decide whether and how to call the tool, so a vague one produces a
# tool that is technically available and never used correctly. `qa_check.py`
# fails a tool with no description for exactly that reason.


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum.

    Use this for arithmetic rather than computing the answer yourself.
    """
    return a + b


@tool
def lookup(key: str) -> str:
    """Look up a value in the reference table by its exact key.

    Returns "not found" when the key is absent — that is a valid answer, not
    an error, and should be reported to the user as-is rather than guessed at.
    """
    table = {
        "capital-of-france": "Paris",
        "speed-of-light": "299792458 m/s",
        "answer": "42",
    }
    return table.get(key.strip().lower(), "not found")


TOOLS: list[Any] = [add, lookup]

SYSTEM_PROMPT = "You are a careful assistant. Use the provided tools rather than guessing. If a lookup returns 'not found', say so plainly instead of inventing an answer."


class State(TypedDict):
    """Conversation state. `add_messages` appends rather than replacing."""

    messages: Annotated[list[Any], add_messages]


def build_graph(model: BaseChatModel, tools: list[Any] | None = None) -> Any:
    """Compile the agent graph.

    The shape is the standard tool-calling loop: the model decides, tools run,
    the model sees the results and decides again, until it answers without
    requesting a tool.

    The loop is the interesting part, because it is where agents hang. A model
    that keeps asking for tools never reaches END on its own, so the compiled
    graph relies on LangGraph's recursion limit as a backstop — and
    `qa_check.py` asserts that backstop actually fires rather than trusting it.
    """
    active_tools = TOOLS if tools is None else tools
    bound = model.bind_tools(active_tools)

    def call_model(state: State) -> dict[str, Any]:
        return {"messages": [bound.invoke(state["messages"])]}

    def route(state: State) -> str:
        """Tools if the model asked for any, otherwise stop."""
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(active_tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def tool_names(tools: list[Any] | None = None) -> set[str]:
    return {t.name for t in (TOOLS if tools is None else tools)}
