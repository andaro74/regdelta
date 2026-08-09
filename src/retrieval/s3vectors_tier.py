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
import re

from retrieval import fusion
from shared import citations, config
from shared.models import Chunk, Filters
from shared.util import retry

_clients: dict = {}


def _client(name):
    if name not in _clients:
        import boto3
        if name == "registry":
            _clients[name] = boto3.resource(
                "dynamodb", region_name=config.REGION).Table(config.REGISTRY_TABLE)
        else:
            _clients[name] = boto3.client(name, region_name=config.REGION)
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


def _metadata_filter(filters: Filters) -> dict | None:
    """Filters -> S3 Vectors metadata filter expression.

    Pushdown is an optimisation, not the contract: router._finish re-checks
    every result with Filters.matches(). See the note below for why only the
    existence half of a date filter is pushed down.
    """
    clauses: list[dict] = []
    for key in ("cfr_title", "cfr_part", "doc_type", "fr_doc_number"):
        if (want := getattr(filters, key)) is not None:
            clauses.append({key: {"$eq": want}})
    for key in ("pub_date", "effective_date", "compliance_date", "version_date"):
        if getattr(filters, key) is not None:
            # $exists, NOT $gte/$lte — see the note below.
            clauses.append({key: {"$exists": True}})
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


# "21 CFR 74.303(a)(1)" -> "21 CFR 74.303". A chunk's citation_path carries the
# paragraph it came from; the document's structural chunks are filed under the
# section.
_PARA_SUFFIX_RE = re.compile(r"(?:\([a-z0-9]+\))+\Z", re.ASCII | re.IGNORECASE)


def _lookup_citation(cite: str, limit: int) -> list[str]:
    from boto3.dynamodb.conditions import Key
    resp = _client("registry").query(
        IndexName="citations",
        KeyConditionExpression=Key("citation").eq(cite),
        Limit=limit)
    return [item["chunk_id"] for item in resp.get("Items", [])]


def _doc_citation(chunk: Chunk) -> str | None:
    """The citation a document's STRUCTURAL chunks are filed under.

    The chunker gives an FR document's DATES, summary and amdpar chunks the
    bare FR citation ("90 FR 4628") and gives every preamble chunk that
    citation plus a heading. So the bare citation is a precise selector for
    exactly the structural chunks — which is what makes the expansion below
    cheap and specific rather than "fetch the document".
    """
    if not chunk.citation_path:
        return None
    found = citations.extract_citations(chunk.citation_path)
    if not found:
        return None
    return _PARA_SUFFIX_RE.sub("", found[0]).strip()


def _citation_assist(query: str, vector_lane: list[Chunk], k: int) -> list[Chunk]:
    """Lexical lane: citation -> chunk ids, through the DynamoDB `citations` GSI.

    Two sources, in priority order:

    1. Citations named IN THE QUERY (SPEC/02's "exact-citation assist").
    2. STRUCTURAL EXPANSION — the citations of the documents the vector lane
       already ranked highest.

    (2) is the fix for a failure mode that showed up on first measurement and
    was unanimous: every probe that missed, missed a DATES or amendatory-
    instructions chunk belonging to a document sitting at vector rank 1. Those
    chunks are short, formulaic legalese ("DATES: This order is effective
    January 15, 2027, except for amendatory instruction 4...") and they embed
    far from a natural-language question, so nearest-neighbour search buries
    them at rank 12-46 while returning six paragraphs of the same document's
    preamble. They are also, for this product specifically, the highest-value
    chunks in the corpus: they carry the dates and the CFR edits.

    So the expansion is not "fetch more of the top document". It is: once the
    vector lane has identified WHICH documents matter, the paragraphs stating
    what those documents DO are candidates, and the fusion decides their rank.
    A hybrid tier gets this from BM25 matching "effective" and "compliance
    date" as terms; Tier A has no lexical lane at all without it.
    """
    ids: list[str] = []
    for cite in dict.fromkeys(citations.extract_citations(query)):
        ids.extend(_lookup_citation(cite, k))

    # Only documents good enough to be ON the page get expanded. `k` here is
    # the candidate width and the router sets it to three times the page size,
    # so k//3 IS the page size — a derived bound, not a tuned one.
    #
    # Gating on "the top N DISTINCT documents" instead was measurably wrong:
    # in a 24-long candidate list the third distinct document can sit at rank
    # 20, and expanding it lifted the Red No. 3 order's DATES paragraph to
    # rank 4 of a question entirely about the "healthy" rule — a confident,
    # correctly-cited answer about the wrong regulation.
    window = vector_lane[:max(1, k // 3)]

    expanded = 0
    seen_docs: set[str] = set()
    for chunk in window:
        doc = fusion.doc_of(chunk)
        if doc in seen_docs:
            continue
        seen_docs.add(doc)
        if (cite := _doc_citation(chunk)) is None:
            continue
        ids.extend(_lookup_citation(cite, config.RETRIEVAL_STRUCTURAL_PER_DOC))
        expanded += 1
        if expanded >= config.RETRIEVAL_EXPAND_DOCS:
            break

    return _hydrate(list(dict.fromkeys(ids))[:k])


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
    # GetVectors does not promise input order; restore it so the assist lane
    # is a ranked list (GSI order = citation order in the query) rather than
    # an arbitrary one. RRF scores by rank, so an unordered lane is noise.
    order = {cid: n for n, cid in enumerate(chunk_ids)}
    out.sort(key=lambda c: order.get(c.chunk_id, len(order)))
    return out


def retrieve_s3v(query: str, filters: Filters, k: int) -> list[Chunk]:
    """`k` is the candidate width, not the page size.

    router.retrieve_traced passes k*3 and cuts to k after re-applying filters,
    so `topK` here is SPEC/02's "topK=k*3" measured from the caller's k.
    """
    sv = _client("s3vectors")
    kwargs = {"vectorBucketName": config.VECTOR_BUCKET,
              "indexName": config.VECTOR_INDEX,
              "topK": k,
              "queryVector": {"float32": embed_query(query)},
              "returnMetadata": True,
              "returnDistance": True}
    if (mf := _metadata_filter(filters)) is not None:
        kwargs["filter"] = mf
    resp = retry(lambda: sv.query_vectors(**kwargs))
    # NOT diversified here. Per-document capping is a property of the PAGE, so
    # it lives in router._finish where both tiers get the identical rule. Doing
    # it inside the lane also corrupted the expansion below: capping pulled
    # low-relevance documents into the top-3 and expanded those instead of the
    # ones the query was actually about.
    vector_lane = [Chunk.from_metadata(v["key"], v.get("metadata") or {})
                   for v in resp.get("vectors", [])]

    lanes = [vector_lane]
    # The assist runs unconditionally, not only for citation-shaped queries:
    # its second source is the structural expansion, which keys off the
    # documents the vector lane found rather than off anything in the query
    # text. looks_like_citation_query() gated the old single-source version
    # and would now suppress the expansion for every plain-English question —
    # which is all of them.
    #
    # An empty assist lane is dropped rather than appended: RRF scores by rank
    # within a lane, so an empty lane changes no ordering, but appending one
    # would make the recorded scores depend on whether the assist found
    # anything. Same top-k either way, different numbers in the scorecard.
    weights = [1.0]
    if assist := _citation_assist(query, vector_lane, k):
        lanes.append(assist)
        weights.append(config.RETRIEVAL_ASSIST_WEIGHT)
    return fusion.rrf(lanes, k=k, weights=weights)
