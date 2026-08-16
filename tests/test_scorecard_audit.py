"""A recorded PASS must be auditable after the fact.

Scorecards used to carry `{id, pass, fails}` and nothing else. A FAILURE was
always legible — `fails` names the missing string — but a PASS was dark, and
that is the wrong way round: the 2026-08-15 discrimination sweep found fourteen
wrong answers that the live golden questions score as passes, and there was no
way to ask of any recorded card whether its passes had been earned or merely
given away by a loose accept token. Settling it would have meant re-running the
whole set against Bedrock.

These tests pin the two properties that make a card evidence rather than a
claim: the answer is recorded, and it is recorded whole.

They exercise the real main() with `ask` monkeypatched, so the assertions cover
the recording path a milestone close actually runs, not a reimplementation of
it.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))
import run_evals  # noqa: E402

# Long enough that any sane truncation limit would cut it, so a card that
# silently shortened answers would fail rather than merely look shorter.
LONG_ANSWER = ("The compliance date is February 25, 2028 and it did not change. " * 200)


@pytest.fixture
def one_question(monkeypatch, tmp_path):
    """Run main() over a single synthetic question, recording into tmp_path."""
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": [{
        "id": "qXX",
        "subset": ["smoke"],
        "question": "does the deadline move?",
        "must_contain": ["February 25, 2028"],
    }]}), encoding="utf-8")

    monkeypatch.setattr(run_evals, "GOLDEN", golden)
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(run_evals, "resolve_api_url", lambda _: "http://x")
    monkeypatch.setattr(run_evals, "git_sha", lambda: "deadbee")
    monkeypatch.setattr(run_evals, "git_dirty", lambda: False)
    monkeypatch.setattr(run_evals, "corpus_fingerprint", lambda: {"documents": 1})

    def run(resp):
        monkeypatch.setattr(run_evals, "ask", lambda *a, **k: resp)
        monkeypatch.setattr(sys, "argv", ["run_evals.py", "--record"])
        run_evals.main()
        cards = list((tmp_path / "history").glob("*.json"))
        assert len(cards) == 1, cards
        return json.loads(cards[0].read_text(encoding="utf-8"))["questions"][0]

    return run


@pytest.fixture
def two_questions(monkeypatch, tmp_path):
    """Run main() over two questions, so a run can be partially answered.

    A single-question fixture cannot express the distinction the recording
    guard turns on — "some questions reached the API" versus "none did" — and
    that distinction is the whole point of the guard.
    """
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": [
        {"id": "qAA", "subset": ["smoke"], "question": "one?",
         "must_contain": ["February 25, 2028"]},
        {"id": "qBB", "subset": ["smoke"], "question": "two?",
         "must_contain": ["February 25, 2028"]},
    ]}), encoding="utf-8")

    monkeypatch.setattr(run_evals, "GOLDEN", golden)
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(run_evals, "resolve_api_url", lambda _: "http://x")
    monkeypatch.setattr(run_evals, "git_sha", lambda: "deadbee")
    monkeypatch.setattr(run_evals, "git_dirty", lambda: False)
    monkeypatch.setattr(run_evals, "corpus_fingerprint", lambda: {"documents": 1})

    def run(responses, expect_card=True, want_status=None):
        seq = iter(responses)

        def ask(*a, **k):
            r = next(seq)
            if r == "boom":
                raise RuntimeError("connection refused")
            return r

        monkeypatch.setattr(run_evals, "ask", ask)
        monkeypatch.setattr(sys, "argv", ["run_evals.py", "--record"])
        status = run_evals.main()
        if want_status is not None:
            assert status == want_status, f"exit {status}, wanted {want_status}"
        cards = list((tmp_path / "history").glob("*.json"))
        if not expect_card:
            assert not cards, f"expected no scorecard, got {cards}"
            return None
        assert len(cards) == 1, cards
        return json.loads(cards[0].read_text(encoding="utf-8"))

    return run


def test_a_passing_answer_is_recorded(one_question):
    """The point of the change: a PASS carries the text that earned it."""
    card = one_question({
        "answer": "It did not change: February 25, 2028.",
        "citations": ["89 FR 106064"],
        "status": "ok",
    })
    assert card["pass"] is True
    assert card["response"]["answer"] == "It did not change: February 25, 2028."
    assert card["response"]["citations"] == ["89 FR 106064"]
    assert card["response"]["status"] == "ok"


def test_a_failing_answer_is_recorded_too(one_question):
    """Failures were already legible via `fails`; they must not lose the answer."""
    card = one_question({"answer": "It moved to 2029.", "citations": [], "status": "ok"})
    assert card["pass"] is False
    assert card["fails"]                       # the reason survives
    assert card["response"]["answer"] == "It moved to 2029."


def test_the_answer_is_not_truncated(one_question):
    """A truncated answer reintroduces the audit gap, more quietly."""
    card = one_question({"answer": LONG_ANSWER, "citations": [], "status": "ok"})
    assert card["response"]["answer"] == LONG_ANSWER


def test_answer_rows_survive(one_question):
    """SPEC/03's verdict rows are what check() scores for multi-rule questions."""
    rows = [{"product": "granola bar", "real_deadline": "February 25, 2028"}]
    card = one_question({"answer": "February 25, 2028", "answer_rows": rows,
                         "citations": [], "status": "ok"})
    assert card["response"]["answer_rows"] == rows


def test_a_partial_transport_error_still_produces_a_record(two_questions):
    """An error IS a failure, and the card must not lose the question to it.

    One question reaches the API and one does not, so the run measured
    something and is recorded — with the dead question's error preserved.
    """
    cards = two_questions(["boom", {"answer": "February 25, 2028",
                                    "citations": [], "status": "ok"}])
    dead, live = cards["questions"]
    assert dead["pass"] is False
    assert "connection refused" in dead["fails"][0]
    # `resp` is unbound on this path; the record must still be well-formed
    # rather than raising NameError and taking the whole run down with it.
    assert dead["response"]["answer"] is None
    assert live["pass"] is True
    assert live["response"]["answer"] == "February 25, 2028"


def test_a_run_that_measured_nothing_is_not_recorded(two_questions):
    """The 2026-08-15 defect: a shim that never started scored 0/10 and filed it.

    Nothing measured is not a score of zero. A card of pure connection errors
    is false evidence — it looks like a measurement and sits under a real sha.
    """
    cards = two_questions(["boom", "boom"], expect_card=False)
    assert cards is None


def test_refusing_to_record_is_distinguishable_from_recording_a_failure(two_questions):
    """Exit 2, so a caller can tell 'refused' from 'ran and failed' (which is 1)."""
    assert two_questions(["boom", "boom"], expect_card=False, want_status=2) is None
    # A real, measured failure still exits 1 and still records.
    assert two_questions([{"answer": "wrong", "citations": [], "status": "ok"},
                          {"answer": "wrong", "citations": [], "status": "ok"}],
                         want_status=1) is not None
