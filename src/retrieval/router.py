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
from dataclasses import dataclass

import boto3

from retrieval import fusion, rerank
from shared import config
from shared.config import SSM_SEARCH_ENDPOINT
from shared.models import Chunk, Filters

_ssm = boto3.client("ssm")
_cache: dict = {"endpoint": None, "at": 0.0}
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


def active_endpoint() -> str | None:
    now = time.monotonic()
    if now - _cache["at"] > _TTL:
        try:
            _cache["endpoint"] = _ssm.get_parameter(
                Name=SSM_SEARCH_ENDPOINT)["Parameter"]["Value"]
        except _ssm.exceptions.ParameterNotFound:
            _cache["endpoint"] = None
        _cache["at"] = now
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


def retrieve(query: str, filters: Filters, k: int = 8) -> list[Chunk]:
    """SPEC/02 contract. See retrieve_traced when the tier matters."""
    return retrieve_traced(query, filters, k)[0]


def retrieve_traced(query: str, filters: Filters,
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
