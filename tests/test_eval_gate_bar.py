"""What the eval gate blocks on, and what it deliberately does not.

The bar changed on 2026-08-22, the first day `golden-set` ever ran in CI, by
PM-seat ruling (milestones/M07/eval-gate-bar-ruling.md). It was
`passed == total` — 20/20, no partial credit — and no recorded run in
evals/history/ has ever been 20/20. So the moment the job became a required
check, every merge in the repository became impossible, including the milestone
that built the gate.

These tests exist because the replacement is easy to get wrong in the direction
nobody notices: a gate that blocks nothing looks exactly like a gate that has
nothing to block. So the first thing asserted here is that a REGRESSION still
fails the run, and the never-passed carve-out is asserted second.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))

run_evals = pytest.importorskip("run_evals")


def card(fail_ids: set[str], n: int = 20) -> list[dict]:
    """A per-question result list of the shape main() builds."""
    return [{"id": f"q{i:02d}", "pass": f"q{i:02d}" not in fail_ids}
            for i in range(1, n + 1)]


# --------------------------------------------------------------------------
# The gate still gates. This is the half that matters.
# --------------------------------------------------------------------------

def test_a_question_that_regresses_fails_the_run():
    """q03 has passed in recorded history. If it fails, the merge is blocked.

    If this test ever goes green-by-vacuity — because `ever_passed()` returned
    an empty set, say — the gate would be blocking nothing while still
    reporting success. That is the failure mode the whole file guards."""
    assert run_evals.gate_verdict(card({"q03"})) == 1


def test_several_regressions_still_fail():
    assert run_evals.gate_verdict(card({"q03", "q14", "q20"})) == 1


def test_a_regression_fails_even_alongside_the_known_failures():
    """The known-failure carve-out must not swallow a real regression that
    happens to arrive in the same run."""
    assert run_evals.gate_verdict(card({"q12", "q15", "q03"})) == 1


def test_ever_passed_is_not_empty():
    """Guards the vacuity above directly rather than by inference. An empty
    set would make every failure 'known' and the gate would pass anything."""
    passed = run_evals.ever_passed()
    assert len(passed) >= 15, f"suspiciously small: {sorted(passed)}"
    assert "q03" in passed


# --------------------------------------------------------------------------
# What it deliberately does not block
# --------------------------------------------------------------------------

def test_questions_that_have_never_passed_do_not_block():
    """q12 and q15 fail in every recorded run across three milestones. They are
    real defects — a reasoning defect and a retrieval defect respectively,
    triaged in milestones/M07/q12-q15-triage.md with ground truth UPHELD on
    both — and they are not this pull request's doing."""
    assert run_evals.gate_verdict(card({"q12", "q15"})) == 0


def test_q12_and_q15_are_actually_the_never_passed_ones():
    """Pins the carve-out to the two questions it was ruled for. If a third
    question ever joins them it is because it has never passed, which is a
    thing a reader should have to notice rather than inherit."""
    never = {q["id"] for q in card(set())} - run_evals.ever_passed()
    assert never == {"q12", "q15"}, (
        f"the never-passed set moved: {sorted(never)}. That is either a new "
        "question with no recorded run yet, or a question whose history was "
        "lost. Both need a look before this test is updated.")


def test_a_clean_run_passes():
    assert run_evals.gate_verdict(card(set())) == 0


# --------------------------------------------------------------------------
# The old bar is gone, and stays gone
# --------------------------------------------------------------------------

def test_the_bar_is_not_passed_equals_total():
    """18/20 with both failures known must exit 0. Under the old bar this was
    exit 1, and under the old bar it was exit 1 for every run this repository
    has ever recorded."""
    result = card({"q12", "q15"})
    assert sum(1 for q in result if q["pass"]) == 18
    assert run_evals.gate_verdict(result) == 0


def test_the_source_no_longer_contains_the_old_criterion():
    """A grep-level guard. The old line is one edit away from coming back and
    would silently restore an unsatisfiable gate."""
    source = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert "return 0 if passed == total else 1" not in source


# --------------------------------------------------------------------------
# The third state, which the first version of this gate got wrong
# --------------------------------------------------------------------------

def test_a_question_with_no_recorded_history_gates():
    """Absence of evidence is not evidence of a known defect.

    The first version of `gate_verdict` had two states — ever-passed and
    everything else — so a question with NO recorded run fell into the
    non-blocking bucket. That means adding a golden question and never
    recording a run makes it permanently exempt: it can fail forever without
    blocking anything, and nobody has to decide that.

    Found by tests/test_scorecard_audit.py, which asserts a measured failure
    exits 1 and whose synthetic questions have no history. Unknown fails
    CLOSED, and this pins it directly rather than through that test's
    side effect."""
    invented = [{"id": "qZZ", "pass": False}]
    assert "qZZ" not in run_evals.ever_passed()
    assert run_evals.gate_verdict(invented) == 1


def test_the_carve_out_requires_recorded_runs_not_merely_absence():
    """q12 and q15 are exempt because they have HISTORY in which they never
    passed — twelve recorded runs each — not because nothing is known."""
    ever, has_history = run_evals.history_verdicts()
    for qid in ("q12", "q15"):
        assert qid in has_history, f"{qid} must have recorded runs to be exempt"
        assert qid not in ever
    assert "qZZ" not in has_history
