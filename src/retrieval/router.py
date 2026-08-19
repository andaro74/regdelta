"""Retrieval router — the two-tier seam (SPEC/02).

SSM /regdelta/search/endpoint present  -> AOSS hybrid tier
                            absent     -> S3 Vectors tier
Both tiers implement: retrieve(query, filters, k) -> list[Chunk]

The router owns three things the tiers must NOT each decide for themselves:
which tier answers, what a filter means (Filters.matches is re-applied here),
and how many results come back. Anything a tier decides privately becomes
cross-tier drift, which is what SPEC/02 criterion 3 gates on — and a gate
cannot distinguish real drift from two engines disagreeing about the contract.
"""
import time
from dataclasses import dataclass, replace

import boto3

from retrieval import fusion, rerank
from shared import config
from shared.config import SSM_SEARCH_ENDPOINT
from shared.models import Chunk, Filters

_ssm = boto3.client("ssm")
# `fetched` is not redundant with `at`. The refresh used to be guarded by
# `now - at > _TTL` alone with `at` seeded to 0.0, which makes the first call
# ask `time.monotonic() > 60` — a question about how long THE MACHINE has been
# up, not about how stale the value is. On a laptop monotonic is thousands of
# seconds so the lookup always fired and the code read as correct; in a Lambda
# microVM the clock starts near zero, so for the first minute of every
# container's life the seeded None was returned WITHOUT CONSULTING SSM and the
# router silently served S3 Vectors while SSM held an AOSS endpoint. An explicit
# "have we ever fetched" flag cannot be fooled by the clock's origin.
_cache: dict = {"endpoint": None, "at": 0.0, "fetched": False}
_TTL = 60.0


@dataclass(frozen=True)
class Resolution:
    """Which tier actually answered, and why. Never inferred by the caller.

    SPEC/02 criterion 2 exists because an unreachable hot tier falls back
    silently: two S3 Vectors runs would otherwise score green as "both tiers
    pass". The harness asserts `tier` against what it asked for, so the
    fallback stays available to production and cannot be mistaken for
    coverage in an eval run.
    """
    tier: str                       # "aoss" | "s3vectors"
    endpoint: str | None
    fallback_reason: str | None = None
    # What the reranker did, verbatim from retrieval.rerank. SPEC/02's RERANK
    # adoption bar requires each scorecard to record the candidate set the
    # reranker scored and whether it was taken before or after per-document
    # diversification — a null result over a post-diversification set measures
    # the ordering, not the reranker. Carried out rather than logged so a
    # scorecard cannot claim a reranked run that did not happen.
    rerank: str = "off"
    #: How long the whole router call took, in milliseconds — the SAME span
    #: `make demo-parity` times for the artifact (`router.retrieve()`, which is
    #: `retrieve_traced` plus a tuple index), so the two numbers are the same
    #: quantity from two vantages: an in-process harness on a laptop against a
    #: Lambda round trip. SPEC/04 calls those "different instruments" and gates
    #: on the artifact; the UI readout shows this one.
    #:
    #: It spans the WHOLE call, so on a fallback it includes the failed AOSS
    #: attempt while `tier` reads `s3vectors`. That is deliberate: the artifact
    #: measures `router.retrieve()` the same way, and `fallback_reason` is on
    #: the same object to say why the number is large. Timing only the attempt
    #: that succeeded would report a fast Tier A for a request that spent most
    #: of its time failing at Tier B.
    #:
    #: None only when a Resolution is constructed outside `retrieve_traced`
    #: (tests, hand-built fixtures) — a zero would read as "instant".
    elapsed_ms: float | None = None


def active_endpoint() -> str | None:
    now = time.monotonic()
    if not _cache.get("fetched") or now - _cache["at"] > _TTL:
        try:
            _cache["endpoint"] = _ssm.get_parameter(
                Name=SSM_SEARCH_ENDPOINT)["Parameter"]["Value"]
        except _ssm.exceptions.ParameterNotFound:
            _cache["endpoint"] = None
        _cache["at"] = now
        _cache["fetched"] = True
    return _cache["endpoint"]


def active_tier() -> str:
    return "aoss" if active_endpoint() else "s3vectors"


def reset_cache() -> None:
    """Drop the memoised SSM lookup.

    `make up` / `make down` flip the parameter, and the harness runs both
    tiers within one 60s TTL window in a single process. Without this the
    second run would answer from the first run's cached endpoint and the
    resolved-tier assertion would fail for a reason that has nothing to do
    with either tier.
    """
    _cache["endpoint"] = None
    _cache["at"] = 0.0
    # Clearing `at` alone had the same clock dependency as the seed above: on a
    # cold process the next call would find `monotonic() - 0.0 < _TTL` and hand
    # back the endpoint this function was called to forget — leaving the second
    # tier run reading the first tier's endpoint, which is the one thing
    # reset_cache exists to prevent.
    _cache["fetched"] = False


