"""Filter semantics — the one place both tiers must agree (SPEC/02, ADR-0006).

These pin behaviour that is invisible in a passing eval run: a filter that
silently matches everything turns a filtered probe into an unfiltered one and
still scores green. The date-attribution rule in particular is a *negative*
claim (the delay notice must NOT come back for a 2028 range), and negative
claims are the ones that rot quietly.
"""
import pytest

from shared.models import Chunk, DateRange, Filters
from shared.validate import ValidationError


def chunk(cid="d#0000", **kw) -> Chunk:
    base = dict(text="t", citation_path="21 CFR 101.65", doc_type="final_rule",
                fr_doc_number="2024-29957", cfr_title="21", cfr_part="101",
                pub_date="2024-12-27", effective_date="2025-04-28",
                compliance_date="2028-02-25")
    base.update(kw)
    return Chunk(chunk_id=cid, **base)


# ------------------------------------------------------------- DateRange
def test_a_document_with_no_such_date_is_never_in_range():
    """ADR-0006, expressed as one assertion.

    The reflex implementation — "no value, no constraint" — returns True here
    and makes a 2028 compliance filter return the delay notice, which asserts
    that the DELAY is what makes 2028 operative. That is the exact conflation
    q01 exists to trap, manufactured by the filter itself.
    """
    assert DateRange(gte="2028-01-01", lte="2028-12-31").contains(None) is False


@pytest.mark.parametrize("value,expected", [
    ("2027-12-31", False),
    ("2028-01-01", True),      # inclusive lower bound
    ("2028-02-25", True),
    ("2028-12-31", True),      # inclusive upper bound
    ("2029-01-01", False),
])
def test_range_bounds_are_inclusive(value, expected):
    assert DateRange(gte="2028-01-01", lte="2028-12-31").contains(value) is expected


def test_open_ended_ranges():
    assert DateRange(gte="2026-01-01").contains("2030-01-01") is True
    assert DateRange(lte="2026-01-01").contains("2030-01-01") is False


# --------------------------------------------------------- Filters.matches
def test_the_probe_pair_in_one_test():
    """r02 negative / r03 positive, at the filter level.

    2024-29957 sets 2028-02-25 and must match a 2028 compliance range.
    2025-03118 sets no compliance date and must not — while remaining
    reachable unfiltered, which is what makes SPEC/02's "this is not a recall
    loss" an assertion rather than a claim.
    """
    f = Filters.from_dict({"compliance_date": {"gte": "2028-01-01",
                                               "lte": "2028-12-31"}})
    final_rule = chunk("2024-29957#0000")
    delay_notice = chunk("2025-03118#0003", fr_doc_number="2025-03118",
                         doc_type="delay_notice", compliance_date=None,
                         effective_date="2025-04-28")
    assert f.matches(final_rule) is True
    assert f.matches(delay_notice) is False
    assert Filters().matches(delay_notice) is True


def test_keyword_filters_are_exact():
    f = Filters.from_dict({"cfr_title": "21", "cfr_part": "101"})
    assert f.matches(chunk()) is True
    assert f.matches(chunk(cfr_part="74")) is False
    assert f.matches(chunk(cfr_part=None)) is False


def test_doc_type_filter_matches_the_enum_value():
    assert Filters.from_dict({"doc_type": "order"}).matches(
        chunk(doc_type="order")) is True
    assert Filters.from_dict({"doc_type": "order"}).matches(
        chunk(doc_type="final_rule")) is False


# ------------------------------------------------------------- strictness
def test_an_unknown_filter_field_raises_rather_than_being_ignored():
    """A dropped filter key is the silent failure this whole file guards.

    The probe would run unfiltered, return whatever it returns, and pass —
    reporting coverage of a filter path that never executed. Same class as
    the out-of-enum doc_type from M01c MEDIUM-1.
    """
    with pytest.raises(ValidationError, match="unknown filter field"):
        Filters.from_dict({"complianceDate": {"gte": "2028-01-01"}})


def test_out_of_enum_doc_type_raises():
    with pytest.raises(ValidationError):
        Filters.from_dict({"doc_type": "finalrule"})


def test_malformed_and_inverted_dates_raise():
    with pytest.raises(ValidationError):
        Filters.from_dict({"compliance_date": {"gte": "Feb 25, 2028"}})
    with pytest.raises(ValidationError, match="inverted"):
        Filters.from_dict({"compliance_date": {"gte": "2028-12-31",
                                               "lte": "2028-01-01"}})
    with pytest.raises(ValidationError, match="no bounds"):
        Filters.from_dict({"compliance_date": {}})
    with pytest.raises(ValidationError, match="unsupported bound"):
        Filters.from_dict({"compliance_date": {"before": "2028-01-01"}})


def test_empty_and_null_filters_are_the_unfiltered_case():
    assert Filters.from_dict(None).is_empty()
    assert Filters.from_dict({}).is_empty()


# ------------------------------------------- the probe file parses as filters
def test_every_probe_filter_in_the_truth_file_is_valid():
    """The probe set is data, and data with a typo in it is a green run.

    Parsing every `filters` object here means a bad probe fails in CI rather
    than degrading a live run into an unfiltered one.
    """
    import json
    from pathlib import Path
    truth = json.loads((Path(__file__).parent.parent / "evals"
                        / "retrieval_truth.json").read_text(encoding="utf-8"))
    for probe in truth["probes"]:
        Filters.from_dict(probe.get("filters"))       # must not raise
