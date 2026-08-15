"""The poller's subject filter (SPEC/01).

"Agency = FDA" is not a subject filter — the same agency publishes device
reclassifications and drug user-fee notices, and unfiltered they landed in a
food-labeling corpus and competed for the eight retrieval slots every answer
gets. Every case below uses the CFR references the live Federal Register API
actually returns for that document, so these are fixtures, not inventions.
"""
import pytest
from conftest import FIXTURES  # noqa: F401  (path setup)

from ingestion import poller
from shared import config


def _refs(*pairs):
    return [{"title": t, "part": p, "chapter": None, "citation_url": None}
            for t, p in pairs]


# Real values, fetched from the FR API on 2026-08-15.
IN_SCOPE = {
    "2024-29957 healthy rule": _refs((21, "101")),
    "2025-00830 Red No. 3": _refs((21, "74")),
    "2026-15920 stay lift": _refs((21, "74")),
    "2026-16296 GRAS": _refs((21, "170"), (21, "570")),
    "2026-16420 RTE food guide": _refs((21, "117")),
}
OUT_OF_SCOPE = {
    "2026-16209 breast tomosynthesis": _refs((21, "892")),
    "2026-15963 radiology devices": _refs((21, "892")),
    "2026-16727 hematology devices": _refs((21, "864")),
    "2026-16728 gastro-urology devices": _refs((21, "876")),
    "2026-16729 device accessories": _refs((21, "870"), (21, "876"), (21, "878")),
}


@pytest.mark.parametrize("name", list(IN_SCOPE))
def test_food_documents_are_kept(name):
    keep, why = poller.in_scope(IN_SCOPE[name])
    assert keep, f"{name} was dropped ({why}) — the golden set depends on it"


@pytest.mark.parametrize("name", list(OUT_OF_SCOPE))
def test_device_documents_are_dropped(name):
    keep, _ = poller.in_scope(OUT_OF_SCOPE[name])
    assert not keep, f"{name} was kept — this is what the filter exists to stop"


def test_the_stay_lift_survives_the_filter():
    """Singled out because losing it would be silent and expensive: ADR-0007's
    entire stay model is reconstructed from this one document, and nothing else
    in the corpus records that the Red No. 3 order was ever suspended."""
    assert poller.in_scope(_refs((21, "74")))[0]


def test_a_topic_filter_would_have_dropped_red_no_3():
    """Not a test of code — a test of the DECISION, pinned so it is not
    quietly revisited. The Red No. 3 order's FR topics are ['Color additives',
    'Cosmetics', 'Drugs']: no food topic at all. Anyone reaching for a topic
    allowlist should fail here first and read why."""
    red3_topics = ["Color additives", "Cosmetics", "Drugs"]
    assert not any("food" in t.lower() for t in red3_topics)


def test_a_document_citing_both_food_and_device_parts_is_kept():
    """One food part is enough. A rule amending 21 CFR 101 and 21 CFR 880 still
    changes food labelling, and dropping it would lose a real obligation to
    keep out material that arrives with it anyway."""
    assert poller.in_scope(_refs((21, "101"), (21, "880")))[0]


def test_another_title_is_not_mistaken_for_a_food_part():
    """9 CFR 317 is USDA meat labelling — same part NUMBER range, different
    title, not this corpus. The comparison is on (title, part), never part."""
    keep, why = poller.in_scope(_refs((9, "317")))
    assert not keep
    assert "21 CFR" in why


def test_a_non_numeric_part_is_not_guessed_at():
    """`part` comes from a response body. It is compared numerically or not at
    all — never coerced into one."""
    assert not poller.in_scope(_refs((21, "101A-ish")))[0]


def test_junk_in_place_of_the_reference_list_does_not_crash_the_poll():
    for junk in (None, "", 42, [None], [{"title": 21}], [[]]):
        keep, why = poller.in_scope(junk)
        assert isinstance(keep, bool) and isinstance(why, str)


def test_no_cfr_reference_is_excluded_by_default(monkeypatch):
    """38 of 49 documents on 2026-08-15, and unfilterable any other way — they
    carry no topics either. A document citing no CFR part amends no regulation,
    so it cannot be the subject of 'what changed and what is the deadline'."""
    monkeypatch.setattr(config, "POLL_REQUIRE_CFR", True)
    keep, why = poller.in_scope([])
    assert not keep
    assert why == "no cfr_references"


def test_the_no_reference_rule_is_a_flag_not_an_assumption(monkeypatch):
    """It is a scope judgement, so it is reversible: POLL_REQUIRE_CFR=0 takes
    the old behaviour back, along with the drug and device fee notices."""
    monkeypatch.setattr(config, "POLL_REQUIRE_CFR", False)
    assert poller.in_scope([])[0]


def test_a_vanished_cfr_references_field_raises_rather_than_halting_quietly(monkeypatch):
    """The failure this filter introduces, guarded. If the API renames the
    field, every record looks reference-less, everything is skipped, and the
    handler returns enqueued:0 — indistinguishable from a quiet week. Keyed on
    the KEY being ABSENT, not on the skip count, because a week of device
    notices legitimately skips everything.
    """
    def poll_with_field_gone(since):
        poller._missing_scope_field.append("2026-99999")
        return []

    monkeypatch.setattr(poller, "_new_fr_docs", poll_with_field_gone)
    monkeypatch.setattr(poller, "_new_cfr_versions", lambda: [])
    monkeypatch.setattr(poller, "_client", lambda name: None)   # must not be reached

    with pytest.raises(ValueError, match="cfr_references"):
        poller.handler({"mode": "daily"}, None)


def test_an_ordinary_poll_still_enqueues_and_reports_what_it_skipped(monkeypatch):
    """The control for the test above, and the reporting contract: a scope
    filter running unattended must show what it dropped, or the next person to
    wonder where a document went has nothing to read."""
    sent = []

    class _FakeSQS:
        def send_message(self, QueueUrl, MessageBody):
            sent.append(MessageBody)

    def poll(since):
        poller._accepted.append("2025-00830")
        poller._skipped.append("2026-16209: 21 CFR parts [892]")
        return ["2025-00830"]

    monkeypatch.setattr(poller, "_new_fr_docs", poll)
    monkeypatch.setattr(poller, "_new_cfr_versions", lambda: [])
    monkeypatch.setattr(poller, "_client", lambda name: _FakeSQS())

    result = poller.handler({"mode": "daily"}, None)
    assert result["enqueued"] == 1
    assert result["skipped_count"] == 1
    assert "892" in result["skipped_out_of_scope"][0]
    assert len(sent) == 1
