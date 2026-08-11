"""Claude rerank of the fused candidate window (SPEC/02 "Optional").

Behind `RERANK=1`, off by default. SPEC/02 pre-registered this before M02's
first measurement and defines the adoption bar under "Optional"; ADR-0009
Ruling 3 defers the non-hybrid-Tier-B question pending that measurement.

WHY IT SITS WHERE IT SITS. The failure this exists to fix is not a lane
failure. `2025-03118#0003` is ranked 6th-7th by kNN and 14th by BM25 — mediocre
on both — so RRF has no signal to promote it, and `fusion.diversify` then hands
2025-03118's three slots to #0000/#0001/#0005 and drops #0003. So the reranker
must score the FUSED CANDIDATE WINDOW, before diversification. Placed after the
per-document cap it would be reading a page from which the chunk it exists to
recover has already been evicted, and a null result would measure the ordering
rather than the reranker. SPEC/02's adoption bar requires each scorecard to
record which side of `diversify` the candidate set came from, precisely so a
null result cannot be misread.

THE INVARIANT, which is what makes this safe to switch on. Reranking may only
REORDER the candidate window; it may never change its membership. Every
candidate handed in comes back out — ids the model omits are appended in their
original relative order, and ids it invents are discarded. So recall over the
candidate set is identical with the flag on and off, and turning the flag on
cannot lose a chunk that the un-reranked path would have returned inside the
window. What it can change is which chunks survive `diversify`, which is the
entire point. `test_rerank.py` pins the invariant directly.

FAIL-OPEN, deliberately. Any failure — a denied model, a malformed response, a
timeout — returns the candidates unchanged rather than raising. Same reasoning
as the AossError fallback in router.py: a degraded ranking beats a 500, and the
un-reranked order is a correct answer, just a worse-ordered one. The reason is
carried out on the Resolution rather than logged and dropped, so a scorecard
cannot record a reranked run that silently was not one.
"""
import json

from shared import config
from shared.models import Chunk

# Fixed at 20 by SPEC/02 ("Claude rerank of top-20 -> top-k"), not tuned here.
# The window is a spec value; changing it is a spec edit.
WINDOW = 20

# The reranker reads text, so the window has to carry text — but a full 389-chunk
# preamble document would blow the prompt. 1200 chars is enough to see what a
# paragraph asserts; #0003's "the compliance date remains unchanged at this
# time" sits in the first sentence of its chunk.
_SNIPPET = 1200

_PROMPT = """You are ranking retrieved passages from US federal regulatory
documents (Federal Register rules and notices, and the Code of Federal
Regulations) by how well each one helps answer a question.

Question: {query}

Passages, each with an id:
{passages}

Rank ALL {n} passage ids from most to least useful for answering that exact
question. Judge only what a passage actually states — a passage that asserts
the specific fact the question asks about outranks one that is merely about the
same topic, and a passage about a different product class or a different
regulation is least useful even when it repeats the question's wording.

Reply with only a JSON array of the ids, most useful first, no other text:
["<id>", "<id>", ...]
"""


def _client():
    # Imported lazily and built per call site the same way the tiers do it, so
    # importing this module never requires credentials.
    from retrieval.s3vectors_tier import _client as shared_client
    return shared_client("bedrock-runtime")


def _invoke(prompt: str) -> str:
    # Converse, matching baseline/naive.py and processor.py. MODEL_FAST, not a
    # new constant: config.py records that this account gets
    # AccessDeniedException with agreementAvailability=NOT_AVAILABLE for Opus
    # 4.7/4.8, Sonnet 5, Opus 5, Fable 5 and Haiku 4.5, so a "better" model id
    # here would fail at invoke time and read as the reranker not helping.
    # Ranking 20 short passages is a MODEL_FAST-shaped task anyway.
    resp = _client().converse(
        modelId=config.MODEL_FAST,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1000, "temperature": 0})
    blocks = resp["output"]["message"]["content"]
    return next((b["text"] for b in blocks if "text" in b), "")


def _parse_order(text: str, known: set[str]) -> list[str]:
    """Ranked ids from the model's reply, filtered to ids we actually sent.

    Tolerates prose around the array — the instruction says JSON only, and a
    model that adds a sentence anyway should not cost us the ranking. Anything
    that is not a recognisable array of known ids yields [], which the caller
    treats as "no ranking" and falls open.
    """
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    seen, order = set(), []
    for item in raw:
        # Invented ids are dropped rather than trusted: a hallucinated chunk id
        # must never reach a citation.
        if isinstance(item, str) and item in known and item not in seen:
            seen.add(item)
            order.append(item)
    return order


def rerank(query: str, candidates: list[Chunk],
           invoke=None) -> tuple[list[Chunk], str]:
    """Reorder the candidate window. Returns (chunks, note) — never raises.

    `note` records what actually happened, for the scorecard: a run recorded as
    reranked must be able to prove the reranker ran.
    """
    if not config.RERANK:
        return candidates, "off"
    window = candidates[:WINDOW]
    if len(window) < 2:
        return candidates, f"skipped: {len(window)} candidate(s)"

    by_id = {c.chunk_id: c for c in window}
    passages = "\n\n".join(
        f"id: {c.chunk_id}\n{(c.text or '')[:_SNIPPET]}" for c in window)
    prompt = _PROMPT.format(query=query, passages=passages, n=len(window))

    try:
        text = (invoke or _invoke)(prompt)
    except Exception as e:  # noqa: BLE001 — fail-open is the whole contract
        return candidates, f"failed, order unchanged: {type(e).__name__}: {e}"

    order = _parse_order(text, set(by_id))
    if not order:
        return candidates, "unparseable reply, order unchanged"

    # THE INVARIANT. Ranked ids first, then every id the model left out, in
    # their original relative order. Membership is preserved by construction —
    # not by a check that could be removed — and the tail beyond the window is
    # appended untouched.
    ranked = [by_id[cid] for cid in order]
    ranked += [c for c in window if c.chunk_id not in set(order)]
    out = ranked + candidates[WINDOW:]

    assert {c.chunk_id for c in out} == {c.chunk_id for c in candidates}, (
        "rerank changed candidate membership")
    return out, f"reranked {len(order)}/{len(window)} before diversify"
