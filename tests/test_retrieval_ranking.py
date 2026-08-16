"""Ranking mechanisms: fusion, page diversity, structural expansion.

These exist because the first live measurement of Tier A scored recall@8 =
0.5, and the four changes that took it to 1.0 are all ranking policy — the
kind of code that has no obviously-wrong state. A regression here does not
raise; it returns eight plausible chunks that omit the deadline.

The CONSTANTS these mechanisms use are not pinned here. The probe set could
not robustly determine the per-document cap (3 and 5 pass, 4 fails — see
shared/config.py), so a unit test asserting a particular value would be
dressing a fitted number as a specification. What is pinned is the behaviour
each mechanism must have at whatever value is configured.
"""
import pytest

from retrieval import fusion
from shared.models import Chunk


def mk(cid, **kw) -> Chunk:
    base = dict(text="t", citation_path="90 FR 4628", doc_type="order",
                fr_doc_number="2025-00830", cfr_title="21", cfr_part="74",
                pub_date="2025-01-16", effective_date="2027-01-15",
                compliance_date=None)
    base.update(kw)
    return Chunk(chunk_id=cid, **base)


# ------------------------------------------------------------------- RRF
def test_a_chunk_found_by_two_lanes_outranks_one_found_by_one():
    a = [mk("d1#0000"), mk("d2#0000")]
    b = [mk("d2#0000"), mk("d3#0000")]
    got = [c.chunk_id for c in fusion.rrf([a, b], k=3)]
    assert got[0] == "d2#0000"


def test_lane_weights_scale_that_lane_only():
    """The structural lane is a recall device. Weighting exists so it can be
    told apart from a relevance signal — measured as making things worse here,
    but the mechanism has to work for that measurement to mean anything."""
    strong = fusion.rrf([[mk("v#0000")], [mk("a#0000")]], k=2, weights=[1.0, 1.0])
    assert {c.chunk_id for c in strong} == {"v#0000", "a#0000"}
    assert strong[0].score == pytest.approx(strong[1].score)

    weak = fusion.rrf([[mk("v#0000")], [mk("a#0000")]], k=2, weights=[1.0, 0.25])
    assert [c.chunk_id for c in weak] == ["v#0000", "a#0000"]
    assert weak[0].score > weak[1].score


def test_equal_scores_break_ties_deterministically():
    """Two tiers scoring the same chunks equally must order them the same way.
    Left to dict order, criterion 3's Jaccard would measure iteration order."""
    lanes = [[mk("b#0000"), mk("a#0000")], [mk("a#0000"), mk("b#0000")]]
    first = [c.chunk_id for c in fusion.rrf(lanes, k=2)]
    assert first == sorted(first)
    assert first == [c.chunk_id for c in fusion.rrf(lanes, k=2)]


# ------------------------------------------------------------- diversify
def test_one_document_cannot_crowd_out_every_other():
    """The 389-chunk final rule case. Without this, six adjacent preamble
    paragraphs of one rule take six of eight slots and the DATES paragraph
    carrying the deadline never appears."""
    flood = [mk(f"big#{i:04d}") for i in range(10)]
    others = [mk("other1#0000"), mk("other2#0000")]
    got = fusion.diversify(flood + others, per_doc=3, limit=8)
    from collections import Counter
    counts = Counter(fusion.doc_of(c) for c in got)
    assert counts["big"] == 3 + 3      # 3 capped picks, then back-fill
    assert counts["other1"] == 1 and counts["other2"] == 1
    assert [c.chunk_id for c in got[:5]] == [
        "big#0000", "big#0001", "big#0002", "other1#0000", "other2#0000"]


def test_deferred_candidates_backfill_rather_than_shortening_the_page():
    """A cap that returned five results for k=8 would trade one silent failure
    for a worse one: nothing reports a short page."""
    got = fusion.diversify([mk(f"only#{i:04d}") for i in range(10)],
                           per_doc=3, limit=8)
    assert len(got) == 8


def test_diversify_returns_everything_when_there_is_nothing_to_cap():
    got = fusion.diversify([mk("a#0000"), mk("b#0000")], per_doc=3, limit=8)
    assert len(got) == 2


def test_diversify_never_exceeds_the_limit():
    got = fusion.diversify([mk(f"d{i}#0000") for i in range(20)],
                           per_doc=1, limit=8)
    assert len(got) == 8


def test_doc_of_splits_on_the_chunk_id_separator():
    assert fusion.doc_of(mk("2025-00830#0027")) == "2025-00830"
    assert fusion.doc_of(mk("cfr-21-74.303@2025-01-01#0000")) == \
        "cfr-21-74.303@2025-01-01"


