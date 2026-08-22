# ADR-0015: A merge gate may be overridden per observation, never per rule

- Status: **proposed** — drafted at M07, awaiting the human seat.
- Date: 2026-08-21
- Milestone: M07
- SME-seat ruling; primary sources cited inline; no second approver exists
  (ADR-0005).
- Amends: nothing. Records a mechanism M05's own ruling declined to build, and
  says why the shape adopted here is not the shape that was declined.
- **Drafted in the engineering seat.** Engineering proposed the mechanism,
  implemented it, and is writing it up. Read it as a proposal. What makes it
  checkable is that every claim below is exercised by
  `milestones/M07/admission_mutations.py` and `tests/test_admitted_false_fails.py`,
  which were written to try to break it rather than to describe it.

## Context

`evals/replay_history.py` re-scores every recorded answer with today's
`check()` and gates CI on FRAGILE — a question whose agent answer passed
earlier and fails later. Since 2026-08-20 it has been red on q03, and with it
`unit`, and with `unit` every pull request to `main`. PR #14 read
`mergeStateStatus: BLOCKED` for this reason and was merged from the admin seat
anyway, which is the shape of an unusable gate.

The M05 SME ruling established that q03's failure is a **false fail**: the
banned literal `TTB requires` occurs only inside *"I cannot confirm from these
sources whether TTB requires …"*, the answer attaches zero citations to the
other-agency row, and it does not commit the error the ban exists to catch
(`milestones/M05/q03-ruling.md` §2). That ruling stands and is not reopened.

M05 §11 then chose **option 3, leave it**, on a reason that was correct at the
time: making the gate clear "means building an admit path into FRAGILE, which
`replay_history` was deliberately built without … that mechanism would then be
permanently available to silence real non-determinism, and the first thing it
would silence is the detector that just caught a real defect."

M05 recorded the real fix as open thread 7: *score the structure, not the
characters — the failing answer's `answer_rows[1].citations` was `[]`, so the
invariant is checkable without looking at wording.*

## The finding that changed the decision

**Open thread 7's remedy was measured before being built, and it does not
work.** `milestones/M07/q03_invariant_probe.py`, over all 22 recorded q03
answers:

| observation | count |
|---|---|
| answers carrying `answer_rows` | 11 of 22 |
| answers carrying **no** `answer_rows` at all | 10 of 22 (5 agent-mode) |
| row-bearing answers whose other-agency row carries citations | **0 — including both FAILs** |
| answers with the banned literal in the rows | **0** |
| answers with the banned literal in the prose | 2 — both FAILs |

The field is `[]` in the **passing** answers too. So the proposed rule scores
the passing and failing answers identically, is inert on ten of the
twenty-two, and reads a location the defect has never occupied. The thread
generalised an instrument from one field of one card.

Two further candidates were measured and are dead
(`milestones/M07/q03_instrument_probe.py`):

- **Key the rule on the failure reason.** The `LIMIT_FALSE_FAIL` specimen and
  three `WRONG` specimens produce byte-identical reason sets:
  `["forbidden text present: 'TTB requires'"]`. Nothing keyed on the scorer's
  own output can separate them.
- **Drop the TTB tokens.** Six defective answers become passes, including B1 —
  the fabricated TTB obligation that got the M05 rule reverted. Fails
  `milestones/M05/negation_scope_false_passes.py`, which is the acceptance bar.

And the reason no fourth candidate is coming, from
`milestones/M07/q03-prose-diff.txt`. The failing and passing answers at the
same sha, same day:

> **FAIL:** "I cannot confirm from these sources whether **TTB requires** a
> formula amendment filing, a label re-approval, or any notification…"
> **PASS:** "I cannot confirm from these sources whether **you must separately
> update that formula approval** … or whether that agency has issued its own
> guidance or requirements…"

Same paragraph, same hedge, same empty other-agency row, same
`pending_review`. Separating that from *"whether exempt or not, TTB requires a
revised formula"* is a judgement about syntactic scope in natural language.
The 2026-08-12 note predicted it; the M05 attempt approximated it with
substrings and produced four false passes.

**So the ban is not a defective implementation of a good instrument. It is the
wrong kind of instrument for this proposition**, and no further patch to it is
coming. That is what makes this a decision about the gate rather than about
the scorer.

