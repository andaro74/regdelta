"""Retrieval router — the two-tier seam (SPEC/02).

SSM /regdelta/search/endpoint present  -> AOSS hybrid tier
                            absent     -> S3 Vectors tier
Both tiers implement: retrieve(query, filters, k) -> list[Chunk]
"""
import time

import boto3

from shared.config import SSM_SEARCH_ENDPOINT
from shared.models import Chunk, Filters

_ssm = boto3.client("ssm")
_cache: dict = {"endpoint": None, "at": 0.0}
_TTL = 60.0


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


def retrieve(query: str, filters: Filters, k: int = 8) -> list[Chunk]:
    if endpoint := active_endpoint():
        from retrieval.aoss_tier import retrieve_aoss
        return retrieve_aoss(endpoint, query, filters, k)
    from retrieval.s3vectors_tier import retrieve_s3v
    return retrieve_s3v(query, filters, k)
