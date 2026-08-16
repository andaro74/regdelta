"""Reciprocal Rank Fusion and per-document diversification — shared by both
tiers so a ranking decision is made once, not twice in two dialects."""
from collections import defaultdict

from shared.models import Chunk


def rrf(result_lists: list[list[Chunk]], k: int = 8, c: int = 60,
        weights: list[float] | None = None) -> list[Chunk]:
    """Reciprocal Rank Fusion, optionally weighted per lane.

    Unweighted RRF assumes every lane is an equally good relevance signal.
    That is false for a lane whose job is RECALL — the structural-expansion
    lane selects chunks by which document they belong to, not by how well they
    match the query, so at equal weight its first entry ties with the vector
    lane's first entry and a recall device becomes a ranking device. Measured:
    it put a barely-relevant document's DATES paragraph at rank 4 and pushed
    the chunk that actually answered the question to rank 12.
    """
    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for lane, results in enumerate(result_lists):
        weight = 1.0 if weights is None else weights[lane]
        for rank, chunk in enumerate(results):
            scores[chunk.chunk_id] += weight / (c + rank + 1)
            by_id.setdefault(chunk.chunk_id, chunk)
    # Ties are broken by chunk_id rather than left to dict order, so the same
    # corpus and query produce the same list on every run and on both tiers.
    # Cross-tier Jaccard (criterion 3) would otherwise measure iteration order.
    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    out = []
    for cid in ranked:
        ch = by_id[cid]
        ch.score = scores[cid]
        out.append(ch)
    return out


def doc_of(chunk: Chunk) -> str:
    """The document a chunk belongs to. chunk_id is '<doc_id>#<nnnn>'."""
    return chunk.chunk_id.split("#", 1)[0]


def diversify(chunks: list[Chunk], per_doc: int, limit: int) -> list[Chunk]:
    """Fill `limit` slots, letting no document take more than `per_doc` of
    them until every other candidate has been considered.

    Nearest-neighbour search over a corpus containing one 389-chunk final rule
    returns runs of adjacent preamble paragraphs from that rule: they are
    genuinely similar to each other and to almost any query about it. Five of
    eight slots then say nearly the same thing, and the DATES paragraph
    carrying the actual deadline never makes the page.

    This is a recall mechanism, not a relevance judgement — it does not claim
    the deferred chunks are irrelevant, only that the sixth paragraph of one
    document is worth less than the first of another for a question that spans
    documents. Every question this product answers spans documents: what
    changed, and what the change did to the rule it changed.

    Deferred candidates BACK-FILL the remaining slots rather than being
    dropped. A cap that shortened the page would trade one silent failure for
    another: eight slots asking about one rule is bad, but five results where
    the caller asked for eight is worse, because nothing reports it.
    """
    kept: list[Chunk] = []
    deferred: list[Chunk] = []
    seen: dict[str, int] = defaultdict(int)
    for chunk in chunks:
        if len(kept) >= limit:
            break
        doc = doc_of(chunk)
        if seen[doc] >= per_doc:
            deferred.append(chunk)
            continue
        seen[doc] += 1
        kept.append(chunk)
    for chunk in deferred:
        if len(kept) >= limit:
            break
        kept.append(chunk)
    return kept
