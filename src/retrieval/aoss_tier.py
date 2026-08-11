"""Tier B — AOSS hybrid (ephemeral). SPEC/02.

BM25 on chunk_text + citation_path, kNN on the stored embedding, the same
filters expressed as bool/filter clauses, then client-side RRF of the two
ranked lists.

SPEC/02 says "single hybrid query ... client-side RRF". Those two halves pull
against each other: one query yields one ranked list, and RRF needs two. This
sends both as one `_msearch` — a single round trip carrying two queries, which
is what the spec's intent (no extra latency, fusion done here rather than by a
search pipeline) actually requires. Noted rather than silently resolved.
"""
import json

from retrieval import aoss_client, expansion
from retrieval.fusion import rrf
from shared import config, models
from shared.models import Chunk, Filters


def _filter_clauses(filters: Filters) -> list[dict]:
    """Filters -> OpenSearch bool/filter clauses.

    Date fields are mapped as `date`, so a range clause excludes documents
    that do not carry the field at all — which is exactly ADR-0006's rule
    (a document is selected only by a date it establishes) and matches
    DateRange.contains(None) is False on the client side.
    """
    # Iterate the shared field lists rather than hand-listing, for the same
    # reason _SOURCE_FIELDS does: a hand-list silently omits a field the other
    # tier honours. It had already drifted — `kind` is in KEYWORD_FIELDS and
    # Filters.matches enforces it, but this list predated it, so Tier B pushed
    # no `kind` clause into the engine. Tier A filled its 24 candidate slots
    # with matching chunks while Tier B filled them with anything and
    # router._finish then discarded nearly all of them: a short page on one tier
    # and a full one on the other, which is the silent divergence this design
    # exists to make unrepresentable. No current probe filters on `kind`, so no
    # recorded scorecard changes.
    clauses: list[dict] = []
    for key in models.KEYWORD_FIELDS:
        if (want := getattr(filters, key)) is not None:
            clauses.append({"term": {key: want}})
    for key in models.DATE_FIELDS:
        if (rng := getattr(filters, key)) is None:
            continue
        bounds = {}
        if rng.gte is not None:
            bounds["gte"] = rng.gte
        if rng.lte is not None:
            bounds["lte"] = rng.lte
        clauses.append({"range": {key: bounds}})
    return clauses


# Derived, not hand-listed: a _source list that drifts from what the writer
# stores returns chunks with silently empty fields, and a filter re-check in
# router._finish would then drop them for "not matching" a value that was
# simply never fetched.
_SOURCE_FIELDS = ["chunk_id", *models.INDEX_METADATA_KEYS]


def _bm25_body(query: str, clauses: list[dict], size: int) -> dict:
    return {
        "size": size,
        "_source": _SOURCE_FIELDS,
        "query": {"bool": {
            "should": [{"match": {"chunk_text": query}},
                       {"match": {"citation_path": query}}],
            "minimum_should_match": 1,
            "filter": clauses,
        }},
    }


def _knn_body(vector: list[float], clauses: list[dict], size: int) -> dict:
    knn: dict = {"vector": vector, "k": size}
    if clauses:
        # Efficient (pre-)filtering inside the faiss engine. Without it the
        # kNN lane would return its k nearest overall and the filter would
        # prune afterwards, so a narrow filter could return nothing while
        # matching documents sat just outside the k.
        knn["filter"] = {"bool": {"filter": clauses}}
    return {"size": size, "_source": _SOURCE_FIELDS,
            "query": {"knn": {"embedding": knn}}}


def _hits(response: dict) -> list[Chunk]:
    if "error" in response:
        raise aoss_client.AossError(json.dumps(response["error"])[:2000])
    out = []
    for hit in response.get("hits", {}).get("hits", []):
        src = hit.get("_source") or {}
        # chunk_id lives in _source, not _id: AOSS assigns its own document
        # ids and the reindex Lambda does not set them (see retrieval.reindex).
        cid = src.get("chunk_id")
        if cid:
            out.append(Chunk.from_metadata(cid, src, score=hit.get("_score") or 0.0))
    return out


