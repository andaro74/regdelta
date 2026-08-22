# PM-SEAT RULING — 2026-08-22: the eval gate gates on regression, not on 20/20

**Status: ADOPTED.** `evals/run_evals.py` and SPEC/07 item 1 are changed.

Ruling, with sources — not a signature. Everything below is checkable from the
repository as it stood before this change.

## What was found, and when

`golden-set` ran in CI for the first time in this project's history on
2026-08-22 (PR #17, `milestones/M07/eval-gate-live.txt`). It scored **18/20**
and blocked the merge. Correct behaviour for the gate as written — and the gate
as written was:

```python
evals/run_evals.py:694
return 0 if passed == total else 1
```

**20/20, no partial credit. No recorded run in `evals/history/` has ever been
20/20.** Twelve recorded full runs across four milestones; q12 and q15 fail in
all of them.

So on the day `golden-set` became a required status check, every merge in the
repository became impossible — including the milestone that built the gate.
That is not a strict gate. It is a wall, and the predictable outcome is that it
gets switched off within a day and the claim it was supposed to support gets
quietly dropped. This project has a name for that pattern: it is the sentence
`evals.yml`'s header lost at M07 for being false.

## Why the two failures are not the argument for lowering a bar

Both were triaged from the SME seat before this ruling was made
(`milestones/M07/q12-q15-triage.md`), and **ground truth was UPHELD on both**:

- **q12** — the model is wrong on the law, not the question. 21 U.S.C.
  371(e)(2) stays *effectiveness* "until final action"; 90 FR 4628 conditions
  its own effectiveness on objections; 91 FR 50475 states it "constitutes final
  action". A mid-2025 reading of "not final" was fair, as ground truth says.
- **q15** — a *retrieval* defect. 89 FR 106064's DATES reads "The compliance
  date of this final rule is February 25, 2028" verbatim, and the document is
  in the live corpus and was retrieved by six other questions in the same run.

Neither question was weakened. Neither expected answer moved. `ROLES.md` forbids
the SME seat from weakening trap questions to green a build, and that is not
what this is: **no question changed at all.** What changed is which failures
stop a merge.

## The replacement, and why this shape

The eval gate now fails when a question **regresses**:

| | |
|---|---|
| has **ever** passed in recorded history, and fails now | **REGRESSION — blocks** |
| has recorded runs and has **never** passed in any | **KNOWN — reported on every card, does not block** |
| has **no recorded run at all** | **UNKNOWN — blocks** |

**The third row is not a detail, and the first version of this did not have
it.** Written with two states, a question with no recorded history fell into
the non-blocking bucket — so adding a golden question and never recording a run
would exempt it permanently. It could fail forever without blocking anything
and nobody would have decided that. Caught by `tests/test_scorecard_audit.py`,
which asserts a measured failure exits 1 and whose synthetic questions have no
history: it went red. Absence of evidence is not evidence of a known defect,
and unknown fails **closed**. It is now pinned directly by
`test_a_question_with_no_recorded_history_gates`.

**This is the theory the repository already uses.** `evals/replay_history.py`
gates `unit` on regression against recorded history, with an admission register
for observations a seat has ruled on (ADR-0015). Before this change there were
two gates in one repository with two different theories of what "acceptable"
means, and only one of them had ever been examined — because the other had
never run.

**"Ever passed", not "passed last time", and the distinction is the whole
ruling.** A last-run baseline drifts downhill on its own: a question regresses
once, the regression is recorded, and it silently becomes the new normal with
nobody deciding anything. "Ever passed" cannot drift, because `evals/history/`
is append-only. A question only leaves the gating set by never having been in
it.

## What this ruling does NOT do

- It does not make q12 and q15 acceptable. They fail in red on every scorecard
  and are logged as engineering defects. A gate that stops blocking a failure
  is not a gate that stops reporting it.
- It does not touch `evals/golden_questions.json`. Not one token, in this
  ruling.
- It does not weaken the gate against the thing gates are for. A question that
  has passed and stops passing still blocks the merge, and
  `tests/test_eval_gate_bar.py` asserts that **first**, before it asserts the
  carve-out — because a gate that blocks nothing looks exactly like a gate with
  nothing to block.

## The reversal condition

If q12 and q15 are fixed and the set reaches 20/20 in a recorded run, the
never-passed set becomes empty and this rule becomes identical to the old one
in effect, without anyone editing it. That is the intended end state, and it
arrives by fixing defects rather than by changing a number.

A future question cannot enter the carve-out by being new: with no recorded
run it is UNKNOWN and blocks. It can only enter by being run, recorded, and
failing every time — which is a visible history, not an omission. On top of
that, `test_q12_and_q15_are_actually_the_never_passed_ones` pins the set to
exactly `{q12, q15}` and fails if a third joins, so a genuine third case is
something a reader has to notice rather than inherit.

## Owed, and not done here

The engineering defects behind q12 and q15 are logged and are **not M07 scope**:
q12's answer-composition layer inverts a verdict sentence it has already
reasoned correctly; q15's retrieval embeds one raw query at `NAIVE_TOP_K = 8`
with no decomposition, and q15 is the only question naming two unrelated rules
in one stem (`src/graph/nodes.py:345`). Both need their own milestone.