# ------------------------------------------------------ structural lane
def test_the_assist_lane_is_ordered_by_selection_not_by_hydration():
    """Neither hydration path promises input order, and RRF scores by rank —
    an unordered assist lane is noise, and the two tiers would disagree about
    identical chunks."""
    from retrieval import expansion
    wanted = ["d#0000", "d#0001", "d#0002"]
    shuffled = [mk("d#0002"), mk("d#0000"), mk("d#0001")]
    assert [c.chunk_id for c in expansion.restore_order(shuffled, wanted)] == wanted


def test_named_citations_lead_the_lane_and_duplicates_collapse():
    """One lane, not two. Merging keeps the lane COUNT independent of whether
    the query happened to contain a citation — otherwise every RRF score in
    the run shifts depending on the query's phrasing."""
    from retrieval import expansion
    named = [mk("cited#0000")]
    structural = [mk("cited#0000"), mk("dates#0000")]
    merged = expansion.merge_lane(named, structural)
    assert [c.chunk_id for c in merged] == ["cited#0000", "dates#0000"]


def test_a_citation_named_in_the_query_is_looked_up(monkeypatch):
    """SPEC/02's exact-citation assist, and the one job left to the GSI:
    `citation_path` is non-filterable in the S3 Vectors index, so an exact
    lookup cannot be pushed into that engine at all."""
    from retrieval import expansion
    looked_up: list[str] = []
    monkeypatch.setattr(expansion, "lookup_citation",
                        lambda cite, limit: looked_up.append(cite) or [])
    expansion.query_citation_ids("what does 21 CFR 101.65(d) require?", 8)
    assert looked_up == ["21 CFR 101.65(d)"]
    assert expansion.query_citation_ids("plain english question", 8) == []


def test_both_tiers_restrict_the_structural_lane_to_the_same_kinds():
    """The two tiers issue the lane natively — S3 Vectors as a $in metadata
    filter, AOSS as a terms clause. If they ever restrict to different kinds
    they rank different populations, and criterion 3's Jaccard reads that as
    retrieval drift rather than as the configuration bug it is."""
    import inspect

    from retrieval import aoss_tier, s3vectors_tier
    for mod in (aoss_tier, s3vectors_tier):
        assert "RETRIEVAL_STRUCTURAL_KINDS" in inspect.getsource(mod), mod.__name__


def test_the_structural_kinds_are_the_operative_paragraphs():
    """dates and amdpar carry the deadlines and the CFR edits. `summary` is
    context, not an operative provision — including it triples the lane
    without adding an answer."""
    from shared import config, models
    assert set(config.RETRIEVAL_STRUCTURAL_KINDS) == {"dates", "amdpar"}
    assert set(config.RETRIEVAL_STRUCTURAL_KINDS) <= models.CHUNK_KINDS


def test_the_structural_query_still_honours_the_callers_filters():
    """The kind restriction is ANDed with the user's filters, not substituted
    for them. A structural lane that ignored the caller's filters would return
    chunks router._finish then discards — burning lane slots that decide RRF
    rank."""
    from retrieval.s3vectors_tier import _metadata_filter
    from shared.models import Filters
    got = _metadata_filter(Filters.from_dict({"doc_type": "order"}),
                           {"kind": {"$in": ["dates", "amdpar"]}})
    assert got == {"$and": [{"doc_type": {"$eq": "order"}},
                            {"kind": {"$in": ["dates", "amdpar"]}}]}


def test_the_structural_restriction_survives_with_no_caller_filters():
    from retrieval.s3vectors_tier import _metadata_filter
    from shared.models import Filters
    assert _metadata_filter(Filters(), {"kind": {"$in": ["dates"]}}) ==         {"kind": {"$in": ["dates"]}}


# ------------------------------------------------ S3 Vectors filter dialect
def test_date_filters_push_down_existence_only():
    """S3 Vectors rejects $gte/$lte on string metadata (verified live; see
    tests/probe_s3v_filter.py). $exists is pushed instead — which is not a
    consolation prize but exactly ADR-0006: a document that establishes no
    compliance date can never satisfy a compliance-date range."""
    from retrieval.s3vectors_tier import _metadata_filter
    from shared.models import Filters
    f = Filters.from_dict({"compliance_date": {"gte": "2028-01-01",
                                               "lte": "2028-12-31"}})
    assert _metadata_filter(f) == {"compliance_date": {"$exists": True}}


def test_keyword_filters_push_down_as_equality():
    from retrieval.s3vectors_tier import _metadata_filter
    from shared.models import Filters
    assert _metadata_filter(Filters.from_dict({"doc_type": "order"})) == \
        {"doc_type": {"$eq": "order"}}
    assert _metadata_filter(Filters.from_dict(
        {"cfr_title": "21", "cfr_part": "74"})) == {
            "$and": [{"cfr_title": {"$eq": "21"}}, {"cfr_part": {"$eq": "74"}}]}
    assert _metadata_filter(Filters()) is None