def _hydrate(endpoint: str, chunk_ids: list[str]) -> list[Chunk]:
    """chunk ids -> Chunks, from this tier's own index.

    Deliberately NOT via S3 Vectors, even though the always-on tier could
    answer it: the hot tier must be self-contained, and hydrating one tier's
    assist lane out of the other's store would make a stale or partial hot
    index invisible — the assist would keep returning correct text for chunks
    that are not in the index being measured.
    """
    if not chunk_ids:
        return []
    body = {"size": len(chunk_ids), "_source": _SOURCE_FIELDS,
            "query": {"terms": {"chunk_id": chunk_ids}}}
    resp = aoss_client.request(
        endpoint, "POST", f"{aoss_client.INDEX_NAME}/_search", body)
    return expansion.restore_order(_hits(resp), chunk_ids)


def retrieve_aoss(endpoint: str, query: str, filters: Filters, k: int) -> list[Chunk]:
    """`k` is the candidate width, not the page size — see retrieve_s3v."""
    from retrieval.s3vectors_tier import embed_query

    clauses = _filter_clauses(filters)
    vector = embed_query(query)
    # The structural lane asks for a page's worth, not a full candidate set —
    # it puts a handful of chunks in contention rather than supplying a second
    # result set. k//3 is the page size by construction of the router.
    page = max(1, k // 3)

    header = json.dumps({"index": aoss_client.INDEX_NAME})
    ndjson = "\n".join([
        header, json.dumps(_bm25_body(query, clauses, k)),
        header, json.dumps(_knn_body(vector, clauses, k)),
    ]) + "\n"

    resp = aoss_client.request(
        endpoint, "POST", "_msearch", ndjson.encode(),
        content_type="application/x-ndjson")
    responses = resp.get("responses") or []
    if len(responses) != 2:
        raise aoss_client.AossError(
            f"_msearch returned {len(responses)} responses, expected 2")
    bm25, knn = (_hits(r) for r in responses)

    # BM25 and kNN fuse into ONE relevance lane, so this tier presents the same
    # two-lane shape as Tier A: [relevance, structural].
    #
    # Three flat lanes was tried and measured strictly worse — 6/9 -> 4/9. The
    # argument for flattening was that pre-fusing halves each relevance signal
    # while leaving the structural lane whole, so it outweighs BM25 two to one;
    # that is true and it is not a defect. The structural lane competes with
    # the relevance signal AS A WHOLE, because it answers a different question
    # ("which paragraphs state what this document does") rather than offering a
    # third opinion on the same one. Flattening buried the DATES paragraphs
    # again, which is the failure the lane exists to fix.
    relevance = rrf([bm25, knn], k=k)

    # The structural lane is NOT a Tier A workaround for weak vector search.
    # Measured on the live hot tier: Tier B scored 3/9 without it and missed
    # the same DATES and amendatory-instruction chunks, because BM25 does not
    # favour a short DATES paragraph for a plain-English question either.
    #
    # A second round trip, not a third query in the _msearch above: it is
    # scoped to the documents the RELEVANCE lane found, which is not known
    # until that response comes back. Scoping matters more than the round trip
    # — unscoped, this lane returns the most query-similar deadlines in the
    # whole corpus, including from rules the query never mentioned.
    structural: list[Chunk] = []
    if docs := expansion.documents_in_play(relevance, page):
        structural = _hits(aoss_client.request(
            endpoint, "POST", f"{aoss_client.INDEX_NAME}/_search",
            _knn_body(vector, [
                *clauses,
                {"terms": {"kind": list(config.RETRIEVAL_STRUCTURAL_KINDS)}},
                {"terms": {"fr_doc_number": docs}}], page)))

    assist = expansion.merge_lane(
        _hydrate(endpoint, expansion.query_citation_ids(query, page)),
        structural)

    lanes, weights = [relevance], [1.0]
    if assist:
        lanes.append(assist)
        weights.append(config.RETRIEVAL_ASSIST_WEIGHT)
    return rrf(lanes, k=k, weights=weights)
