"""Reciprocal Rank Fusion — shared by both tiers. Working code."""
from collections import defaultdict

from shared.models import Chunk


def rrf(result_lists: list[list[Chunk]], k: int = 8, c: int = 60) -> list[Chunk]:
    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for results in result_lists:
        for rank, chunk in enumerate(results):
            scores[chunk.chunk_id] += 1.0 / (c + rank + 1)
            by_id.setdefault(chunk.chunk_id, chunk)
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    out = []
    for cid in ranked:
        ch = by_id[cid]
        ch.score = scores[cid]
        out.append(ch)
    return out
