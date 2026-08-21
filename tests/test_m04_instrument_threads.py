"""Two eval-instrument defects M04 found and homed nowhere (README, threads 3-4).

Both are ADR-0013 instances — an instrument that does not read the field its
own claim is about — and both are about the same thing: a run that went wrong
leaving no trace that says so.

  3. `record()` overwrote at one sha, so a flaky question could be re-run
     until green and the losing runs vanished. Every progress claim in this
     repo is a delta against exactly those files.
  4. The agent path discarded `stopReason` while the frozen control in
     `src/baseline/naive.py` has recorded it since M00b — the baseline
     ADR-0002 measures the system against was the better-instrumented of the
     two.

Thread 3 is not merely tidiness for M05: the SPEC/05 Done-when runs the golden
set twice on the AOSS tier at one commit (`up -> evals -> down -> evals -> up
-> evals`), so the second AOSS card would have silently replaced the first —
and the first is the one that proves the tier came back.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

import run_evals

# ------------------------------------------------- 3. record() overwriting


@pytest.fixture
def history(tmp_path, monkeypatch):
    # ONLY HISTORY is redirected. Patching the archive location too would
    # override the sibling-vs-subdirectory choice that
    # test_archives_are_invisible_to_the_readers_of_history exists to check —
    # which it did, and that mutation survived until this fixture stopped
    # reaching past the thing under test.
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path / "history")
    return tmp_path / "history"


def card(passed: int, at: str) -> dict:
    return {"sha": "abc1234", "tier": "aoss", "subset": None,
            "at": at, "passed": passed, "total": 20, "questions": []}


def test_the_first_card_at_a_sha_supersedes_nothing(history):
    out = run_evals.record(card(18, "2026-08-20T10:00:00+00:00"))
    assert json.loads(out.read_text())["supersedes"] == []
    assert not (history / "superseded").exists()


def test_a_second_run_at_one_sha_does_not_erase_the_first(history):
    """The defect, stated as its consequence.

    18/20 then 20/20 at the same commit and tier used to leave only 20/20 on
    disk, with nothing anywhere saying a run had been replaced.
    """
    run_evals.record(card(18, "2026-08-20T10:00:00+00:00"))
    out = run_evals.record(card(20, "2026-08-20T11:00:00+00:00"))

    trail = json.loads(out.read_text())["supersedes"]
    assert len(trail) == 1, "the earlier run left no trace in the card"
    assert trail[0]["passed"] == 18
    assert trail[0]["at"] == "2026-08-20T10:00:00+00:00"

    kept = history / "superseded" / trail[0]["file"]
    assert kept.exists(), "the earlier card was deleted, not archived"
    assert json.loads(kept.read_text())["passed"] == 18


def test_the_trail_accumulates_across_repeated_runs(history):
    """Re-running until green is exactly the behaviour this makes visible."""
    for i, passed in enumerate([15, 17, 20]):
        out = run_evals.record(card(passed, f"2026-08-20T1{i}:00:00+00:00"))
    trail = json.loads(out.read_text())["supersedes"]
    assert [t["passed"] for t in trail] == [15, 17]
    assert [t["run"] for t in trail] == [1, 2]
    assert len({t["file"] for t in trail}) == 2


def test_archives_are_invisible_to_the_readers_of_history(history):
    """A subdirectory, and that choice is load-bearing.

    `previous_card()` picks the most recent card for a tier by globbing
    `*-{tier}-{subset}.json`, and `replay_history` globs `*.json`. Neither
    recurses. As siblings, archived cards would become candidates for "the
    previous card" and would be replayed as though they were separate runs.
    """
    run_evals.record(card(18, "2026-08-20T10:00:00+00:00"))
    run_evals.record(card(20, "2026-08-20T11:00:00+00:00"))

    top = {p.name for p in history.glob("*.json")}
    assert top == {"abc1234-aoss-full.json"}, top
    assert run_evals.previous_card("aoss", None)["passed"] == 20


def test_a_corrupt_previous_card_is_archived_rather_than_blocking(history):
    """Losing the good run to protect the bad one would be the wrong trade."""
    history.mkdir(parents=True)
    (history / "abc1234-aoss-full.json").write_text("{not json", encoding="utf-8")
    out = run_evals.record(card(20, "2026-08-20T11:00:00+00:00"))
    trail = json.loads(out.read_text())["supersedes"]
    assert len(trail) == 1
    assert trail[0]["passed"] is None
    assert (history / "superseded" / trail[0]["file"]).exists()


def test_different_tiers_at_one_sha_are_not_supersessions(history):
    """`up -> evals -> down -> evals` is two tiers, not a repeat."""
    run_evals.record(card(18, "2026-08-20T10:00:00+00:00"))
    other = {**card(18, "2026-08-20T11:00:00+00:00"), "tier": "s3vectors"}
    out = run_evals.record(other)
    assert json.loads(out.read_text())["supersedes"] == []


# --------------------------------------------- 4. stopReason in the agent


@pytest.fixture
def nodes():
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from graph import nodes as mod
    mod.reset_stop_reason()
    return mod


# `verdict` reads state["retrieved"] and state["timeline_facts"] (nodes.py).
# These were {"rows", "facts"} until eng-code-reviewer pointed out that the
# keys were decorative — the tests exercised the empty-context path either way
# and would not have noticed a change to context handling. Empty context is
# still the right fixture here (this file is about the stop reason, not about
# retrieval), but it should be empty because the node read an empty list, not
# because it read a key nobody supplies.
EMPTY_CONTEXT = {"query": "q", "retrieved": [], "timeline_facts": []}


def converse_response(text: str, stop: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}},
            "stopReason": stop}


def test_the_stop_reason_is_carried_out_of_converse(nodes):
    nodes.reset_stop_reason()
    assert nodes.last_stop_reason() is None
    nodes._text_of(converse_response("hi", "max_tokens"))
    assert nodes.last_stop_reason() == "max_tokens"


def test_a_truncated_verdict_says_so(nodes, monkeypatch):
    """The failure this exists for.

    The verdict prompt asks for JSON in 2000 tokens. A cut-off mid-object
    leaves `_json_object` with no closing brace, so the answer is empty and
    the status is "ok" — indistinguishable from a model with nothing to say
    unless the stop reason is on the result.
    """
    def truncated_invoke(*a, **kw):
        # What the node would see: _converse ran, hit the ceiling, and the
        # JSON never closed.
        return nodes._text_of(converse_response('{"answer": "The compl',
                                                "max_tokens"))

    out = nodes.verdict(EMPTY_CONTEXT,
                        invoke=truncated_invoke)
    assert out["answer"] == "", "precondition: the cut-off JSON parses to {}"
    assert out["stop_reason"] == "max_tokens"
    assert out["truncated"] is True, (
        "an empty answer with no explanation is the pause-shaped failure M04 "
        "could not tell apart from a decline")


def test_a_complete_verdict_is_not_flagged(nodes):
    def ok_invoke(*a, **kw):
        return nodes._text_of(
            converse_response('{"answer": "Yes.", "citations": []}', "end_turn"))

    out = nodes.verdict(EMPTY_CONTEXT,
                        invoke=ok_invoke)
    assert out["stop_reason"] == "end_turn"
    assert out["truncated"] is False


def test_an_unobserved_stop_reason_is_none_not_false(nodes):
    """"We did not look" and "we looked and it was fine" are different claims.

    Every fixture in this suite injects `invoke`, so `_converse` never runs and
    nothing observes a stop reason. Reporting `truncated: False` there would
    reassure a reader of an empty answer on the strength of no measurement —
    which is the substitution ADR-0013 is about.
    """
    out = nodes.verdict(EMPTY_CONTEXT,
                        invoke=lambda *a, **kw: '{"answer": "Yes."}')
    assert out["stop_reason"] is None
    assert out["truncated"] is None


def test_the_reading_does_not_survive_into_the_next_call(nodes):
    """A stale reason would attribute one question's truncation to another."""
    nodes._text_of(converse_response("x", "max_tokens"))
    assert nodes.last_stop_reason() == "max_tokens"
    out = nodes.verdict(EMPTY_CONTEXT,
                        invoke=lambda *a, **kw: '{"answer": "Yes."}')
    assert out["stop_reason"] is None, (
        "the verdict node inherited a stop reason from an earlier, unrelated "
        "Converse call")


