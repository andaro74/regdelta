"""Tier B — AOSS hybrid (ephemeral). TODO(SPEC/02).

One query: bool{ should:[ match(chunk_text), match(citation_path) ],
knn(embedding, k*3), filter:[dates, cfr_part] } → client-side RRF of the
BM25 and kNN result lists → top-k. SigV4 service name 'aoss'.
"""
from shared.models import Chunk, Filters


def retrieve_aoss(endpoint: str, query: str, filters: Filters, k: int) -> list[Chunk]:
    raise NotImplementedError("SPEC/02 Tier B")
