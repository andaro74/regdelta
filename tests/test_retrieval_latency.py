"""Retrieval latency, measured where it is claimed and carried to the response.

WHAT THIS EXISTS FOR. SPEC/04's Tier B latency criterion is a conjunction: the
artifact records median and p95 `router.retrieve()` per tier, AND "the UI readout
is populated from a real per-query measurement through the deployed API on both
tiers". The artifact half was met at M04 Phase 4. This is the plumbing for the
other half.

WHY NOT JUST TIME THE FETCH IN THE BROWSER. Because that number is not retrieval.
A `/query` miss is 10-13 seconds end to end and is dominated by Bedrock
generation; retrieval is a few hundred milliseconds of it. A round-trip
stopwatch displayed under the words "retrieval latency" is an instrument
measuring something adjacent to the claim, which is this milestone's recurring
defect — the parity gate that would have passed comparing nothing, the allowlist
test green in a clean checkout, "end-to-end" that never touched the end, and a
tier read from `/health` instead of from what answered. The browser still times
its own round trip; the UI shows the two as two numbers with two labels.

THE SPAN IS CHOSEN, NOT INCIDENTAL. `retrieve_traced` times its whole self, so
`Resolution.elapsed_ms` is the same quantity `evals/run_demo_parity.py` puts in
the artifact (it times `router.retrieve`, which is `retrieve_traced` plus a tuple
index). Same quantity, two vantages — SPEC/04's "different instruments".
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from shared.models import Chunk, Filters  # noqa: E402


def _chunk(cid="c1"):
    return Chunk(chunk_id=cid, text="text", citation_path="21 CFR 101.65",
                 doc_type="rule", fr_doc_number="89 FR 106064",
                 cfr_title="21", cfr_part="101", pub_date="2024-12-27",
                 effective_date="2025-04-28", compliance_date="2028-02-25",
                 score=1.0)


# A sleep long enough that a wall clock cannot mistake it for zero, and short
# enough that the suite does not notice. Everything below asserts a FLOOR: a
# loaded machine can only make these slower, so there is no flake in the
# direction the assertions point.
SLOW_MS = 60


def _sleepy(ms, chunks=None):
    def fn(*a, **kw):
        time.sleep(ms / 1000)
        return chunks if chunks is not None else [_chunk()]
    return fn


@pytest.fixture
def router(monkeypatch):
    """Import the router with boto3 stubbed — it builds an SSM client at import."""
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: SimpleNamespace(
        exceptions=SimpleNamespace(ParameterNotFound=type(
            "ParameterNotFound", (Exception,), {}))))
    sys.modules.pop("retrieval.router", None)
    from retrieval import router as mod
    mod.reset_cache()
    yield mod
    sys.modules.pop("retrieval.router", None)


# ------------------------------------------------------------- in the router
def test_the_router_reports_how_long_it_took(router, monkeypatch):
    monkeypatch.setattr(router, "active_endpoint", lambda: None)
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=_sleepy(SLOW_MS)))

    _, res = router.retrieve_traced("q", Filters(), k=8)
    assert res.elapsed_ms is not None, "no measurement on the Resolution"
    assert res.elapsed_ms >= SLOW_MS, (
        f"reported {res.elapsed_ms}ms for a retrieval that slept {SLOW_MS}ms — "
        "this is not timing the retrieval")


def test_the_aoss_path_is_timed_too(router, monkeypatch):
    """Both tiers, because the readout's whole job is to let them be compared."""
    monkeypatch.setattr(router, "active_endpoint",
                        lambda: "https://x.us-west-2.aoss.amazonaws.com")
    monkeypatch.setitem(sys.modules, "retrieval.aoss_tier",
                        SimpleNamespace(retrieve_aoss=_sleepy(SLOW_MS)))

    _, res = router.retrieve_traced("q", Filters(), k=8)
    assert res.tier == "aoss"
    assert res.elapsed_ms >= SLOW_MS


