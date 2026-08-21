"""The span policy covers every state key, and never logs the asker's data.

`graph/instrument.py` decides what a node's span carries. Two things can go
wrong with such a table and only one of them is visible by reading it:

1. **It falls behind the schema.** A field is added to `RegDeltaState`, nobody
   adds a disposition, and the span reports nothing about it — which reads
   exactly like "there was nothing to report". Four fields have been lost that
   way in this repo already.
2. **It carries too much.** `query`, `company_profile`, `applicability` and
   `answer` are the asker's question, the asker's business and the analysis
   written for them. `shared/config.py` forces three LangSmith variables off as
   a data-egress control naming exactly that payload; writing it to a log group
   instead would reverse that decision by implication rather than by ruling.

These tests are the two halves.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from graph import instrument
from graph.state import RegDeltaState

SRC = Path(__file__).parent.parent / "src"

#: Values planted in a fake node's return so a leak is unmistakable in the
#: emitted document. Chosen not to occur anywhere else in the repo.
SECRET_MARKER = "ZZQ-secret-payload-must-never-be-logged-ZZQ"


def _declared() -> set[str]:
    return set(RegDeltaState.__annotations__)


def test_every_state_key_has_a_disposition():
    """A new field must be given one, even if that disposition is SECRET."""
    missing = _declared() - set(instrument.DISPOSITION)
    assert not missing, (
        f"graph/state.py declares {sorted(missing)} with no entry in "
        f"instrument.DISPOSITION. Add one — SECRET with a reason is a valid "
        f"answer, silence is not: an undisposed field reads on the dashboard "
        f"as 'nothing to report' when the truth is 'nobody asked'.")


def test_no_disposition_describes_a_field_that_no_longer_exists():
    """The other direction: a stale entry claims coverage of nothing."""
    extra = set(instrument.DISPOSITION) - _declared()
    assert not extra, (
        f"instrument.DISPOSITION names {sorted(extra)}, which RegDeltaState "
        f"does not declare. A disposition for a dead field is a claim of "
        f"coverage nobody can spend.")


def test_every_secret_carries_a_reason():
    for key, (kind, extra) in instrument.DISPOSITION.items():
        if kind is instrument.SECRET:
            assert isinstance(extra, str) and len(extra) > 20, (
                f"{key} is SECRET with no stated reason. The reason is the "
                f"whole record of the decision.")


def test_usage_keys_are_complete():
    """A model-calling node whose usage key is missing costs $0 on the dashboard.

    DERIVED FROM THE SCHEMA rather than trusted: `instrument.USAGE_KEYS` is a
    hand-written tuple, and the failure it can have is invisible — the cost
    metric simply never fires for that node and every total stays plausible.
    """
    from_schema = {k for k in _declared() if k.endswith("_usage")}
    assert from_schema == set(instrument.USAGE_KEYS), (
        f"RegDeltaState declares {sorted(from_schema)} but "
        f"instrument.USAGE_KEYS is {sorted(instrument.USAGE_KEYS)}. A usage "
        f"key missing here emits no BedrockCostUsd and no token counts, and "
        f"the dashboard under-reports spend with no gap visible.")


# --------------------------------------------------------------- emission
def _capture(result: dict) -> list[dict]:
    """Run a fake node returning `result`; collect every emitted document."""
    emitted: list[dict] = []

    def fake_emit(metrics, dimensions, properties=None, **kw):
        doc = {"metrics": metrics, "dimensions": dimensions,
               "properties": properties or {}}
        emitted.append(doc)
        return doc

    real_emit = instrument.observability.emit
    instrument.observability.emit = fake_emit
    try:
        instrument.observed("probe", lambda _s: result)({})
    finally:
        instrument.observability.emit = real_emit
    return emitted


def _all_text(docs: list[dict]) -> str:
    return json.dumps(docs, default=str)


@pytest.mark.parametrize("key", sorted(
    k for k, (kind, _) in instrument.DISPOSITION.items()
    if kind is instrument.SECRET))
def test_a_secret_field_never_reaches_an_emitted_document(key):
    """Planted, run, and searched for — not reasoned about.

    The value is a marker string. If ANY emitted document contains it, in a
    metric, a dimension or a property, the field leaked.
    """
    docs = _capture({key: SECRET_MARKER})
    assert SECRET_MARKER not in _all_text(docs), (
        f"{key} is SECRET and its value appeared in an emitted document. "
        f"That document goes to a CloudWatch log group.")


def test_a_secret_dict_field_never_reaches_an_emitted_document():
    """`company_profile` and `applicability` are dicts, not strings.

    A str-only check would pass them while the dict's CONTENTS leaked, which is
    the shape that actually carries the products and claims.
    """
    docs = _capture({"company_profile": {"products": [SECRET_MARKER]},
                     "applicability": {"claims": [SECRET_MARKER]}})
    assert SECRET_MARKER not in _all_text(docs)


def test_an_undisposed_key_is_named_without_its_value():
    """The unknown-key branch says something is unobserved, and nothing more.

    Reached only if the coverage tests above are failing, but it must be safe
    when it is reached: naming the key is a gap report, printing the value
    would be the leak this file exists to prevent, arriving by the back door.
    """
    docs = _capture({"a_field_nobody_disposed": SECRET_MARKER})
    text = _all_text(docs)
    assert "undisposed__a_field_nobody_disposed" in text
    assert SECRET_MARKER not in text


def test_the_tier_is_a_dimension_on_retrieval_latency():
    """SPEC/06's bar is p95 of this interval PER TIER, so it must slice."""
    docs = _capture({"retrieval_ms": 354.1, "retrieval_tier": "s3vectors"})
    latency = [d for d in docs if "RetrievalLatency" in d["metrics"]]
    assert latency, "RetrievalLatency was not emitted"
    assert latency[0]["dimensions"] == {"retrieval_tier": "s3vectors"}
    assert latency[0]["metrics"]["RetrievalLatency"] == (354.1, "Milliseconds")


