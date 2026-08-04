"""Tier A — S3 Vectors (always-on). TODO(SPEC/02).

Steps:
1. Embed query (Titan v2 via Bedrock).
2. s3vectors QueryVectors: bucket=VECTOR_BUCKET, index=VECTOR_INDEX,
   topK=k*3, metadata filter from Filters.
3. If citations.looks_like_citation_query: exact matches via the DynamoDB
   citation GSI; merge with fusion.rrf().
4. Return top-k Chunks (hydrate text from metadata or corpus bucket).
"""
from shared.models import Chunk, Filters


def retrieve_s3v(query: str, filters: Filters, k: int) -> list[Chunk]:
    raise NotImplementedError("SPEC/02 Tier A")
