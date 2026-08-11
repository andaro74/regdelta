"""Tier B's lexical lane, off by default (ADR-0009 Ruling 3, resolved as (a)).

`config.RERANK` was a declared flag referenced nowhere in the code until M02
noticed, so a flag this milestone adds gets exercised rather than asserted. What
matters here is not that a boolean exists but that it changes what goes over the
wire and what comes back:

1. Off, the `_msearch` carries ONE query and the relevance lane is the raw kNN
   list. Not `rrf([knn])` — that re-scores by rank and would differ from Tier A's
   shape for no reason, and (a)'s whole content is that the two tiers now run the
   same algorithm.
2. On, it carries TWO and they fuse. The lane is reversible on a named condition
   (a probe BM25 wins), so the path back has to keep working.

None of these reach AWS. `aoss_client.request` is stubbed and the recorded ndjson
is parsed back, so the assertions are about the request actually sent.
"""
import json

import pytest

from retrieval import aoss_tier
from shared.models import Filters


@pytest.fixture
def wire(monkeypatch):
    """Stub AOSS. Records every request; replies with `size` fabricated hits."""
    sent = []

    def fake_request(endpoint, method, path, body=None, content_type=None):
        sent.append({"path": path, "body": body})
        if path == "_msearch":
            # One response per query line, in order. The lane under test is
            # identified by which body carries a "knn" query.
            docs = []
            for i, line in enumerate(body.decode().splitlines()):
                if not line.startswith("{\"index\""):
                    q = json.loads(line)
                    lane = "knn" if "knn" in json.dumps(q["query"]) else "bm25"
                    docs.append([f"{lane}-{i}#{j:04d}" for j in range(3)])
            return {"responses": [_hits_for(d) for d in docs]}
        return {"hits": {"hits": []}}     # structural lane + hydrate: empty

    def _hits_for(ids):
        return {"hits": {"hits": [
            {"_score": 1.0 - n / 100, "_source": {
                "chunk_id": cid, "chunk_text": "t", "citation_path": "c",
                "doc_type": "final_rule", "fr_doc_number": cid.split("#")[0],
                "cfr_title": "21", "cfr_part": "101", "kind": "preamble",
                "pub_date": "2024-12-27", "effective_date": "2025-04-28",
                "compliance_date": "2028-02-25"}}
            for n, cid in enumerate(ids)]}}

    monkeypatch.setattr(aoss_tier.aoss_client, "request", fake_request)
    monkeypatch.setattr(aoss_tier, "_hydrate", lambda ep, ids: [])
    monkeypatch.setattr(
        "retrieval.s3vectors_tier.embed_query", lambda q: [0.0] * 8)
    return sent


def queries(sent) -> list[dict]:
    """The query bodies from the _msearch, ndjson header lines dropped."""
    msearch = next(s for s in sent if s["path"] == "_msearch")
    return [json.loads(ln) for ln in msearch["body"].decode().splitlines()
            if not ln.startswith("{\"index\"")]


def test_off_by_default_sends_one_query_and_it_is_the_vector_one(wire, monkeypatch):
    """The default is the ruling: no BM25 query is issued at all.

    Not issued rather than issued-and-down-weighted. A lane weighted to nothing
    still costs a round trip's worth of work inside the engine, and latency is
    the only claim Tier B has left after (a).
    """
    monkeypatch.setattr(aoss_tier.config, "RETRIEVAL_LEXICAL_LANE", False)
    aoss_tier.retrieve_aoss("https://x", "did the date change?", Filters(), 6)
    bodies = queries(wire)
    assert len(bodies) == 1
    assert "knn" in json.dumps(bodies[0]["query"])
    assert "match" not in json.dumps(bodies[0]["query"])