## Decision

A recorded answer's failure may be admitted by the SME seat **per observation**
and never **per rule**.

`evals/admitted_false_fails.json` holds entries; `replay_history` consults it
after `check()` has scored an answer and only when that answer is already
failing. Four fields must match exactly: `question`, `sha`, `scored_sha256`
(the digest of `run_evals.flatten_answer(resp)` — the exact text `check()`
scores) and `admits_fails` (the failure reasons, exactly and in order).

### Why this is not the mechanism M05 refused

M05's objection was to a **rule**: something that suppresses a class of
failures and therefore silences future ones. An entry here names an
**artifact**:

| property | consequence | pinned by |
|---|---|---|
| keyed to the answer's digest | a paraphrase is not admitted, so FRAGILE stays live on new non-determinism — which is the exact thing it exists to catch | `test_a_paraphrase_is_not_admitted` |
| failure reasons matched exactly | an admitted answer failing for a *new* reason is not admitted, so an entry cannot silence a defect it was not written for | `test_a_different_failure_reason_is_not_admitted`, `test_an_extra_failure_reason_is_not_admitted` |
| consulted only when already failing | it can subtract a failure; it can never create or preserve a pass | `test_an_admission_cannot_suppress_a_passing_answer` |
| never reaches `run_evals.py` | `make evals` still scores the answer as failing; the live scorecard is unchanged | `test_run_evals_is_untouched_by_the_register` |
| an entry matching nothing **gates** | the register cannot accumulate dead overrides, which is how an override list rots into the general admit path | `test_a_stale_entry_gates` |
| an entry citing no resolvable ruling **admits nothing and gates** | an override a reader cannot falsify is not a seat ruling (ADR-0005) | `test_an_entry_citing_no_ruling_does_not_admit` |
| printed every run, `ADMIT` not `PASS` | a suppression a reader must go looking for is the thing that was refused | `test_the_admission_is_reported_on_every_run` |
| `--no-admissions` | the unadmitted state is one flag away and is recorded in the evidence pack | `test_no_admissions_reports_the_unadmitted_state` |

Thirteen cases were run rather than argued
(`milestones/M07/admission-mutations.txt`): sha changed, question changed,
digest changed by one character, an extra reason, a different reason, no
reason, no ruling reference, a ruling citing a document not in the tree,
register emptied, an unruled entry beside a good one, the register file absent,
an entry for a question with no recorded cards, and the baseline.
**Zero survivors**, register restored byte-for-byte.

The refusal set is enumerated in SPEC/07's Done-when rather than left as
"every refusal", because the first version of it was written by this
mechanism's own author with the mechanism in hand — the 2026-08-15 failure
mode, which `milestones/M05/q03-ruling.md` §10 records this project committing
twice already. `pm-spec-reviewer` supplied the enumeration adversarially, and
**two of the cases it named were ones this set had missed** — see below.

### What the spec review found that this ADR had asserted

`pm-spec-reviewer` returned *request changes* on the SPEC/07 diff, and two of
its five blockers were defects in the mechanism rather than in the prose
(`milestones/M07/spec07-pm-review.md`):

- **The staleness claim was stated absolutely and was false.** An entry whose
  question has no recorded answer is reported, not gated — the hole recorded
  in Consequences below — and no mutation covered it. The spec bullet now
  states both halves and a mutation pins the exempt one.
- **Nothing required an entry to cite a ruling.** `ruling` was read at print
  time only, so an entry citing nothing admitted a failure exactly as well as a
  ruled one and printed `— None`. This ADR's own Consequences said *"the only
  thing requiring a ruling behind an entry is a convention"* — and then a spec
  bullet asserted the convention as a guarantee. `cites_ruling` is a check now:
  an entry whose ruling is absent or does not resolve admits nothing and fails
  the run as `UNCITED ADMISSION`.

That is the same shape as this ADR's own subject matter and as ADR-0005's
original defect: a property asserted in prose, unenforced in code, and true
only until someone read the two against each other.

`evals/golden_questions.json` was not edited at any point, and this mechanism
does not edit it.

## Alternatives considered

