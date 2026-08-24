"""M09 ruling 1 — a paused `needs_input` run carries no verdict rows.

FOUND BY M08's Playwright suite on its first run against the deployed stack:
the demo paused for human review and rendered a full verdict table underneath
it, `real_deadline` 2028-02-25 at 0.95 confidence, for an empty
`company_profile`. Ruled ground truth by the SME seat at
`milestones/M09/sme-ruling-pause-suppression.md`, on the basis that
`evals/check_discrimination.py:300-310` has classified exactly this as a
knowingly-accepted wrong answer since 2026-08-15.

THREE PROPERTIES, and the middle one is the reason this file exists rather than
a one-line assertion:

  1. `needs_input` carries no rows.
  2. `pending_review` KEEPS them — the reviewer approves or rejects the existing
     answer, so the draft is the artifact under review. Suppressing it there
     would leave a reviewer nothing to review.
  3. THE PROSE SURVIVES. Ruling 4 first proposed skipping synthesis entirely on
     the `needs_input` path, "because the draft is discarded on resume anyway".
     q16 disproves that: it pauses correctly, and its ground truth is an HONESTY
     check that passes on the word "cannot confirm" in the PROSE. Skipping
     synthesis would have regressed a golden question in the act of fixing
     another defect. The q16 case is pinned below with its real recorded
     answer, so that a future "simplification" to skip synthesis fails here
     instead of on the next golden run.

And both `_shape` implementations are driven, not just the rule: the deployed
API and the offline shim are deliberately one mapping, and a fix applied to one
of them would make `make evals` and `make agent-evals` measure different
systems.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from graph.nodes import assertable_rows  # noqa: E402

ROW = {"product": "granola bar", "trigger": "healthy", "required_change": "meet 101.65(d)",
       "real_deadline": "2028-02-25", "confidence": 0.95,
       "citations": ["89 FR 106064"]}

# q16's REAL recorded row and prose, from
# evals/history/c256b81-s3vectors-full.json. Copied rather than invented,
# because the point of this case is that it is the thing the golden set scores.
Q16_ROW = {"product": "All products (no size threshold identified)",
           "trigger": "Front-of-package nutrition summary",
           "required_change": "No requirement found in these sources",
           "real_deadline": "none", "confidence": 0.85,
           "citations": ["89 FR 106064", "21 CFR 101.13"]}
Q16_PROSE = ("Based on the sources provided, there is no binding final rule requiring "
             "a front-of-package (FOP) nutrition summary label. … Therefore, I cannot "
             "confirm from these sources that any front-of-package nutrition summary "
             "is required.")


# ------------------------------------------------------------------ the rule
def test_a_needs_input_run_asserts_no_rows():
    assert assertable_rows([ROW], "needs_input") == []


@pytest.mark.parametrize("status", ["ok", "pending_review", "resumed", "degraded",
                                    "rejected"])
def test_every_other_status_keeps_its_rows(status):
    """`pending_review` is the one that matters and the one most likely to be
    'simplified' into the same branch: there the reviewer approves or rejects
    the existing answer, so the draft IS the artifact under review."""
    assert assertable_rows([ROW], status) == [ROW]


def test_the_rule_does_not_mutate_its_input():
    rows = [ROW]
    assertable_rows(rows, "needs_input")
    assert rows == [ROW]


def test_an_empty_or_missing_row_list_is_handled():
    assert assertable_rows(None, "ok") == []
    assert assertable_rows([], "needs_input") == []


# ------------------------------------------------- both shapes, one contract
def _state(rows, prose="an answer", *, profile_sufficient=False):
    """State as the REAL graph leaves it at an interrupt.

    `status: "ok"` is not a mistake and it is the point of this fixture. The
    `verdict()` node writes `"status": "ok"` into state, and `hitl_gate` has not
    returned when `interrupt()` suspends the run — so on a genuine deployed
    pause the ONLY place `needs_input` exists is the interrupt payload.

    The first version of this file set `status: "needs_input"` in state as well,
    which made every suppression test pass no matter which source `_shape` read.
    Both of these one-line mutations then survived the whole suite while
    restoring the exact M08 defect (`eng-code-reviewer` H3):

        assertable_rows(rows, state.get("status", "degraded"))
        status = state.get("status") or request.get("status") or "degraded"

    With `ok` here, the interrupt payload is the sole source of the pause and
    both mutations turn this file red.
    """
    return {"verdict_rows": rows, "answer": prose, "citations": ["89 FR 106064"],
            "confidence": 0.95, "status": "ok", "review_reason": "",
            "profile_sufficient": profile_sufficient}


class _Interrupt:
    def __init__(self, value):
        self.value = value


def test_the_deployed_api_shape_drops_the_rows():
    from api import api

    state = _state([ROW])
    state["__interrupt__"] = [_Interrupt({"status": "needs_input", "reason": "no profile",
                                          "needs": "company_profile"})]
    body = api._shape(state, "t-1")
    assert body["status"] == "needs_input"
    assert body["answer_rows"] == []
    assert body["answer"] == "an answer", "the prose must survive — see q16 below"


def test_the_offline_shim_shape_drops_them_too(monkeypatch):
    """If these two disagree, `make evals` and `make agent-evals` measure
    different systems — which is why `api._shape`'s docstring says they are
    deliberately the same mapping."""
    from dataclasses import make_dataclass

    import serve_local

    from retrieval import router

    # The shim reports the live tier as provenance, which is an SSM read. Stub
    # it: this test is about which rows the mapping emits, and a unit test that
    # needs AWS credentials is a unit test that skips in CI for the wrong reason.
    monkeypatch.setattr(router, "active_tier", lambda: "s3vectors")

    # The shim asdict()s its rows, so they must really be dataclasses — the
    # deployed API accepts either, and this is the difference between them.
    row_type = make_dataclass("VerdictRowLike", list(ROW.keys()))
    state = _state([row_type(**ROW)])
    state["__interrupt__"] = [_Interrupt({"status": "needs_input", "reason": "no profile",
                                          "needs": "company_profile"})]
    body = serve_local._shape(state, "t-1")
    assert body["status"] == "needs_input"
    assert body["answer_rows"] == []
    assert body["answer"] == "an answer"


def test_a_pending_review_response_still_carries_its_draft():
    from api import api

    # profile_sufficient TRUE: this pause is about confidence, not about a
    # missing asker, so the draft is the artifact the reviewer must see.
    state = _state([ROW], profile_sufficient=True)
    state["__interrupt__"] = [_Interrupt({"status": "pending_review",
                                          "reason": "low confidence",
                                          "needs": "reviewer_decision"})]
    body = api._shape(state, "t-1")
    assert body["status"] == "pending_review"
    assert body["answer_rows"] == [ROW], (
        "a reviewer asked to approve or reject an answer must be able to see it")


def test_a_junk_resume_cannot_put_the_row_back():
    """`eng-code-reviewer` H2, reproduced against the real graph before this
    test existed.

    `_resume_with` turns ANY unusable resume payload into `pending_review`,
    which the status rule exempts — and the graph only re-enters retrieval on
    `resumed`, so the rows synthesised while the profile was insufficient are
    still in the checkpoint. One `POST /resume/<id> {"unrelated": "junk"}` from
    the anonymous asker, who was handed the token in the first response, and the
    forbidden row ships.

    Keying on `profile_sufficient` as well as status is what closes it, and this
    is the test that fails if someone drops that argument as redundant.
    """
    from api import api

    state = _state([ROW])                      # profile_sufficient False
    state["status"] = "pending_review"         # what a junk resume leaves behind
    body = api._shape(state, "t-1")
    assert body["status"] == "pending_review"
    assert body["answer_rows"] == [], (
        "a run whose profile was never sufficient shipped its verdict row by "
        "being resumed with junk — the row is back and the status hid it")


# ---------------------------------------------------------------- q16's case
def test_the_honesty_answer_survives_the_suppression():
    """THE CASE THAT SHAPED THE FIX.

    q16 pauses correctly and its ground truth is an honesty check: the answer
    must report that the sources establish no such requirement, and it passes on
    "cannot confirm" in the prose. The first proposed fix — skip synthesis
    entirely when `profile_sufficient` is false — would have deleted that text
    and regressed q16 while fixing q10.

    Scored through `run_evals.check()` against q16's REAL entry in
    `golden_questions.json` — not against a hand-picked needle. The first
    version of this test asserted `"cannot confirm" in flatten_answer(...)`
    while claiming to be "the real oracle and not a paraphrase of it", which
    was a paraphrase: it pinned one token out of a list the SME seat owns, so a
    ruling that changed the token list would leave this test green and the
    golden set red. `eng-code-reviewer` L8.
    """
    import json

    from run_evals import check

    from api import api

    golden = json.loads((ROOT / "evals" / "golden_questions.json").read_text(
        encoding="utf-8"))
    questions = golden["questions"] if isinstance(golden, dict) else golden
    q16 = next(q for q in questions if q["id"] == "q16")

    state = _state([Q16_ROW], prose=Q16_PROSE)
    state["__interrupt__"] = [_Interrupt({"status": "needs_input", "reason": "no profile",
                                          "needs": "company_profile"})]
    body = api._shape(state, "t-16")

    assert body["answer_rows"] == [], "the row went, as ruled"
    assert check(q16, body) == [], (
        "q16 no longer passes with its rows suppressed — this fix regressed a "
        "golden question while fixing another defect. The prose must survive; "
        "only the rows go.")