def test_on_sends_both_queries_in_one_round_trip(wire, monkeypatch):
    """The reversal path. SPEC/02's "single hybrid query" is honoured by one
    `_msearch` carrying two queries, so turning the lane back on must not become
    two round trips."""
    monkeypatch.setattr(aoss_tier.config, "RETRIEVAL_LEXICAL_LANE", True)
    aoss_tier.retrieve_aoss("https://x", "did the date change?", Filters(), 6)
    bodies = queries(wire)
    assert len(bodies) == 2
    assert "match" in json.dumps(bodies[0]["query"]), "BM25 lane first"
    assert "knn" in json.dumps(bodies[1]["query"])
    assert len([s for s in wire if s["path"] == "_msearch"]) == 1


def test_off_the_knn_order_reaches_the_page(wire, monkeypatch):
    """Off, only the kNN response feeds the page, in its own order.

    An earlier version of this test claimed to rule out implementing the
    flag-off path as `rrf([knn])` rather than `hits[0][:k]`. **That claim was
    false and the test proved nothing**: single-lane RRF assigns
    weight/(c+rank+1), strictly decreasing in rank, then truncates at k, so it is
    identical to slicing in membership AND order — engineering review mutated the
    line to the unconditional `rrf(hits, k=k)` and all six tests here stayed
    green. `aoss_tier.py` now has one code path and makes no such claim.

    What remains is still worth pinning, and it is what this now asserts: the kNN
    lane's order survives to the page, and nothing from a lane that was never
    queried appears in it. That would fail if the response index were wrong, the
    order reversed, or the tail truncated from the front.
    """
    monkeypatch.setattr(aoss_tier.config, "RETRIEVAL_LEXICAL_LANE", False)
    out = aoss_tier.retrieve_aoss("https://x", "q", Filters(), 6)
    got = [c.chunk_id for c in out]
    assert got == sorted(got, key=lambda cid: int(cid.split("#")[1])), got
    assert all(c.chunk_id.startswith("knn-") for c in out), got


def test_on_the_bm25_lane_actually_reaches_the_page(wire, monkeypatch):
    """Guards the reversal being real rather than nominal: with the lane on, the
    page must contain chunks only the BM25 response supplied. A flag that flips a
    boolean but never changes the result is the defect config.RERANK had."""
    monkeypatch.setattr(aoss_tier.config, "RETRIEVAL_LEXICAL_LANE", True)
    out = aoss_tier.retrieve_aoss("https://x", "q", Filters(), 6)
    ids = [c.chunk_id for c in out]
    assert any(cid.startswith("bm25-") for cid in ids), ids
    assert any(cid.startswith("knn-") for cid in ids), ids


def test_the_response_count_check_follows_what_was_sent(wire, monkeypatch):
    """It was hardcoded to 2. With the lane off one query goes out, so a
    hardcoded 2 would raise AossError on every well-formed reply — and
    router.retrieve_traced catches AossError and falls back to Tier A, which
    would have made a broken Tier B look like a passing S3 Vectors run."""
    monkeypatch.setattr(aoss_tier.config, "RETRIEVAL_LEXICAL_LANE", False)

    def one_too_many(endpoint, method, path, body=None, content_type=None):
        if path == "_msearch":
            return {"responses": [{"hits": {"hits": []}}] * 2}
        return {"hits": {"hits": []}}

    monkeypatch.setattr(aoss_tier.aoss_client, "request", one_too_many)
    with pytest.raises(aoss_tier.aoss_client.AossError,
                       match=r"returned 2 responses, expected 1"):
        aoss_tier.retrieve_aoss("https://x", "q", Filters(), 6)


def test_the_default_is_off_in_config_not_only_in_this_test():
    """The ruling is the DEFAULT, not something a test sets up.

    Reading the module attribute rather than trusting the fixture: if someone
    flips the default without a spec edit and an ADR, this fails.
    """
    from shared import config
    assert config.RETRIEVAL_LEXICAL_LANE is False, (
        "ADR-0009 Ruling 3 resolved as (a): the lexical lane is off by default. "
        "Turning it back on requires the reversal condition in config.py — a "
        "probe the lexical lane wins — not an edit here")