def test_a_fallback_is_timed_including_the_attempt_that_failed(router, monkeypatch):
    """The fallback returns from a different place than the hot path.

    Two claims at once. The first is that this return path is timed at all —
    a stopwatch written at each `return` is one a later branch can forget, which
    is why the timing wraps the call rather than living inside it.

    The second is what the number MEANS here. It spans the whole router call, so
    a request that spent 60ms failing at AOSS before 60ms of S3 Vectors reports
    ~120ms against `tier: s3vectors`. That is deliberate and it is what the
    artifact measures too: attributing only the successful leg would report a
    fast Tier A for a request that spent most of its time failing at Tier B, and
    `fallback_reason` is on the same object to explain the number.
    """
    from retrieval import aoss_client

    monkeypatch.setattr(router, "active_endpoint",
                        lambda: "https://x.us-west-2.aoss.amazonaws.com")

    def boom(*a, **kw):
        time.sleep(SLOW_MS / 1000)
        raise aoss_client.AossError("connection refused")

    monkeypatch.setitem(sys.modules, "retrieval.aoss_tier",
                        SimpleNamespace(retrieve_aoss=boom))
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=_sleepy(SLOW_MS)))

    _, res = router.retrieve_traced("q", Filters(), k=8)
    assert res.tier == "s3vectors"
    assert res.fallback_reason and "AossError" in res.fallback_reason
    assert res.elapsed_ms >= 2 * SLOW_MS, (
        f"{res.elapsed_ms}ms covers only one leg of a two-leg call")


def test_the_untimed_contract_call_still_returns_chunks(router, monkeypatch):
    """`router.retrieve` is SPEC/02's contract and callers outside the graph use
    it. Splitting the body out from the timing wrapper must not move it."""
    monkeypatch.setattr(router, "active_endpoint", lambda: None)
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=lambda *a, **k: [_chunk("a")]))

    assert [c.chunk_id for c in router.retrieve("q", Filters(), k=8)] == ["a"]


# --------------------------------------------------------- out onto the state
def test_the_node_carries_the_measurement_out(monkeypatch):
    from graph import nodes
    from retrieval import router

    # `router.Resolution`, not `from retrieval.router import Resolution`. The
    # fixture above pops the module from sys.modules, which leaves the stale
    # object hanging off the `retrieval` package — so `from retrieval import
    # router` hands back the old module while `import retrieval.router` builds
    # a new one. Reaching through the module this test patched keeps both names
    # on the same object; the split form patched one module and let the node
    # call the other, which then went to real SSM.
    monkeypatch.setattr(
        router, "retrieve_traced",
        lambda q, f, k=8: ([_chunk()], router.Resolution("aoss", "e",
                                                         elapsed_ms=912.5)))

    out = nodes.retrieval_agent({"query": "q"})
    assert out["retrieval_ms"] == 912.5


def test_the_node_does_not_invent_a_measurement(monkeypatch):
    """A Resolution built outside `retrieve_traced` carries no timing, and the
    node must pass that absence through rather than substituting a zero — which
    would render as "0 ms", i.e. instant, in the readout."""
    from graph import nodes
    from retrieval import router

    monkeypatch.setattr(
        router, "retrieve_traced",
        lambda q, f, k=8: ([_chunk()], router.Resolution("aoss", "e")))

    out = nodes.retrieval_agent({"query": "q"})
    assert out["retrieval_ms"] is None


# ------------------------------------------------------- onto the response
def test_the_api_puts_the_measurement_on_the_response():
    """SPEC/04's readout reads this field off the deployed API. Without it the
    only number the browser can produce is its own round trip."""
    from api.api import _shape

    body = _shape({"retrieval_tier": "aoss", "retrieval_ms": 912.5}, "t1")
    assert body["retrieval_ms"] == 912.5


def test_a_run_that_never_retrieved_reports_no_latency():
    """The same rule as `tier`: a `needs_input` run never reached retrieval, and
    a number on it would be a measurement of something that did not happen."""
    from api.api import _shape

    body = _shape({"status": "needs_input"}, "t1")
    assert body["retrieval_ms"] is None
    assert body["tier"] is None


def test_the_shim_and_the_api_agree_on_the_latency_field():
    """The two `_shape` mappings are meant to be one mapping. A field on one
    side only is how `dropped_citations` came to read as "nothing was dropped"
    on every demo-parity response where nothing had been asked."""
    sys.path.insert(0, str(ROOT / "evals"))
    import serve_local

    from api.api import _shape as api_shape

    state = {"retrieval_tier": "s3vectors", "retrieval_ms": 354.1}
    assert api_shape(state, "t1")["retrieval_ms"] == \
        serve_local._shape(state, "t1")["retrieval_ms"] == 354.1
