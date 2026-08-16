"""Router seam: which tier answers, and what the caller is told about it.

Everything here is about SPEC/02 criterion 2. The fallback from a broken hot
tier to the always-on tier is correct production behaviour and dangerous eval
behaviour — it turns "the hot tier is down" into "both tiers pass". These
tests pin that the fallback happens AND that it is reported.
"""
import sys
from types import SimpleNamespace

import pytest

from shared.models import Chunk, Filters


def mk(cid, **kw) -> Chunk:
    base = dict(text="t", citation_path="c", doc_type="final_rule",
                fr_doc_number="2024-29957", cfr_title="21", cfr_part="101",
                pub_date="2024-12-27", effective_date="2025-04-28",
                compliance_date="2028-02-25")
    base.update(kw)
    return Chunk(chunk_id=cid, **base)


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


def test_absent_parameter_routes_to_s3_vectors(router, monkeypatch):
    monkeypatch.setattr(router, "active_endpoint", lambda: None)
    called = {}

    def fake(query, filters, k):
        called["k"] = k
        return [mk("a"), mk("b")]

    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=fake))
    chunks, res = router.retrieve_traced("q", Filters(), k=8)
    assert res.tier == "s3vectors"
    assert res.fallback_reason is None
    # Fuse wide, filter, then cut: the tier is asked for k*3 candidates.
    assert called["k"] == 24
    assert [c.chunk_id for c in chunks] == ["a", "b"]


def test_present_parameter_routes_to_aoss(router, monkeypatch):
    endpoint = "https://abc123.us-west-2.aoss.amazonaws.com"
    monkeypatch.setattr(router, "active_endpoint", lambda: endpoint)
    monkeypatch.setitem(sys.modules, "retrieval.aoss_tier", SimpleNamespace(
        retrieve_aoss=lambda ep, q, f, k: [mk("a")] if ep == endpoint else []))
    chunks, res = router.retrieve_traced("q", Filters(), k=8)
    assert res.tier == "aoss"
    assert [c.chunk_id for c in chunks] == ["a"]


def test_a_broken_hot_tier_falls_back_and_says_so(router, monkeypatch):
    """The fallback must happen (an answerable query beats a 500) and must be
    reported (an unreported fallback is how a down hot tier scores green)."""
    from retrieval import aoss_client
    monkeypatch.setattr(router, "active_endpoint",
                        lambda: "https://abc123.us-west-2.aoss.amazonaws.com")

    def boom(ep, q, f, k):
        raise aoss_client.AossError("POST _msearch -> 404: index_not_found")

    monkeypatch.setitem(sys.modules, "retrieval.aoss_tier",
                        SimpleNamespace(retrieve_aoss=boom))
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=lambda q, f, k: [mk("a")]))

    chunks, res = router.retrieve_traced("q", Filters(), k=8)
    assert [c.chunk_id for c in chunks] == ["a"]
    assert res.tier == "s3vectors"
    assert "index_not_found" in res.fallback_reason
    # The endpoint is still reported, so the scorecard shows a hot tier was
    # configured and did not answer — not that none was configured.
    assert res.endpoint is not None


def test_an_unreachable_hot_tier_also_falls_back(router, monkeypatch):
    """The case the fallback comment names, and the one it used to miss.

    `aoss_client.request` originally converted only HTTPError, so URLError
    (DNS/NXDOMAIN, connection refused/reset), TimeoutError and a non-JSON 200
    escaped unwrapped and the router — which catches AossError and nothing else
    — let them propagate. SPEC/02's contract is "present + REACHABLE", and
    unreachable is the live state in the window between `make down` deleting the
    collection and the 60s endpoint cache expiring. Both role-gate reviews found
    this independently.

    Asserted at the client boundary because that is where the contract lives:
    every transport failure must arrive at the router as AossError.
    """
    import json as _json
    import socket
    import urllib.error

    from retrieval import aoss_client

    monkeypatch.setattr(router, "active_endpoint",
                        lambda: "https://abc123.us-west-2.aoss.amazonaws.com")
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=lambda q, f, k: [mk("a")]))

    for exc in (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")),
                TimeoutError("timed out"),
                ConnectionResetError(104, "reset by peer")):
        def boom(ep, q, f, k, _e=exc):
            raise aoss_client.AossError(
                f"GET chunks/_count -> unreachable: {type(_e).__name__}: {_e}")

        monkeypatch.setitem(sys.modules, "retrieval.aoss_tier",
                            SimpleNamespace(retrieve_aoss=boom))
        _, res = router.retrieve_traced("q", Filters(), k=8)
        assert res.tier == "s3vectors", f"{type(exc).__name__} did not fall back"
        assert "unreachable" in res.fallback_reason
        assert type(exc).__name__ in res.fallback_reason

    # And the conversion itself: these must not escape `request` unwrapped.
    import urllib.request
    for exc in (urllib.error.URLError("dns"), TimeoutError("t"),
                ConnectionResetError("reset")):
        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e))
        with pytest.raises(aoss_client.AossError, match="unreachable"):
            aoss_client.request("https://abc123.us-west-2.aoss.amazonaws.com",
                                "GET", "chunks/_count", None)

    class NonJson:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>gateway error</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: NonJson())
    with pytest.raises(aoss_client.AossError, match="non-JSON"):
        aoss_client.request("https://abc123.us-west-2.aoss.amazonaws.com",
                            "GET", "chunks/_count", None)
    assert _json  # the decode error is converted, not left to the caller


def test_the_router_re_applies_filters_the_tier_ignored(router, monkeypatch):
    """A tier whose pushdown silently matched everything cannot change the
    answer — only how many candidates arrive. This is what keeps criterion 3
    measuring retrieval drift rather than filter-dialect drift."""
    monkeypatch.setattr(router, "active_endpoint", lambda: None)
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier", SimpleNamespace(
        retrieve_s3v=lambda q, f, k: [
            mk("2024-29957#0000"),
            mk("2025-03118#0003", compliance_date=None),
        ]))
    f = Filters.from_dict({"compliance_date": {"gte": "2028-01-01",
                                               "lte": "2028-12-31"}})
    chunks, _ = router.retrieve_traced("q", f, k=8)
    assert [c.chunk_id for c in chunks] == ["2024-29957#0000"]


def test_truncation_happens_after_filtering(router, monkeypatch):
    """A filter that prunes most candidates must still return a full page.

    Cutting to k before filtering would silently shorten filtered results —
    recall loss with no error and no missing-chunk report.
    """
    monkeypatch.setattr(router, "active_endpoint", lambda: None)
    pool = ([mk(f"drop{i}", cfr_part="74") for i in range(20)]
            + [mk(f"keep{i}") for i in range(10)])
    monkeypatch.setitem(sys.modules, "retrieval.s3vectors_tier",
                        SimpleNamespace(retrieve_s3v=lambda q, f, k: pool))
    chunks, _ = router.retrieve_traced("q", Filters.from_dict({"cfr_part": "101"}), k=8)
    assert len(chunks) == 8
    assert all(c.chunk_id.startswith("keep") for c in chunks)


def test_reset_cache_lets_one_process_see_the_parameter_flip(router):
    """The harness runs both tiers within the 60s SSM TTL. Without a reset the
    second run answers from the first run's cached endpoint and criterion 2
    fails for a reason unrelated to either tier."""
    router._cache["endpoint"] = "https://abc123.us-west-2.aoss.amazonaws.com"
    router._cache["at"] = 10 ** 9
    router.reset_cache()
    assert router._cache["at"] == 0.0
