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

from retrieval import aoss_client
from retrieval.fusion import rrf
from shared.models import Chunk, Filters


def _filter_clauses(filters: Filters) -> list[dict]:
    """Filters -> OpenSearch bool/filter clauses.

    Date fields are mapped as `date`, so a range clause excludes documents
    that do not carry the field at all — which is exactly ADR-0006's rule
    (a document is selected only by a date it establishes) and matches
    DateRange.contains(None) is False on the client side.
    """
    clauses: list[dict] = []
    for key in ("cfr_title", "cfr_part", "doc_type", "fr_doc_number"):
        if (want := getattr(filters, key)) is not None:
            clauses.append({"term": {key: want}})
    for key in ("pub_date", "effective_date", "compliance_date", "version_date"):
        if (rng := getattr(filters, key)) is None:
            continue
        bounds = {}
        if rng.gte is not None:
            bounds["gte"] = rng.gte
        if rng.lte is not None:
            bounds["lte"] = rng.lte
        clauses.append({"range": {key: bounds}})
    return clauses


_SOURCE_FIELDS = ["chunk_id", "chunk_text", "citation_path", "doc_type",
                  "cfr_title", "cfr_part", "fr_doc_number", "pub_date",
                  "effective_date", "compliance_date", "version_date"]


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


def retrieve_aoss(endpoint: str, query: str, filters: Filters, k: int) -> list[Chunk]:
    """`k` is the candidate width, not the page size — see retrieve_s3v."""
    from retrieval.s3vectors_tier import embed_query

    size = k
    clauses = _filter_clauses(filters)
    header = json.dumps({"index": aoss_client.INDEX_NAME})
    ndjson = "\n".join([
        header, json.dumps(_bm25_body(query, clauses, size)),
        header, json.dumps(_knn_body(embed_query(query), clauses, size)),
    ]) + "\n"

    resp = aoss_client.request(
        endpoint, "POST", "_msearch", ndjson.encode(),
        content_type="application/x-ndjson")
    responses = resp.get("responses") or []
    if len(responses) != 2:
        raise aoss_client.AossError(
            f"_msearch returned {len(responses)} responses, expected 2")
    return rrf([_hits(r) for r in responses], k=k)
