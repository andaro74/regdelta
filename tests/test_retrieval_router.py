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
