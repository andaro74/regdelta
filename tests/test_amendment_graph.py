"""The amendment graph's read side (SPEC/03), tested at its semantics.

These tests were derived from the golden-question contracts rather than from
the implementation, because the questions are what the module owes. Each test
names the question it stands under. The three that matter most:

- **q11** a stay suspends without tolling, and a CONFIRMS edge moves nothing.
  The failure this prevents is a timeline agent that reads the freshest edge
  and reports a deadline that moved.
- **q12** a question about the past must be answered from what the corpus knew
  then, not from hindsight.
- **q19** a repeal sets no compliance date (ADR-0006), so the real deadline is
  derived from the effective date and must SAY it was derived.

The fixture is shaped after the live corpus and its verified values are the
ones quoted in evals/retrieval_truth.json and the regulatory-domain skill.
One value is illustrative rather than sourced — the healthy rule's ORIGINAL
effective date (2025-02-25), which the corpus records but no repo file quotes.
Nothing here asserts it as ground truth; it exists so supersession has
something to supersede.
"""
import pytest
from conftest import FIXTURES  # noqa: F401  (path setup)

from graph import amendment_graph as ag

HEALTHY = "2024-29957"      # 89 FR 106064, pub 2024-12-27
DELAY = "2025-03118"        # 90 FR 10592,  pub 2025-02-25
RED3 = "2025-00830"         # 90 FR 4628,   pub 2025-01-16
LIFT = "2026-15920"         # 91 FR 50475,  pub 2026-08-05


def _meta(doc, *, citation, pub, effective=(), compliance=(), binding=True):
    import json
    return {
        "pk": f"DOC#{doc}", "sk": "META", "citation": citation, "pub_date": pub,
        "title": f"test META for {doc}", "doc_type": "rule", "binding": binding,
        "effective_dates": json.dumps(list(effective)),
        "compliance_dates": json.dumps(list(compliance)),
        "amendatory_instructions": json.dumps([]),
    }


def _edge(citing, target, predicate, scope, **attrs):
    return {"pk": f"DOC#{citing}", "sk": f"{predicate}#{target}#{scope}",
            "predicate": predicate, "scope": scope, "target_doc": target,
            "target_raw": target, **attrs}


def _stay(stayed, start, source, **attrs):
    return {"pk": f"DOC#{stayed}", "sk": f"STAY_PERIOD#{start}#{source}",
            "start": start, "source_doc": source, "dates_changed": False, **attrs}


def _corpus():
    """The four real documents, with the edges processor.py would write."""
    return [
        _meta(HEALTHY, citation="89 FR 106064", pub="2024-12-27",
              effective=[{"date": "2025-02-25", "applies_to": ""}],
              compliance=[{"date": "2028-02-25", "applies_to": ""}]),
        _meta(DELAY, citation="90 FR 10592", pub="2025-02-25",
              effective=[{"date": "2025-04-28",
                          "applies_to": "Federal Register effective_on for this document"}]),
        _meta(RED3, citation="90 FR 4628", pub="2025-01-16",
              effective=[{"date": "2027-01-15", "applies_to": "food; 21 CFR 74.303"},
                         {"date": "2028-01-18",
                          "applies_to": "ingested drugs; 21 CFR 74.1303"}]),
        _meta(LIFT, citation="91 FR 50475", pub="2026-08-05"),
        # The delay moves the healthy rule's EFFECTIVE date and expressly
        # leaves its compliance date alone — "the compliance date remains
        # unchanged at this time" (chunk 2025-03118#0003).
        _edge(DELAY, HEALTHY, "SUPERSEDES", "effective_date", new_date="2025-04-28"),
        _edge(DELAY, HEALTHY, "CONFIRMS", "dates_confirmed"),
        # The lift confirms both Red No. 3 dates and changes neither.
        _edge(LIFT, RED3, "LIFTS_STAY", "stay_lifted"),
        _edge(LIFT, RED3, "CONFIRMS", "dates_confirmed"),
        _stay(RED3, "2025-02-18", LIFT, end="2026-08-05",
              authority="21 U.S.C. 371(e)(2)"),
    ]