def test_an_undimensionable_metric_says_so_rather_than_lying():
    """`retrieval_ms` with no tier must not be filed under some default tier.

    A retrieval latency attributed to a tier that did not produce it is the
    exact substitution `router.Resolution` and `api._shape`'s `tier` field
    exist to prevent, arriving through the metrics side.
    """
    docs = _capture({"retrieval_ms": 354.1})
    assert not any(d["dimensions"].get("retrieval_tier") for d in docs)
    assert "RetrievalLatency__undimensioned" in _all_text(docs)


def test_cost_is_emitted_per_model_and_an_unpriced_model_is_not_free():
    from shared import config

    priced = _capture({"verdict_usage": {
        "model": config.MODEL_VERDICT, "input": 5246, "output": 636,
        "cache_read": None, "cache_write": None}})
    cost = [d for d in priced if "BedrockCostUsd" in d["metrics"]]
    assert cost, "no BedrockCostUsd emitted for a priced model"
    assert cost[0]["dimensions"] == {"model": config.MODEL_VERDICT}
    # 5246 * 5.50e-6 + 636 * 27.50e-6
    assert cost[0]["metrics"]["BedrockCostUsd"][0] == pytest.approx(
        5246 * 5.50e-6 + 636 * 27.50e-6, rel=1e-9)

    unpriced = _capture({"verdict_usage": {
        "model": "us.anthropic.claude-not-in-the-table", "input": 100,
        "output": 10}})
    text = _all_text(unpriced)
    assert "rate_missing" in text, (
        "an unpriced model emitted no rate_missing marker; every total "
        "downstream would stay plausible and be wrong in our favour")
    assert not any("BedrockCostUsd" in d["metrics"] for d in unpriced)


def test_a_node_that_raises_still_emits_its_span():
    """The node you most want a span for is the one that failed."""
    emitted: list[dict] = []
    real_emit = instrument.observability.emit
    instrument.observability.emit = lambda m, d, p=None, **kw: emitted.append(
        {"metrics": m, "dimensions": d, "properties": p or {}})
    try:
        with pytest.raises(ValueError):
            instrument.observed("boom", _raiser)({})
    finally:
        instrument.observability.emit = real_emit

    assert emitted, "a raising node emitted nothing"
    assert "NodeLatency" in emitted[0]["metrics"]
    assert "error" in emitted[0]["properties"]


def _raiser(_state):
    raise ValueError("node failed")


def test_the_wrapper_keeps_the_original_reachable():
    """`loadtest/retrieval_load.py` calls the real node; the tests do too."""
    from graph import nodes

    wrapped = instrument.observed("retrieval_agent", nodes.retrieval_agent)
    assert wrapped.__wrapped__ is nodes.retrieval_agent
    assert wrapped.__doc__ == nodes.retrieval_agent.__doc__


def test_no_high_cardinality_key_is_ever_a_dimension():
    """One CloudWatch metric per request is the classic EMF cost incident.

    Invisible until the bill arrives, because the dashboard looks correct.
    """
    forbidden = {"trace_id", "thread_id", "query", "answer", "review_reason"}
    docs = _capture({"retrieval_ms": 12.0, "retrieval_tier": "aoss",
                     "status": "ok", "intent": "timeline"})
    for doc in docs:
        assert not (forbidden & set(doc["dimensions"])), doc["dimensions"]


def test_instrument_imports_nothing_from_the_answer_path():
    """Instrumentation must not be able to change what the graph decides.

    `graph/nodes.py` is where answers are made. If this file imported it, a
    future edit could route on a metric — and SPEC/03's exit criteria would
    then depend on the observability layer.
    """
    tree = ast.parse((SRC / "graph" / "instrument.py").read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in getattr(node, "names", [None])
    } | {
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert not any("nodes" in str(name) for name in imported if name), imported
