"""Both tiers must push EVERY filter field into their engine.

This is the regression `7d65a07`'s successor fixed and that engineering review
found was protected by nothing: skipping `kind` in either tier's pushdown builder
left all 386 other tests green. `kind` had already drifted once — it is in
`models.KEYWORD_FIELDS` and `Filters.matches` enforces it, but Tier B's clause
builder predated it and pushed no `kind` clause, so Tier B filled its candidate
slots with non-matching chunks that `router._finish` then discarded. The result is
a short page on one tier and a full page on the other: the silent cross-tier
divergence the shared-field-list design exists to make unrepresentable.

No probe filters on `kind`, so no scorecard catches this. These tests are the only
thing that does, which is why they assert over `KEYWORD_FIELDS` itself rather than
naming fields — a field added to the contract and forgotten in a builder fails
here without anyone remembering to extend the test.
"""
import json

from shared import models
from shared.models import DateRange, Filters


def every_field_populated() -> Filters:
    """A Filters with every contract field set, so a dropped field is visible.

    Built from the shared field lists for the same reason the builders iterate
    them: hand-listing is how `kind` went missing in the first place.
    """
    kwargs: dict = {}
    for key in models.KEYWORD_FIELDS:
        kwargs[key] = {"cfr_title": "21", "cfr_part": "101",
                       "doc_type": "final_rule",
                       "fr_doc_number": "2025-03118",
                       "kind": "dates"}.get(key, "x")
    for key in models.DATE_FIELDS:
        kwargs[key] = DateRange(gte="2025-01-01", lte="2025-12-31")
    return Filters(**kwargs)


def test_tier_b_pushes_every_keyword_and_date_field(monkeypatch):
    """Tier B: OpenSearch bool/filter clauses."""
    from retrieval import aoss_tier

    clauses = aoss_tier._filter_clauses(every_field_populated())
    rendered = json.dumps(clauses)
    for key in (*models.KEYWORD_FIELDS, *models.DATE_FIELDS):
        assert f'"{key}"' in rendered, (
            f"Tier B pushed no clause for {key!r}. Filters.matches still "
            "enforces it client-side, so the symptom is not a wrong answer — it "
            "is Tier B's candidate slots filled with chunks router._finish then "
            "discards, i.e. a short page on this tier and a full one on Tier A")
    assert len(clauses) == len(models.KEYWORD_FIELDS) + len(models.DATE_FIELDS)


def test_tier_a_pushes_every_keyword_and_date_field():
    """Tier A: S3 Vectors metadata filter, a different dialect, same contract.

    Asserted separately rather than by comparing the two dialects: the point is
    that each engine receives every field, and a test that only checked the two
    agreed would pass if both dropped the same one.
    """
    from retrieval import s3vectors_tier

    rendered = json.dumps(
        s3vectors_tier._metadata_filter(every_field_populated()))
    for key in (*models.KEYWORD_FIELDS, *models.DATE_FIELDS):
        assert f'"{key}"' in rendered, f"Tier A pushed no clause for {key!r}"


def test_an_unset_field_is_not_pushed_by_either_tier():
    """The complement, so the tests above cannot be satisfied by emitting
    everything unconditionally — which would make a narrow filter match nothing
    and turn a recall failure into a filter bug."""
    from retrieval import aoss_tier, s3vectors_tier

    only_one = Filters(cfr_part="101")
    b = json.dumps(aoss_tier._filter_clauses(only_one))
    a = json.dumps(s3vectors_tier._metadata_filter(only_one))
    for rendered, tier in ((a, "Tier A"), (b, "Tier B")):
        assert '"cfr_part"' in rendered, tier
        for key in ("kind", "doc_type", "fr_doc_number", "cfr_title"):
            assert f'"{key}"' not in rendered, f"{tier} pushed unset {key!r}"