class _FakeRegistry:
    """Registry stand-in. Same trick as tests/test_ingestion_wiring.py — read
    the rendered condition rather than modelling boto3's condition tree."""

    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): i for i in items}
        self.scans = 0

    def get_item(self, Key):
        hit = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": hit} if hit else {}

    def query(self, KeyConditionExpression=None, **_kw):
        eq, begins = KeyConditionExpression._values
        pk, prefix = eq._values[1], begins._values[1]
        return {"Items": [i for (p, s), i in self.items.items()
                          if p == pk and s.startswith(prefix)]}

    def scan(self, FilterExpression=None, **_kw):
        self.scans += 1
        name, want = FilterExpression._values[0].name, FilterExpression._values[1]
        return {"Items": [i for i in self.items.values() if i.get(name) == want]}


@pytest.fixture
def registry():
    return _FakeRegistry(_corpus())


@pytest.fixture
def red3(registry):
    return ag.load(RED3, table=registry)


@pytest.fixture
def healthy(registry):
    return ag.load(HEALTHY, table=registry)


# ---------------------------------------------------------------- load()
def test_load_raises_for_a_document_not_in_the_corpus(registry):
    """"We hold nothing about this" is not "this establishes no dates".

    q16 depends on the difference: the honest answer to a question about a
    rule outside the corpus is that there is no source, and a caller handed an
    empty timeline would instead answer confidently from nothing.
    """
    with pytest.raises(ag.DocumentNotFoundError):
        ag.load("2099-00001", table=registry)


def test_load_finds_inbound_edges_and_dates_the_citing_documents(healthy):
    """Edges are keyed by the CITING document, so inbound needs the scan."""
    assert {(e.citing_doc, e.predicate, e.scope) for e in healthy.inbound} == {
        (DELAY, "SUPERSEDES", "effective_date"),
        (DELAY, "CONFIRMS", "dates_confirmed"),
    }
    assert all(e.citing_pub_date == "2025-02-25" for e in healthy.inbound)


def test_the_stay_is_read_from_the_stayed_documents_partition(red3):
    """processor._write_stay_period writes cross-partition precisely so that
    one query on the stayed document finds it."""
    assert len(red3.stays) == 1
    stay = red3.stays[0]
    assert (stay.start, stay.end) == ("2025-02-18", "2026-08-05")
    assert stay.authority == "21 U.S.C. 371(e)(2)"
    assert stay.sources == (LIFT,)


# ------------------------------------------------- ADR-0007: inert predicates
def test_confirms_does_not_move_the_compliance_date(healthy):
    """q01/q17. The delay notice confirms the compliance date; a consumer
    applying "most recent edge wins" without checking the predicate would
    report it moved."""
    compliance = ag.resolve(healthy, "compliance")
    assert [r.date for r in compliance] == ["2028-02-25"]
    assert compliance[0].source_doc == HEALTHY


def test_supersedes_with_a_date_scope_does_move_the_date(healthy):
    """The control for the test above: the mechanism works, so the test above
    is measuring the predicate check and not a resolver that never fires."""
    effective = ag.resolve(healthy, "effective")
    assert [r.date for r in effective] == ["2025-04-28"]
    assert effective[0].source_doc == DELAY
    assert effective[0].superseded == ("2025-02-25 (2024-29957)",)


@pytest.mark.parametrize("predicate,scope", [
    ("CONFIRMS", "compliance_date"),     # only the predicate check catches this
    ("SUPERSEDES", "dates_confirmed"),   # only the scope check catches this
    ("LIFTS_STAY", "compliance_date"),
])
def test_an_inert_edge_carrying_a_date_still_moves_nothing(healthy, predicate, scope):
    """Both guards pinned independently, with a hostile item.

    The test above passes even with the predicate check deleted, because its
    CONFIRMS edge carries no `new_date` — so on its own it measures the
    absence of a date rather than the rule. These items carry one. The
    scenario is not hypothetical: ADR-0007 exists because the pipeline
    recorded `DOC#2026-15920 SUPERSEDES#2025-00830 scope=effective_date` for
    a document that confirmed dates rather than changing them, and a reader
    applying "most recent edge wins" would have moved a deadline on it.
    """
    from dataclasses import replace
    hostile = replace(healthy, inbound=(
        ag.Edge(citing_doc=DELAY, target_doc=HEALTHY, predicate=predicate,
                scope=scope, new_date="2029-01-01", citing_pub_date="2025-02-25"),
    ))
    assert [r.date for r in ag.resolve(hostile, "compliance")] == ["2028-02-25"]
    assert ag.operative_deadline(hostile).date == "2028-02-25"