def test_the_control_and_the_system_now_report_the_same_thing(nodes):
    """ADR-0002 compares them, so their instrumentation has to be comparable."""
    naive_src = (Path(__file__).parent.parent
                 / "src" / "baseline" / "naive.py").read_text(encoding="utf-8")
    assert '"truncated"' in naive_src
    out = nodes.verdict(EMPTY_CONTEXT,
                        invoke=lambda *a, **kw: nodes._text_of(
                            converse_response('{"answer": "Yes."}', "end_turn")))
    assert "truncated" in out


# ------------------------------------- what the M05 reviewers added to these


def test_a_corrupt_card_does_not_erase_the_runs_before_it(history):
    """The trail is rebuilt from the ARCHIVE, not copied from the card.

    Run 1, run 2, then corrupt the live card and record run 3. Reading the
    outgoing card's own `supersedes` would yield {} and restart the trail at
    empty, dropping runs 1 and 2 from the record while their files sat in
    superseded/. Found by eng-code-reviewer.
    """
    run_evals.record(card(15, "2026-08-20T10:00:00+00:00"))
    run_evals.record(card(17, "2026-08-20T11:00:00+00:00"))
    live = history / "abc1234-aoss-full.json"
    live.write_text("{not json", encoding="utf-8")

    out = run_evals.record(card(20, "2026-08-20T12:00:00+00:00"))
    trail = json.loads(out.read_text())["supersedes"]
    # Two supersessions from three record() calls. Run 2's score is genuinely
    # gone — its file is the one that was corrupted — but run 1's is not, and
    # reading the outgoing card's own `supersedes` would have lost both.
    assert [t["run"] for t in trail] == [1, 2]
    assert [t["passed"] for t in trail] == [15, None], (
        "run 1's score was lost; the earlier archives were not read")


def test_a_serialization_failure_never_leaves_zero_cards(history, monkeypatch):
    """Archive is a move, so doing it before json.dumps opened a window where
    a raise left the old card aside and no new one written — after which
    previous_card() finds nothing and corpus-drift detection switches off."""
    run_evals.record(card(18, "2026-08-20T10:00:00+00:00"))

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        run_evals.record({**card(20, "2026-08-20T11:00:00+00:00"),
                          "questions": Unserializable()})

    assert (history / "abc1234-aoss-full.json").exists(), (
        "the previous card was moved aside and nothing replaced it")
    assert run_evals.previous_card("aoss", None)["passed"] == 18
    assert not (history / "superseded").exists()
