"""Tier A — S3 Vectors (always-on). SPEC/02.

1. Embed the query (Titan v2, same parameters as ingest).
2. QueryVectors on index `chunks` with a metadata pre-filter, topK = k*3.
3. Exact-citation assist: if the query names a citation, resolve it through
   the DynamoDB `citations` GSI and hydrate those chunks directly.
4. RRF-merge the two ranked lists, re-check filters client-side, return k.

Never re-embeds corpus chunks — only the query. The stored vectors are the
ones written at ingest (architecture rule).
"""
import json

from retrieval import expansion, fusion
from shared import config, models
from shared.models import Chunk, Filters
from shared.util import retry

_clients: dict = {}


def _client(name):
    # The "registry" branch that used to live here was dead: the DynamoDB table
    # handle is built by expansion._registry(), and nothing ever called
    # _client("registry"). Removed with the config.REGISTRY_TABLE reference it
    # was the only user of in this module.
    if name not in _clients:
        import boto3
        from botocore.config import Config

        # MAX_POOL_CONNECTIONS, AND IT IS A MEASUREMENT-VALIDITY SETTING RATHER
        # THAN A TUNING ONE. botocore's default is 10. SPEC/06's disposition
        # drives this path at 90 retrieval calls per second, which is
        # `rate x service time` ~ 32 in flight on Tier A and ~80 on Tier B —
        # three to eight times the pool. The excess calls do not fail; they
        # BLOCK in urllib3 waiting for a connection, and that wait lands inside
        # `router.retrieve()`, which is the interval the clause defines the p95
        # over. The disposition would have compared queueing delay in this
        # process against queueing delay in this process and called it a tier
        # difference. security-reviewer, M06, second pass.
        #
        # Harmless on the request path: connections are created lazily, so a
        # query Lambda serving one request at a time still opens one.
        _clients[name] = boto3.client(
            name, region_name=config.REGION,
            config=Config(max_pool_connections=config.RETRIEVAL_POOL_SIZE))
    return _clients[name]


def embed_query(query: str) -> list[float]:
    """Titan v2 with the ingest-identical parameters.

    `dimensions` and `normalize` MUST match processor.embed(). Titan returns a
    different vector for the same text at a different `dimensions`, and an
    un-normalized query against normalized corpus vectors silently degrades
    cosine ranking rather than erroring — a class of bug that shows up as
    "retrieval got a bit worse" and never as a failure.
    """
    rt = _client("bedrock-runtime")
    body = json.dumps({"inputText": query[:30000], "dimensions": config.EMBED_DIM,
                       "normalize": True})
    resp = retry(lambda: rt.invoke_model(modelId=config.EMBED_MODEL, body=body))
    return json.loads(resp["body"].read())["embedding"]


def _metadata_filter(filters: Filters, extra: dict | None = None) -> dict | None:
    """Filters -> S3 Vectors metadata filter expression.

    Pushdown is an optimisation, not the contract: router._finish re-checks
    every result with Filters.matches(). See the note below for why only the
    existence half of a date filter is pushed down.

    `extra` is ANDed in — the structural lane's `kind` restriction, which is
    not part of the caller's Filters. It goes through this function rather
    than being composed at the call site so the user's filters cannot be
    accidentally dropped from the structural query, which would let that lane
    return chunks the page then discards.
    """
    clauses: list[dict] = []
    for key in models.KEYWORD_FIELDS:
        if (want := getattr(filters, key)) is not None:
            clauses.append({key: {"$eq": want}})
    for key in models.DATE_FIELDS:
        if getattr(filters, key) is not None:
            # $exists, NOT $gte/$lte — see the note below.
            clauses.append({key: {"$exists": True}})
    if extra:
        clauses.append(extra)
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