def test_lifting_a_stay_and_confirming_dates_leaves_the_deadline_alone(red3):
    """q11. Both edges on Red No. 3 are inert, so the date the order set is
    still the date the order set."""
    assert [r.date for r in ag.resolve(red3, "effective")] == \
        ["2027-01-15", "2028-01-18"]
    assert all(r.source_doc == RED3 for r in ag.resolve(red3, "effective"))


def test_a_stay_never_shortens_or_extends_a_deadline(red3):
    """q11, stated as the property rather than the example: removing the stay
    entirely must not change any resolved date. A suspension is not a
    day-for-day extension — 21 U.S.C. 371(e)(2) has no tolling."""
    from dataclasses import replace
    without = replace(red3, stays=())
    assert ag.resolve(red3, "effective") == ag.resolve(without, "effective")
    assert ag.operative_deadline(red3) == ag.operative_deadline(without)


# --------------------------------------------------- ADR-0006: derived dates
def test_a_repeal_with_no_compliance_date_derives_one_and_says_so(red3):
    """q19. The supplier's premise is true and the conclusion is wrong: the
    order sets no compliance date, and the effective date is still the real
    deadline."""
    assert ag.resolve(red3, "compliance") == ()
    deadline = ag.operative_deadline(red3)
    assert deadline.date == "2027-01-15"
    assert deadline.kind == "derived-from-effective"
    assert deadline.stated is False
    assert "sets no compliance date" in deadline.basis


def test_a_stated_compliance_date_is_not_relabelled_as_derived(healthy):
    """The other side of the same rule — a real compliance date stays one."""
    deadline = ag.operative_deadline(healthy)
    assert (deadline.date, deadline.kind) == ("2028-02-25", "compliance")
    assert deadline.stated is True


def test_multiple_effective_dates_keep_what_each_applies_to(red3):
    """q13. The order changes two provisions on two days, and the difference
    between them is the food/drug split — which lives in applies_to."""
    by_date = {r.date: r.applies_to for r in ag.resolve(red3, "effective")}
    assert "74.303" in by_date["2027-01-15"]
    assert "74.1303" in by_date["2028-01-18"]
    assert ag.operative_deadline(red3).applies_to == by_date["2027-01-15"]


# ------------------------------------------------------- stays: the interval
def test_containment_is_start_inclusive_and_end_exclusive():
    """The stay is in force on the day it begins and lifted on the day it is
    lifted. Flagged in the module docstring as read rather than quoted."""
    stay = ag.StayInterval(start="2025-02-18", end="2026-08-05")
    assert stay.contains("2025-02-18")
    assert stay.contains("2026-08-04")
    assert not stay.contains("2026-08-05")
    assert not stay.contains("2025-02-17")


def test_an_open_ended_stay_contains_everything_after_its_start():
    stay = ag.StayInterval(start="2025-02-18")
    assert stay.open_ended
    assert stay.contains("2099-01-01")


def test_two_documents_describing_one_stay_merge_into_one_interval():
    """The instruction processor._write_stay_period leaves for its consumer:
    "Consumers must MERGE multiple STAY_PERIOD# items rather than assume one."
    The sort key is namespaced by the asserting document so both survive."""
    merged = ag.merge_stays([
        _stay(RED3, "2025-02-18", "2026-00001", authority="21 U.S.C. 371(e)(2)"),
        _stay(RED3, "2025-02-18", LIFT, end="2026-08-05"),
    ])
    assert len(merged) == 1
    assert (merged[0].start, merged[0].end) == ("2025-02-18", "2026-08-05")
    assert set(merged[0].sources) == {"2026-00001", LIFT}