def retrieve(query: str, filters: Filters, k: int = 8) -> list[Chunk]:
    """SPEC/02 contract. See retrieve_traced when the tier matters."""
    return retrieve_traced(query, filters, k)[0]


def hydrate(chunk_ids: list[str]) -> list[Chunk]:
    """chunk ids -> Chunks with text, through whichever tier is live.

    Both tiers already hydrate ids for their exact-citation assist lane, but
    both keep it private, so a caller outside retrieval had no way to turn an
    id into text. `crossref_agent` was that caller: it resolved cross-references
    to `chunk_ids` and stored the ids, which no prompt can read. Resolving a
    reference and handing on an identifier is not resolving it.

    Falls back to the always-on tier on an AOSS error, for the same reason
    `retrieve_traced` does — a deployed-but-broken hot tier must not remove
    context the other tier can supply.
    """
    if not chunk_ids:
        return []
    endpoint = active_endpoint()
    if endpoint:
        from retrieval import aoss_client
        from retrieval.aoss_tier import _hydrate as _hydrate_aoss
        try:
            return _hydrate_aoss(endpoint, chunk_ids)
        except aoss_client.AossError:
            pass
    from retrieval.s3vectors_tier import _hydrate as _hydrate_s3v
    return _hydrate_s3v(chunk_ids)


def retrieve_traced(query: str, filters: Filters,
                    k: int = 8) -> tuple[list[Chunk], Resolution]:
    """The router call, timed. See `_resolve` for what it does.

    The timing lives here rather than in `_resolve` so that every return path
    is timed by construction — the fallback path returns from a different
    place than the hot path, and a stopwatch written at each `return` is one
    a later branch can forget.
    """
    t0 = time.perf_counter()
    chunks, resolution = _resolve(query, filters, k)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return chunks, replace(resolution, elapsed_ms=elapsed_ms)


def _resolve(query: str, filters: Filters,
             k: int = 8) -> tuple[list[Chunk], Resolution]:
    filters = filters or Filters()
    width = k * 3           # fuse wide, filter, then cut — see below
    fallback_reason = None
    endpoint = active_endpoint()

    if endpoint:
        from retrieval import aoss_client
        from retrieval.aoss_tier import retrieve_aoss
        try:
            raw = retrieve_aoss(endpoint, query, filters, width)
            chunks, note = _finish(query, raw, filters, k)
            return chunks, Resolution("aoss", endpoint, rerank=note)
        except aoss_client.AossError as e:
            # "present + reachable" (SPEC/02 Contract): a deployed-but-broken
            # hot tier must not take the API down, because the always-on tier
            # can answer. The reason is carried out, not logged and dropped —
            # a silent fallback is how two S3 Vectors runs get reported as
            # two-tier coverage.
            fallback_reason = f"{type(e).__name__}: {e}"[:300]

    from retrieval.s3vectors_tier import retrieve_s3v
    raw = retrieve_s3v(query, filters, width)
    chunks, note = _finish(query, raw, filters, k)
    return chunks, Resolution("s3vectors", endpoint, fallback_reason,
                              rerank=note)


def _finish(query: str, raw: list[Chunk], filters: Filters,
            k: int) -> tuple[list[Chunk], str]:
    """Re-apply filters client-side, rerank, cap, then truncate.

    Both tiers push filters into their engine as an optimisation, in two
    different dialects. This is the one place that decides what a filter
    *means*, so a dialect that quietly matches everything (S3 Vectors on an
    unknown key) or quietly matches nothing cannot change the answer — it can
    only change how many candidates arrive here.

    Fusion runs at k*3 and the cut to k happens after filtering, so a filter
    that prunes most of the candidate set still returns a full page rather
    than a short one.

    Per-document capping happens here for the same reason: it shapes the page,
    and a page-shaping rule applied inside one tier would be a difference
    between the tiers that criterion 3 reads as retrieval drift.

    Reranking, when enabled, runs HERE — after filtering, BEFORE diversify.
    `diversify` is what evicted the chunk reranking exists to recover
    (2025-03118 gets exactly three slots and Tier B spends them on
    #0000/#0001/#0005), so a reranker placed after it would be reordering a page
    the chunk had already left. SPEC/02's adoption bar requires the scorecard to
    record which side of `diversify` the candidate set came from, so a null
    result cannot be misread as the reranker not helping. See
    retrieval/rerank.py.
    """
    kept = [c for c in raw if filters.matches(c)]
    kept, rerank_note = rerank.rerank(query, kept)
    return fusion.diversify(kept, config.RETRIEVAL_PER_DOC_CAP, k), rerank_note
