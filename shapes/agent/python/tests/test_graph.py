"""Tests for <name>'s agent graph.

All offline, using the scripted model. An agent whose tests need a live model
has tests nobody runs: they cost money and fail when a provider has a bad
afternoon, so they get skipped, then deleted.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import graph as agent_graph  # noqa: E402
from models import ScriptedChatModel, scripted  # noqa: E402


def tool_call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c_{name}"}])


def invoke(model: ScriptedChatModel, prompt: str, limit: int = 25) -> dict[str, Any]:
    app = agent_graph.build_graph(model)
    return dict(app.invoke({"messages": [HumanMessage(content=prompt)]}, {"recursion_limit": limit}))


class TestGraphStructure:
    def test_compiles(self):
        assert agent_graph.build_graph(scripted(AIMessage(content="hi"))) is not None

    def test_every_node_is_reachable_from_start(self):
        drawn = agent_graph.build_graph(scripted(AIMessage(content="hi"))).get_graph()
        edges = [(e.source, e.target) for e in drawn.edges]
        reachable, frontier = set(), [t for s, t in edges if s == "__start__"]
        while frontier:
            node = frontier.pop()
            if node in reachable:
                continue
            reachable.add(node)
            frontier.extend(t for s, t in edges if s == node)
        nodes = {n for n in drawn.nodes if not n.startswith("__")}
        assert not nodes - reachable, f"unreachable: {nodes - reachable}"

    def test_binds_every_declared_tool(self):
        # A tool declared and never bound is a silent no-op: it appears in the
        # source and the model never sees it.
        model = scripted(AIMessage(content="hi"))
        agent_graph.build_graph(model)
        assert {t.name for t in model.bound_tools} == agent_graph.tool_names()


class TestTools:
    def test_every_tool_has_a_description(self):
        # The description is the prompt the model reads to decide whether to
        # call the tool. Blank means available and unusable.
        for tool in agent_graph.TOOLS:
            assert (tool.description or "").strip(), tool.name

    def test_tool_names_are_unique(self):
        names = [t.name for t in agent_graph.TOOLS]
        assert len(names) == len(set(names))

    def test_add_computes(self):
        assert agent_graph.add.invoke({"a": 2, "b": 3}) == 5

    def test_lookup_finds_a_known_key(self):
        assert agent_graph.lookup.invoke({"key": "answer"}) == "42"

    def test_lookup_reports_a_miss_rather_than_raising(self):
        # "not found" is a valid answer the model must be able to relay. An
        # exception here would become a graph crash on a normal question.
        assert agent_graph.lookup.invoke({"key": "nope"}) == "not found"


class TestRouting:
    def test_answers_directly_when_no_tool_is_requested(self):
        result = invoke(scripted(AIMessage(content="Hello.")), "say hello")
        assert result["messages"][-1].content == "Hello."

    def test_runs_a_requested_tool_then_answers(self):
        model = scripted(tool_call("add", a=2, b=3), AIMessage(content="It is 5."))
        result = invoke(model, "2+3?")
        kinds = [type(m).__name__ for m in result["messages"]]
        assert "ToolMessage" in kinds
        assert result["messages"][-1].content == "It is 5."

    def test_chains_multiple_tools(self):
        model = scripted(
            tool_call("add", a=1, b=1),
            tool_call("lookup", key="answer"),
            AIMessage(content="2 and 42."),
        )
        result = invoke(model, "both")
        called = [c["name"] for m in result["messages"] for c in (getattr(m, "tool_calls", None) or [])]
        assert called == ["add", "lookup"]


class TestTermination:
    def test_a_model_that_never_stops_is_stopped(self):
        # This is the difference between a bad model costing you one wrong
        # answer and costing you an unbounded bill.
        model = scripted(*[tool_call("add", a=1, b=1) for _ in range(50)])
        # Deliberately broad: any stop is a pass here — hanging is the failure,
        # and the exact exception type is langgraph's to change.
        with pytest.raises(Exception):  # noqa: B017
            invoke(model, "loop", limit=6)

    def test_the_scripted_model_refuses_to_improvise(self):
        # Running past the script must raise, not invent a plausible turn —
        # otherwise "my graph loops" shows up as "my test hangs".
        with pytest.raises(AssertionError):
            invoke(scripted(tool_call("add", a=1, b=1)), "one turn short")