def test_the_merge_keeps_the_end_whichever_order_the_items_arrive_in():
    """The specific regression processor.py records having shipped: it kept
    `end` only because `stay_lifted` happened to be emitted last, and
    reversed, the graph would report Red No. 3 as still stayed today.
    """
    items = [_stay(RED3, "2025-02-18", LIFT, end="2026-08-05"),
             _stay(RED3, "2025-02-18", "2026-00001")]
    assert ag.merge_stays(items)[0].end == "2026-08-05"
    assert ag.merge_stays(list(reversed(items)))[0].end == "2026-08-05"


def test_conflicting_end_dates_raise_rather_than_pick_one():
    """The failure mode is not symmetric. Guessing wrong here reads as a live
    suspension, which is the most consequential single fact this graph holds,
    so the module refuses instead of taking last-write-wins."""
    with pytest.raises(ag.AmbiguousTimelineError, match="conflicting end dates"):
        ag.merge_stays([
            _stay(RED3, "2025-02-18", LIFT, end="2026-08-05"),
            _stay(RED3, "2025-02-18", "2026-00001", end="2027-01-01"),
        ])


def test_stay_on_finds_the_covering_interval_and_returns_none_outside_it(red3):
    assert ag.stay_on(red3, "2025-06-01").start == "2025-02-18"
    assert ag.stay_on(red3, "2026-12-01") is None


# -------------------------------------------------------- q12: point in time
def test_a_stay_documented_only_in_hindsight_is_not_reported_as_known(red3):
    """q12, and the sharpest rule in the module. The Red No. 3 stay arose by
    operation of law and was never separately published — it is knowable only
    from the order that lifts it, published 2026-08-05. So on 2025-06-01 the
    corpus could not have told you the order was suspended, even though we now
    know it was. Reporting it as known then would make the system look more
    certain about the past than it ever was."""
    then = ag.as_of(red3, "2025-06-01")
    assert then.stay is None
    assert then.stayed is False
    assert then.retrospective_stay is not None
    assert then.retrospective_stay.start == "2025-02-18"


def test_a_knowable_stay_reads_as_open_ended_before_its_lift_is_published():
    """The tri-state the domain skill requires: not "the deadline moved" and
    not "there is no deadline", but "the stated date is X and it is currently
    unconfirmed". A stay whose start was published while it ran, but whose end
    was not yet, must not borrow the end from the future."""
    timeline = ag.DocTimeline(
        doc_number=RED3, pub_date="2025-01-16",
        effective_dates=({"date": "2027-01-15", "applies_to": "food"},),
        stays=(ag.StayInterval(start="2025-02-18", end="2026-08-05",
                               sources=("2025-09999", LIFT),
                               known_from="2025-02-20",
                               end_known_from="2026-08-05"),),
    )
    then = ag.as_of(timeline, "2025-06-01")
    assert then.stayed is True
    assert then.stay.open_ended            # the end is not yet knowable
    assert then.confirmable is False       # so the date is stated but unconfirmed
    assert [r.date for r in then.effective] == ["2027-01-15"]


def test_after_the_lift_nothing_is_stayed_and_the_date_stands(red3):
    """q11's "what is the position now" half."""
    now = ag.as_of(red3, "2026-09-01")
    assert now.stay is None and now.retrospective_stay is None
    assert now.confirmable is True
    assert [r.date for r in now.effective] == ["2027-01-15", "2028-01-18"]


def test_a_question_about_the_past_does_not_use_a_later_delay(healthy):
    """The edge half of as_of. On 2025-01-01 the delay had not published, so
    the effective date then was the original — answering with 2025-04-28 would
    be hindsight presented as contemporaneous fact."""
    assert [r.date for r in ag.as_of(healthy, "2025-01-01").effective] == ["2025-02-25"]
    assert [r.date for r in ag.as_of(healthy, "2025-06-01").effective] == ["2025-04-28"]


