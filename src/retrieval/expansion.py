"""Structural expansion — the lexical lane, shared by BOTH tiers (SPEC/02).

Selects chunk ids; it does not fetch them. Hydration differs per tier (S3
Vectors metadata vs an AOSS terms query) but the SELECTION must not, or the
two tiers return different chunks for reasons that have nothing to do with
ranking and criterion 3's Jaccard measures the difference.

## Why this exists

First live measurement of Tier A: recall@8 = 0.50, and every miss was the
DATES or amendatory-instructions paragraph of a document the relevance lane
had already ranked FIRST. Those paragraphs are short formulaic legalese —
"DATES: This order is effective January 15, 2027, except for amendatory
instruction 4…" — and they sit far from a natural-language question in
embedding space, at ranks 12 to 46, while six adjacent preamble paragraphs of
the same 389-chunk rule crowd the top. For this product they are the highest
value chunks in the corpus: they carry the dates and the CFR edits.

I first assumed this was a vector-search weakness that Tier B's BM25 lane
would not share. **Measured on the live hot tier, Tier B scored 3/9 and missed
the same chunks.** BM25 does not favour a short DATES paragraph for a
plain-English question either — the question's terms appear throughout the
preamble. The mechanism belongs to the retrieval contract, not to one engine.

## How it selects

The chunker gives an FR document's DATES, summary and amdpar chunks the BARE
citation ("90 FR 4628") and gives every preamble chunk that citation plus a
heading. The DynamoDB `citations` GSI is keyed on exactly that string, so the
bare citation is a precise selector for a document's structural chunks — 2 or
3 ids, not "fetch the document".
"""
import re

from retrieval import fusion
from shared import citations, config
from shared.models import Chunk

_clients: dict = {}


def _registry():
    if "registry" not in _clients:
        import boto3
        _clients["registry"] = boto3.resource(
            "dynamodb", region_name=config.REGION).Table(config.REGISTRY_TABLE)
    return _clients["registry"]


# "21 CFR 74.303(a)(1)" -> "21 CFR 74.303". A chunk's citation_path names the
# paragraph it came from; the document's chunks are filed under the section.
_PARA_SUFFIX_RE = re.compile(r"(?:\([a-z0-9]+\))+\Z", re.ASCII | re.IGNORECASE)


def lookup_citation(cite: str, limit: int) -> list[str]:
    from boto3.dynamodb.conditions import Key
    resp = _registry().query(IndexName="citations",
                             KeyConditionExpression=Key("citation").eq(cite),
                             Limit=limit)
    return [item["chunk_id"] for item in resp.get("Items", [])]


def doc_citation(chunk: Chunk) -> str | None:
    """The citation a document's structural chunks are filed under."""
    if not chunk.citation_path:
        return None
    found = citations.extract_citations(chunk.citation_path)
    if not found:
        return None
    return _PARA_SUFFIX_RE.sub("", found[0]).strip()


def select(query: str, relevance_lane: list[Chunk], k: int) -> list[str]:
    """Chunk ids for the assist lane, in lane order. Two sources:

    1. Citations named IN THE QUERY (SPEC/02's exact-citation assist).
    2. The citations of documents the relevance lane already ranked highly.

    (2) is gated to documents good enough to be ON the page: `k` is the
    candidate width and the router sets it to three times the page size, so
    k//3 is the page size — a derived bound, not a tuned one.

    Gating on "the top N DISTINCT documents" instead was measurably wrong. In
    a 24-long candidate list the third distinct document can sit at rank 20,
    and expanding it lifted the Red No. 3 order's DATES paragraph to rank 4 of
    a question entirely about the "healthy" rule: a confident, correctly-cited
    answer about the wrong regulation.
    """
    ids: list[str] = []
    for cite in dict.fromkeys(citations.extract_citations(query)):
        ids.extend(lookup_citation(cite, k))

    per_doc: list[list[str]] = []
    seen_docs: set[str] = set()
    for chunk in relevance_lane[:max(1, k // 3)]:
        doc = fusion.doc_of(chunk)
        if doc in seen_docs:
            continue
        seen_docs.add(doc)
        if (cite := doc_citation(chunk)) is None:
            continue
        per_doc.append(lookup_citation(cite, config.RETRIEVAL_STRUCTURAL_PER_DOC))
        if len(per_doc) >= config.RETRIEVAL_EXPAND_DOCS:
            break

    # GROUPED by document, in relevance order.
    #
    # Interleaving by position was tried — every document's DATES chunk, then
    # every summary, then every amdpar — on the argument that a DATES paragraph
    # is the highest-value chunk in any FR document, so the second document's
    # dates should outrank the first document's summary. It measured strictly
    # worse: Tier A 9/9 -> 8/9, and on both tiers it simply traded one probe
    # for another (r05 gained, r09 lost), because it moves a document's
    # amendatory instructions from lane position 3 to position 5.
    #
    # That trade is the honest signal here: nine probes cannot distinguish
    # these two orderings, and neither can be justified over the other by
    # anything except the score. Grouped is kept because it is what the higher
    # Tier A measurement used, and the change is recorded so the next person
    # does not re-derive it. See milestones/M02/.
    for doc_ids in per_doc:
        ids.extend(doc_ids)

    return list(dict.fromkeys(ids))[:k]


def restore_order(chunks: list[Chunk], wanted: list[str]) -> list[Chunk]:
    """Put hydrated chunks back into the requested order.

    Neither hydration path promises input order, and RRF scores by rank — so
    an unordered assist lane is noise rather than a ranked list, and the two
    tiers would disagree on the ordering of identical chunks.
    """
    order = {cid: n for n, cid in enumerate(wanted)}
    return sorted(chunks, key=lambda c: order.get(c.chunk_id, len(order)))
