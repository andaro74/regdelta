"""Every key a graph node returns must be declared in RegDeltaState.

## The defect this generalises

`nodes.verdict` returned `stop_reason` and `truncated`; `graph/state.py` did
not declare either. **LangGraph drops an undeclared key silently** — no error,
no warning, nothing in the log — so both fields were discarded between the node
that produced them and the `_shape` that read them.

M05 diagnosed the symptom (`stop_reason: null` on all twenty questions of the
first live golden run) as an allowlist defect in `api._shape`, fixed that, and
recorded as open thread 9 that "no recorded run yet shows a non-null
stop_reason" — attributing the remaining silence to the fix having landed after
the last card. There were two causes and only one was fixed. The second is here.

That makes it the **fourth** time this project has lost a field between
producer and consumer: `dropped_citations`, `retrieval_ms` and `stop_reason`
were all lost in `_shape`'s allowlist, and `stop_reason` was lost a second time
one layer further in. Three of those were found by a live run costing real
Bedrock tokens. This one was found by compiling a two-node graph, offline, for
nothing — which is the argument for this file existing.

## Why the check is static

The honest alternative is to run the graph and diff the keys, and it does not
work: the nodes that matter call Bedrock, so a runtime check either costs money
or runs against stubs whose return shape is the test author's guess rather than
the node's behaviour. Reading the source is the one method that sees every key
every node can return without invoking anything.

## The instrument reports when it could not look (ADR-0013)

An AST walker that silently skips a `return` it cannot read would pass
vacuously the moment a node stops returning a dict literal — and would report
"all keys declared" about a function it never examined. So
`_returned_keys` raises on any return it cannot fully analyse, and
`test_every_node_return_is_analysable` exists to make that failure a test
failure rather than a swallowed exception inside another assertion.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
NODES = SRC / "graph" / "nodes.py"
STATE = SRC / "graph" / "state.py"


def _node_functions() -> dict[str, ast.FunctionDef]:
    """The graph's node callables, taken from graph.py's own registrations.

    DERIVED, NOT LISTED. A hardcoded list of seven names reproduces the very
    defect this file exists to catch the next time a node is added: the new
    node's keys go unchecked and every test stays green. `graph.py` is the one
    place that says what a node is, so it is the one place asked.
    """
    graph_src = (SRC / "graph" / "graph.py").read_text(encoding="utf-8")
    registered = {
        call.args[1].attr
        for call in ast.walk(ast.parse(graph_src))
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_node"
        and len(call.args) == 2
        and isinstance(call.args[1], ast.Attribute)
    }
    assert registered, "no add_node(...) registrations found in graph.py"

    tree = ast.parse(NODES.read_text(encoding="utf-8"))
    found = {fn.name: fn for fn in ast.walk(tree)
             if isinstance(fn, ast.FunctionDef) and fn.name in registered}
    missing = registered - set(found)
    assert not missing, f"graph.py registers nodes absent from nodes.py: {missing}"
    return found


class UnanalysableReturnError(Exception):
    """A `return` this walker cannot read. Never swallowed — see the docstring."""


def _returned_keys(fn: ast.FunctionDef) -> set[str]:
    """String keys of every dict this function returns.

    Raises rather than skipping. `return {}`, `return None` and a bare `return`
    are fine — they add no keys. Anything else that is not a dict literal with
    entirely constant string keys is a shape this walker cannot vouch for.
    """
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            continue
        if isinstance(value, ast.Call):
            # `return _resume_with(...)` and friends: the dict is built in the
            # callee, which is analysed on its own if it is a node, and is not
            # a node otherwise. Followed one level rather than assumed empty.
            called = value.func
            name = getattr(called, "id", None) or getattr(called, "attr", None)
            helper = _helper(name)
            if helper is None:
                raise UnanalysableReturnError(
                    f"{fn.name} returns {name}(...), which is not a function in "
                    f"nodes.py this walker can follow")
            keys |= _returned_keys(helper)
            continue
        if not isinstance(value, ast.Dict):
            raise UnanalysableReturnError(
                f"{fn.name} returns {type(value).__name__}, not a dict literal")
        for key in value.keys:
            if key is None:
                raise UnanalysableReturnError(f"{fn.name} returns a dict with **spread")
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                raise UnanalysableReturnError(
                    f"{fn.name} returns a dict with a non-literal key")
            keys.add(key.value)
    return keys


def _helper(name: str | None) -> ast.FunctionDef | None:
    if not name:
        return None
    tree = ast.parse(NODES.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == name:
            return fn
    return None


def _declared() -> set[str]:
    tree = ast.parse(STATE.read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "RegDeltaState":
            return {stmt.target.id for stmt in cls.body
                    if isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)}
    raise AssertionError("RegDeltaState not found in graph/state.py")


def _node_shaped_functions() -> set[str]:
    """Public functions in nodes.py whose first parameter is the graph state.

    The signature is what makes something a node, so the signature is what is
    asked. Private helpers (`_needs_review`, `_documents_in_play`) take the
    state too and are excluded by their leading underscore, which is the same
    convention the rest of this file's module uses.
    """
    tree = ast.parse(NODES.read_text(encoding="utf-8"))
    out = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("_"):
            continue
        args = fn.args.args
        if not args:
            continue
        annotation = args[0].annotation
        if isinstance(annotation, ast.Name) and annotation.id == "RegDeltaState":
            out.add(fn.name)
    return out


def test_every_node_shaped_function_is_registered_in_the_graph():
    """A node nobody wired is checked by nothing, and this file went quiet.

    WRITTEN BECAUSE THE MUTATION HARNESS FOUND IT.
    `milestones/M06/state_declaration_mutations.py` mutation M6 deletes
    `builder.add_node("verdict", nodes.verdict)` from graph.py — and every test
    in this file went GREEN, because the node list is derived from graph.py and
    the mutation shrank the list. The guard reported "all keys declared" about
    a set it had just stopped examining.

    That is the silent-skip shape this repo has now hit four times
    (`test_search_stack_access.py` importorskip, `_shape`'s allowlist twice,
    and `_foreign_role_imports` half-widened). Deriving the list from graph.py
    was right; deriving it from ONLY graph.py was the gap.
    """
    registered = {
        call.args[1].attr
        for call in ast.walk(ast.parse(
            (SRC / "graph" / "graph.py").read_text(encoding="utf-8")))
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_node"
        and len(call.args) == 2
        and isinstance(call.args[1], ast.Attribute)
    }
    unwired = _node_shaped_functions() - registered
    assert not unwired, (
        f"nodes.py defines {sorted(unwired)} taking RegDeltaState, but "
        f"graph.py does not register them. Either they are dead code, or the "
        f"graph lost a node — and either way every check in this file stopped "
        f"looking at them.")


@pytest.mark.parametrize("name", sorted(_node_functions()))
def test_every_node_return_is_analysable(name):
    """The walker must not report on a function it could not read."""
    _returned_keys(_node_functions()[name])


@pytest.mark.parametrize("name", sorted(_node_functions()))
def test_node_keys_are_declared_in_the_state_schema(name):
    """An undeclared key is DROPPED by LangGraph, silently.

    This is the assertion that would have caught `stop_reason` at M05 without
    a live run.
    """
    undeclared = _returned_keys(_node_functions()[name]) - _declared()
    assert not undeclared, (
        f"graph.nodes.{name} returns {sorted(undeclared)}, which "
        f"graph/state.py's RegDeltaState does not declare. LangGraph DROPS "
        f"undeclared keys with no error, so these never reach api._shape and "
        f"the response reports them as null. Declare them in RegDeltaState.")


def test_langgraph_really_does_drop_an_undeclared_key():
    """The mechanism the file above asserts, exercised rather than believed.

    Without this, `test_node_keys_are_declared_in_the_state_schema` is a style
    rule whose stated justification nobody checked — and if a future LangGraph
    starts carrying undeclared keys (or starts RAISING on them, which would be
    better), this is what says so.
    """
    from langgraph.graph import END, START, StateGraph

    from graph.state import RegDeltaState

    builder = StateGraph(RegDeltaState)
    builder.add_node("n", lambda s: {"answer": "kept",
                                     "not_in_the_schema": "dropped"})
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    out = builder.compile().invoke({"query": "q"})

    assert out.get("answer") == "kept"
    assert "not_in_the_schema" not in out, (
        "LangGraph now carries undeclared state keys. That is a BEHAVIOUR "
        "CHANGE, not a licence to stop declaring them: api._shape still reads "
        "a fixed allowlist, and the parity test still compares key sets.")


def test_the_two_fields_m05_lost_are_declared():
    """A named regression test for the specific defect, beside the general one.

    The parametrized test above would catch a re-removal — but only while
    `nodes.verdict` still returns these two. If someone deletes the field from
    both node and schema, the general test goes quiet. This one does not, and
    the reason it must not is that the fields exist to tell a truncated verdict
    apart from a model that had nothing to say (M05, ADR-0013).
    """
    assert {"stop_reason", "truncated"} <= _declared()