def test_nothing_is_known_about_a_document_before_it_published(red3):
    """Not "no dates" — no knowledge. The distinction is the same one
    DocumentNotFoundError draws, at a different point in time."""
    assert ag.as_of(red3, "2025-01-01").effective == ()
    assert ag.operative_deadline(red3, as_of="2025-01-01") is None


# ------------------------------------------------------------- ambiguity
def test_two_documents_published_the_same_day_disagreeing_raises():
    """No publication order between them means no basis to prefer either."""
    timeline = ag.DocTimeline(
        doc_number=HEALTHY, pub_date="2024-12-27",
        effective_dates=({"date": "2025-02-25", "applies_to": ""},),
        inbound=(
            ag.Edge(citing_doc="a", target_doc=HEALTHY, predicate="SUPERSEDES",
                    scope="effective_date", new_date="2025-04-28",
                    citing_pub_date="2025-02-25"),
            ag.Edge(citing_doc="b", target_doc=HEALTHY, predicate="SUPERSEDES",
                    scope="effective_date", new_date="2025-05-30",
                    citing_pub_date="2025-02-25"),
        ),
    )
    with pytest.raises(ag.AmbiguousTimelineError, match="same day"):
        ag.resolve(timeline, "effective")


def test_the_later_document_wins_when_publication_order_settles_it():
    """The control for the test above."""
    timeline = ag.DocTimeline(
        doc_number=HEALTHY, pub_date="2024-12-27",
        effective_dates=({"date": "2025-02-25", "applies_to": ""},),
        inbound=(
            ag.Edge(citing_doc="a", target_doc=HEALTHY, predicate="SUPERSEDES",
                    scope="effective_date", new_date="2025-04-28",
                    citing_pub_date="2025-02-25"),
            ag.Edge(citing_doc="b", target_doc=HEALTHY, predicate="SUPERSEDES",
                    scope="effective_date", new_date="2025-05-30",
                    citing_pub_date="2025-03-30"),
        ),
    )
    resolved = ag.resolve(timeline, "effective")
    assert (resolved[0].date, resolved[0].source_doc) == ("2025-05-30", "b")
    assert resolved[0].superseded == ("2025-02-25 (2024-29957)", "2025-04-28 (a)")


def test_moving_one_of_several_dates_raises_rather_than_guessing(red3):
    """Red No. 3 states two effective dates. A document moving "the" effective
    date gives no machine-checkable way to say which, because applies_to is
    free-form prose — so matching it would be a guess dressed as a lookup."""
    from dataclasses import replace
    ambiguous = replace(red3, inbound=(
        ag.Edge(citing_doc=LIFT, target_doc=RED3, predicate="SUPERSEDES",
                scope="effective_date", new_date="2027-06-01",
                citing_pub_date="2026-08-05"),
    ))
    with pytest.raises(ag.AmbiguousTimelineError, match="cannot attribute"):
        ag.resolve(ambiguous, "effective")


def test_resolve_rejects_an_unknown_kind(red3):
    with pytest.raises(ValueError, match="kind must be one of"):
        ag.resolve(red3, "publication")


# ------------------------------------------------------------ scan guardrail
def test_a_paginating_scan_that_never_ends_raises_instead_of_truncating():
    """A partial amendment graph answers timeline questions wrongly and with
    full confidence, so the bound fails loudly rather than returning what it
    has. The scan itself is a stopgap — the durable fix is a GSI on
    target_doc, recorded in _scan_inbound's docstring."""
    class _Endless:
        def scan(self, **_kw):
            return {"Items": [], "LastEvaluatedKey": {"pk": "x", "sk": "y"}}

    with pytest.raises(ag.AmendmentGraphError, match="exceeded"):
        ag._scan_inbound(_Endless(), RED3)


def test_date_change_scopes_are_derived_from_the_predicate_vocabulary():
    """Not re-listed here. metadata.EDGE_PREDICATE and its copy in processor.py
    drifted once and the fix was to derive; a third copy would reopen it."""
    assert {"effective_date", "compliance_date"} == ag.DATE_CHANGE_SCOPES
    assert "STAYS#" in ag.EDGE_PREFIXES and "CONFIRMS#" in ag.EDGE_PREFIXES
