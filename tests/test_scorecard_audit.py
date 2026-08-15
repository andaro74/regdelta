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


def test_a_transport_error_still_produces_a_record(one_question, monkeypatch):
    """An error IS a failure, and the card must not lose the question to it."""
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(run_evals, "ask", boom)
    monkeypatch.setattr(sys, "argv", ["run_evals.py", "--record"])
    run_evals.main()
    cards = list((run_evals.HISTORY).glob("*.json"))
    card = json.loads(cards[0].read_text(encoding="utf-8"))["questions"][0]
    assert card["pass"] is False
    assert "connection refused" in card["fails"][0]
    # `resp` is unbound on this path; the record must still be well-formed
    # rather than raising NameError and taking the whole run down with it.
    assert card["response"]["answer"] is None