- **Open thread 7's structural check.** Measured and refuted above. Kept as
  the reason this ADR exists rather than as a deferred option.
- **Leave it (M05 §11 option 3).** Costs the milestone its deliverable: Door 1
  cannot be filmed with the intended cause while `unit` is red for an
  unrelated reason, and SPEC/07's Done-when would need amending instead. It
  also leaves every PR blocked and the admin bypass as the only way through,
  which is the configuration ADR-0005 exists to argue against.
- **Redesign q03** (split the citable date from the decline). The honest
  long-term fix and squarely the SME seat's. Declined for now: q03 passes most
  runs, the failure is a rare phrasing, and redesigning a mostly-working trap
  question under deadline is how the 2026-08-12 false pass was written.
- **A general admit path into FRAGILE.** What M05 refused, and the refusal
  stands.

## Consequences

+ `unit` is green for the first time since M04 — 1211 passed, 0 failed — so
  the merge gate is usable and blocks for reasons a reader can act on.
+ The false fail is now *recorded with a ruling* rather than *ambient in a red
  check nobody can clear*. `check_discrimination.py`'s `LIMIT_FALSE_FAIL`
  specimen is unchanged, so `make discrimination` keeps reporting the
  underlying defect.
+ FRAGILE keeps its teeth on everything it was built for: any new
  disagreement, on any answer that is not byte-identical to a ruled one.

- **An entry can currently be born with its own justification.** `unit` is the
  only required check, approvals are zero and code-owner review is off
  (`milestones/M07/baseline/ruleset-20392406.json`), so one pull request can add
  both an entry and the ruling document it cites — and the entry is usable in
  the commit that introduces it. `cites_ruling` cannot close this: it can only
  ask whether the document is in the tree, and in that PR it is.
  `security-reviewer`, M07 M2.

  What closes it is a **code-owner review requirement** on the register's path,
  because the seat that must approve is then not the seat that wrote it.
  `.github/CODEOWNERS` now routes `/evals/admitted_false_fails.json` to the SME
  seat for exactly that reason. **That is not enforcement today** — with one
  collaborator, CODEOWNERS enforces nothing (ADR-0005) — so this is recorded as
  an open hole that Door 1 closes, not as a fix. A merge-base check
  (`git cat-file -e origin/main:<path>`) was considered and rejected: `actions/
  checkout` fetches at depth 1, so `origin/main` is often absent on the runner,
  and a control that silently degrades to fail-open is worse than a named hole.

- **This is an override list, and override lists get used.** A future operator
  in a hurry can examine an answer carelessly, write an entry, point `ruling`
  at a document that exists, and green the build. **This is a real reduction in
  assurance and is stated as one.** What is mechanical is narrower and worth
  being precise about: an entry cannot be wrong about a *different* answer,
  cannot outlive the observation it describes, cannot be invisible, and cannot
  be uncited — what it can be is *badly reasoned*, and no check reaches that.
  SPEC/07's Out of scope caps M07 at one entry and `test_m07_adds_exactly_one_entry`
  enforces the cap, so the register cannot grow by habit; growing it takes a
  seat ruling and a spec change, which is the friction that is actually load-bearing.
- q03's underlying defect is **not fixed**. The register says so on every run.
- The staleness rule leaves a hole, stated here rather than discovered later:
  if every recorded card for a question disappears, that question's entries
  are never judged. It is reported as `NOT EVALUATED` and deliberately does
  not gate, because the same condition is produced by any legitimate run over
  a subset of history (`--id`, a synthetic fixture).
- A genuine future fix to q03 makes the entry stale, which **fails the run**
  until it is removed. That is a small tax on the right outcome, and it is
  deliberate: the register must not hold entries that describe nothing.

## Note for anyone reading this repo as a work sample

The mechanism was not the interesting part. The interesting part is that M05
wrote down a remedy that sounded right — *check the structure, not the
characters* — and the field it named was `[]` in the passing answers as well as
the failing one, which nobody had looked at. It took a probe over all 22
recorded answers to find that out, and the probe was written **because** the
last attempt at this same question shipped on a plausible mechanism and was
reverted the same day.

This project's premise is that a correct-sounding root cause is an unverified
claim. That applies to remedies written in one's own open-threads list at
least as much as to regulatory text.