# WHY DATE RANGES ARE NOT PUSHED DOWN HERE
#
# S3 Vectors rejects range operators on string metadata: `{"compliance_date":
# {"$gte": "2028-01-01"}}` returns ValidationException "Invalid filter".
# Verified against the live index, not inferred from the docs — `$eq`, `$and`
# and `$exists` on the same field all succeed, so it is the range operator on
# a string value specifically. (Reproduce with tests/probe_s3v_filter.py.)
#
# ISO dates would have to be stored as integers (20280225) to be range-
# filterable in-engine, which means re-ingesting the corpus — SPEC/02 puts
# that out of scope, and it would buy little.
#
# What IS pushed down is `$exists`, and that is not a consolation prize: it is
# precisely ADR-0006's rule. A date filter selects documents that ESTABLISH
# that date, and DateRange.contains(None) is False, so a document with no
# compliance date can never satisfy a compliance-date range. `$exists` is
# therefore a strictly-safe pruning — it cannot remove a document the range
# would have kept — and it removes exactly the ones the rule is about. For
# probe r02, `$exists` alone excludes every 2025-03118 chunk in-engine, which
# is the whole of that probe's must_not_return.
#
# The range bounds are then applied by router._finish via Filters.matches,
# which is the contract's authority for both tiers anyway. The residual cost
# is recall, not correctness: candidates are ranked by similarity before the
# bounds prune them, so a very narrow range over a large in-corpus date set
# could push a matching chunk past the k*3 window. Not observed on this probe
# set; recorded so that a future recall miss on a filtered probe is diagnosed
# here rather than rediscovered.


def _hydrate(chunk_ids: list[str]) -> list[Chunk]:
    """chunk ids -> Chunks, via S3 Vectors GetVectors metadata.

    The GSI stores ids and citations only, so the assist lane has no text.
    GetVectors is the cheap hydration path: the metadata it returns is the
    same record the query lane already gets, so both lanes produce identical
    Chunk objects for the same id and RRF can merge them by key.
    """
    if not chunk_ids:
        return []
    sv = _client("s3vectors")
    out: list[Chunk] = []
    for i in range(0, len(chunk_ids), 100):
        resp = retry(lambda batch=chunk_ids[i:i + 100]: sv.get_vectors(
            vectorBucketName=config.VECTOR_BUCKET,
            indexName=config.VECTOR_INDEX,
            keys=batch, returnMetadata=True, returnData=False))
        for v in resp.get("vectors", []):
            out.append(Chunk.from_metadata(v["key"], v.get("metadata") or {}))
    return expansion.restore_order(out, chunk_ids)


def _query(query_vector, filters: Filters, k: int,
           extra: dict | None = None) -> list[Chunk]:
    """One QueryVectors call -> Chunks. Used by both lanes."""
    sv = _client("s3vectors")
    kwargs = {"vectorBucketName": config.VECTOR_BUCKET,
              "indexName": config.VECTOR_INDEX,
              "topK": k,
              "queryVector": {"float32": query_vector},
              "returnMetadata": True,
              "returnDistance": True}
    if (mf := _metadata_filter(filters, extra)) is not None:
        kwargs["filter"] = mf
    resp = retry(lambda: sv.query_vectors(**kwargs))
    return [Chunk.from_metadata(v["key"], v.get("metadata") or {})
            for v in resp.get("vectors", [])]


def retrieve_s3v(query: str, filters: Filters, k: int) -> list[Chunk]:
    """`k` is the candidate width, not the page size.

    router.retrieve_traced passes k*3 and cuts to k after re-applying filters,
    so `topK` here is SPEC/02's "topK=k*3" measured from the caller's k.
    """
    query_vector = embed_query(query)

    # Relevance lane. NOT diversified here: per-document capping shapes the
    # PAGE, so it lives in router._finish where both tiers get the same rule.
    relevance = _query(query_vector, filters, k)

    # Structural lane — the same embedding signal over only the paragraphs
    # that state what a document does. `page` rather than `k` because this
    # lane is meant to put a handful of candidates in contention, not to
    # supply a second full result set. k//3 is the page size by construction
    # of the router, so it is derived rather than tuned.
    page = max(1, k // 3)
    structural: list[Chunk] = []
    if docs := expansion.documents_in_play(relevance, page):
        structural = _query(query_vector, filters, page, {"$and": [
            {"kind": {"$in": list(config.RETRIEVAL_STRUCTURAL_KINDS)}},
            {"fr_doc_number": {"$in": docs}}]})
    assist = expansion.merge_lane(
        _hydrate(expansion.query_citation_ids(query, page)), structural)

    lanes, weights = [relevance], [1.0]
    if assist:
        lanes.append(assist)
        weights.append(config.RETRIEVAL_ASSIST_WEIGHT)
    return fusion.rrf(lanes, k=k, weights=weights)
