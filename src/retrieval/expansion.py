"""The structural lane — shared vocabulary for both tiers (SPEC/02).

## What it is

A second search, run against the chunks the chunker labelled as stating what a
document DOES: its DATES block and its amendatory instructions
(`config.RETRIEVAL_STRUCTURAL_KINDS`). Each tier issues it natively — S3
Vectors as a `kind`-filtered QueryVectors, AOSS as a `kind`-filtered kNN — so
both rank the same population by the same signal, embedding similarity to the
query.

## Why a separate lane at all

Measured on the live corpus, Tier A scored recall@8 = 0.50 and every miss was
a DATES or amendatory-instructions paragraph belonging to a document the
relevance lane had already ranked FIRST, at global ranks 12 to 46. Those
paragraphs are short formulaic legalese — "DATES: This order is effective
January 15, 2027, except for amendatory instruction 4…" — and they sit far
from a natural-language question while six adjacent preamble paragraphs of the
same 389-chunk rule crowd the top. Tier B, measured later on the hot tier,
scored 3/9 and missed the same chunks: BM25 does not favour a short DATES
paragraph either, because the question's terms appear throughout the preamble.

Restricting the search to structural chunks removes the competition. Ranking
28 DATES paragraphs against each other asks a question embeddings answer well
— *which* deadline is this about — instead of asking them to beat prose that
shares the query's vocabulary.

## What this replaces

The first version reconstructed "which paragraphs state what this document
does" from the DynamoDB `citations` GSI: take the top documents from the
relevance lane, derive each one's bare citation, and look up the chunks filed
under it. It worked, and it was a workaround for a field that already existed.
The chunker has labelled every chunk `dates | summary | amdpar | preamble |
regtext` since M01 and it is in every line of `corpus/chunks/**/*.jsonl`;
neither index writer copied it. Indexing it deleted the document-selection
heuristic, its window bound, its ordering question (grouped vs interleaved —
which measurably traded one probe for another and could not be settled), and
roughly eighty lines.

The GSI keeps one job, below: resolving a citation the USER named.
"""
from shared import citations, config
from shared.models import Chunk

_clients: dict = {}


def _registry():
    if "registry" not in _clients:
        import boto3
        _clients["registry"] = boto3.resource(
            "dynamodb", region_name=config.REGION).Table(config.REGISTRY_TABLE)
    return _clients["registry"]


def lookup_citation(cite: str, limit: int) -> list[str]:
    from boto3.dynamodb.conditions import Key
    resp = _registry().query(IndexName="citations",
                             KeyConditionExpression=Key("citation").eq(cite),
                             Limit=limit)
    return [item["chunk_id"] for item in resp.get("Items", [])]


def query_citation_ids(query: str, limit: int) -> list[str]:
    """Chunk ids for citations the QUERY names (SPEC/02's exact-citation assist).

    Still the GSI rather than a metadata filter: `citation_path` is one of the
    two non-filterable keys in the S3 Vectors index (fixed at index creation),
    so an exact-citation lookup cannot be pushed into that engine at all.

    Unconditional, and not gated behind the structural lane: a query naming
    "21 CFR 101.65(d)" is asking for that section whatever else scored well.
    """
    ids: list[str] = []
    for cite in dict.fromkeys(citations.extract_citations(query)):
        ids.extend(lookup_citation(cite, limit))
    return list(dict.fromkeys(ids))[:limit]


def documents_in_play(relevance_lane: list[Chunk], page: int) -> list[str]:
    """The FR documents the query is about, from the relevance lane's top page.

    The structural lane is scoped to these. Unscoped, it ranks all 31 DATES
    paragraphs in the corpus and happily returns the most query-similar ones
    from documents the query has nothing to do with — measured: Tier A 9/9 ->
    8/9, losing a probe whose answer is a preamble sentence that got crowded
    off the page by other rules' deadlines.

    `fr_doc_number` identifies these documents completely, because structural
    chunks are FR-only: `dates` and `amdpar` come from parsing a Federal
    Register document, and an eCFR snapshot produces `regtext`. So there is no
    CFR case to handle here, and no need for the document id that S3 Vectors
    has no filterable slot left for.

    Scoped to the top PAGE of the relevance lane rather than a tuned document
    count — a document good enough to be on the page is good enough for its
    operative paragraphs to be candidates.
    """
    seen: list[str] = []
    for chunk in relevance_lane[:page]:
        if chunk.fr_doc_number and chunk.fr_doc_number not in seen:
            seen.append(chunk.fr_doc_number)
    return seen


def restore_order(chunks: list[Chunk], wanted: list[str]) -> list[Chunk]:
    """Put hydrated chunks back into the requested order.

    Neither hydration path promises input order, and RRF scores by rank — so
    an unordered lane is noise rather than a ranked list, and the two tiers
    would disagree about identical chunks.
    """
    order = {cid: n for n, cid in enumerate(wanted)}
    return sorted(chunks, key=lambda c: order.get(c.chunk_id, len(order)))


def merge_lane(named: list[Chunk], structural: list[Chunk]) -> list[Chunk]:
    """One assist lane: citations the user named, then structural chunks.

    Named citations lead because the user asked for them by name. Merged into
    a single lane rather than fused as a third, so the number of lanes — and
    therefore every RRF score — does not depend on whether the query happened
    to contain a citation.
    """
    seen: set[str] = set()
    out: list[Chunk] = []
    for chunk in [*named, *structural]:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            out.append(chunk)
    return out
