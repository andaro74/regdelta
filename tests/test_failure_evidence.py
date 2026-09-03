"""M07 ruling item 4: a failing question must print what the system SAID.

THE DEBT, and why it is worth a test file of its own. The q05 investigation
recorded "the raw text is logged nowhere and cannot be recovered"
(`milestones/M07/eval-gate-flake-gap.md`). Its remedy was never implemented and
the bill came due a second time on 2026-09-03: q18 failed with `status: ok` and
a full cited answer, missing one affirmative-phrase token, and diagnosing it
cost three live Bedrock calls against the deployed API.

These tests exist so the third time does not happen. They assert the OUTPUT,
because the output is the artifact an investigator reads.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))

run_evals = pytest.importorskip("run_evals")

#: The real q18 answer, deployed API, 2026-09-03. Verbatim opening.
Q18_ANSWER = (
    "Yes, your shelf-stable lentil soup labeled 'healthy' is directly affected "
    "by the updated definition of the term 'healthy' under the final rule "
    "published at 89 FR 106064 (Doc. 2024-29957, published 2024-12-27). "
    "This rule revises 21 CFR 101.65(d) to replace the old nutrient-threshold "
    "criteria with new food-group-equivalent requirements. The compliance date "
    "remains February 25, 2028."
)


def _evidence(resp):
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_evals._print_failure_evidence(resp)
    return buf.getvalue()


def test_the_answer_text_reaches_the_card():
    """The one property the whole ruling is about."""
    out = _evidence({"answer": Q18_ANSWER, "status": "ok", "confidence": 0.93,
                     "stop_reason": "end_turn", "citations": ["89 FR 106064"]})
    assert "is directly affected" in out, out


def test_the_adverb_that_cost_a_session_is_visible_in_the_excerpt():
    """THE REGRESSION TEST FOR THE INVESTIGATION ITSELF.

    q18's assertion wanted `is affected`; the model wrote `is directly
    affected`. The excerpt is a HEAD excerpt, so this asserts the deciding
    phrase falls inside it for a real answer of realistic length — a limit set
    too low would print evidence that stops short of the finding, which reads as
    working and is not.
    """
    out = _evidence({"answer": Q18_ANSWER, "status": "ok"})
    excerpt = out.split("answer[", 1)[1]
    assert "is directly affected" in excerpt
    assert "is affected" not in excerpt.replace("is directly affected", "")


def test_a_decline_reports_stop_reason():
    """The literal wording of item 4 — and NOT sufficient on its own, which is
    why the test above exists: q18 was not a decline."""
    out = _evidence({"answer": "", "status": "needs_input", "confidence": 0.1,
                     "stop_reason": "max_tokens"})
    assert "max_tokens" in out
    assert "(empty)" in out


def test_an_empty_answer_says_so_rather_than_printing_nothing():
    """Silence is what the ruling is against. An empty answer is a FINDING —
    at q05 the emptiness was the whole diagnosis — so it must be stated."""
    assert "(empty)" in _evidence({"answer": "", "status": "ok"})


def test_no_response_at_all_prints_nothing_rather_than_crashing():
    """A transport failure has no response. The card must still finish."""
    assert _evidence(None) == ""


def test_the_excerpt_is_bounded_so_the_summary_survives_the_pr_comment():
    """The comment shows `scorecard.txt.slice(-3000)`. An unbounded excerpt on
    a card with many failures would push the run summary out of the window that
    a reviewer actually sees."""
    out = _evidence({"answer": "x" * 20000, "status": "ok"})
    assert len(out) < 1200, "excerpt is not bounded"
    assert "…" in out, "a clipped answer must say it was clipped"
    assert "[20000 chars]" in out, "the reader must know how much was withheld"


def test_the_workflow_keeps_the_full_card_as_an_artifact():
    """The other half: the excerpt is bounded, so the FULL text has to survive
    somewhere the truncated PR comment does not reach."""
    wf = (ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")
    assert "upload-artifact" in wf, "the full scorecard is not kept anywhere"
    assert "if: always()" in wf, "an artifact only kept on success is kept when unneeded"


def test_evidence_is_printed_for_a_failure_that_is_not_a_decline():
    """The q18 SHAPE, end to end through `check()` rather than the helper.

    `status: ok`, a real cited answer, failing only a token group. The old card
    printed the missing-token list and stopped there.
    """
    golden = json.loads((ROOT / "evals" / "golden_questions.json").read_text(encoding="utf-8"))
    q18 = next(q for q in golden["questions"] if q["id"] == "q18")
    resp = {"answer": Q18_ANSWER, "status": "ok", "confidence": 0.93,
            "stop_reason": "end_turn", "citations": ["89 FR 106064"]}
    fails = run_evals.check(q18, resp)
    assert fails, "specimen no longer reproduces the q18 failure; update it"
    assert not run_evals.declined(resp), "q18 was not a decline"
    assert "is directly affected" in _evidence(resp)
