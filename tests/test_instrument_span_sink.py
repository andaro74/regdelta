"""The span-status sink on `graph.instrument.observed`, driven for real.

SEPARATE FILE, and that is the point. `tests/test_retrieval_load_driver.py`
replaces `graph.instrument.observed` with a stub in an `autouse` fixture — a
safety guard that must stay, because without it a unit test of the driver
reaches Bedrock and S3 Vectors. But a stub of the collaborator cannot show
what the collaborator does, and the driver's author wrote both. These
assertions drive the real wrapper, with only the datagram send replaced.

SPEC/06 defines the measured interval as the one carried on the per-node
retrieval span, and the amended disposition clause requires the report to
record the span emission status. An artifact claiming a span it did not emit
is ADR-0013's defect exactly, so the status has to come from the code that
actually sent it.
"""
import pytest


def test_the_real_wrapper_reports_the_span_status_on_both_paths(monkeypatch):
    """`graph.instrument.observed`, not the stub above.

    The stub in this module is written by the same author as the driver it
    serves, so it can only show that the driver uses the contract it was
    handed. This drives the real wrapper with the datagram send replaced, and
    asserts the contract itself: a status per call, on the success path and on
    the raising path, carrying what `send_subsegment` actually returned.
    """
    from graph import instrument
    from shared import observability

    monkeypatch.setattr(observability, "send_subsegment",
                        lambda doc, **kw: ("sent", None))
    monkeypatch.setattr(observability, "emit", lambda *a, **kw: None)

    seen = []
    ok = instrument.observed("retrieval_agent", lambda _s: {"retrieval_ms": 1.0},
                             on_span=seen.append)
    assert ok({"query": "q"}) == {"retrieval_ms": 1.0}
    assert seen == [("sent", None)]

    def boom(_s):
        raise RuntimeError("AossError: 503")

    seen.clear()
    bad = instrument.observed("retrieval_agent", boom, on_span=seen.append)
    with pytest.raises(RuntimeError):
        bad({"query": "q"})
    assert seen == [("sent", None)], (
        "a node that raises still emits its span; a sink that misses it "
        "reports every failed retrieval as having emitted nothing")

    # And the failure the sink exists to make visible reaches the report as
    # itself rather than as silence.
    monkeypatch.setattr(observability, "send_subsegment",
                        lambda doc, **kw: ("failed", "OSError: no daemon"))
    seen.clear()
    instrument.observed("retrieval_agent", lambda _s: {}, on_span=seen.append)({})
    assert seen == [("failed", "OSError: no daemon")]


def test_a_node_registered_without_a_sink_is_unchanged(monkeypatch):
    """The graph passes no sink and must not pay for this.

    `on_span` defaults to None and the request path takes one `is not None`.
    Asserted because the alternative — the graph acquiring a sink by default —
    would put a list that grows per node on the request path.
    """
    from graph import instrument
    from shared import observability

    monkeypatch.setattr(observability, "send_subsegment",
                        lambda doc, **kw: ("sent", None))
    monkeypatch.setattr(observability, "emit", lambda *a, **kw: None)

    node = instrument.observed("retrieval_agent", lambda _s: {"retrieval_ms": 2.0})
    assert node({"query": "q"}) == {"retrieval_ms": 2.0}
