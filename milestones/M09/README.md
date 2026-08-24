# M09 — The paused-run defect: ruled, measured, fixed. **IN FLIGHT — the golden run is unpaid.**

- Branch: `m09-pause-suppression` (off `m08-ui-surface`, which is unmerged)
- Spec: none new. This is SPEC/04 behaviour, found by SPEC/08's suite.
- ADRs touched: none. Not tagged, no PR, no CI workflow changed.
- **`evals/golden_questions.json` is UNTOUCHED.**

## What this milestone is

M08's Playwright suite, first run against the deployed stack, found that a run
which pauses for human review **also asserts an answer** — deadline
`2028-02-25`, confidence 0.95, and prose claiming the asker makes a 'healthy'
claim, for a `company_profile` of `{}`.

M09 is the disposition. It has three parts, and **two of them are done**.

## 1. The ruling — done

`sme-ruling-pause-suppression.md`, accepted with amendments by the human seat
on 2026-08-23. Six propositions, of which the seat **split one and added one**.

The load-bearing correction: M08 justified its assertion with a code comment.
The real basis is `evals/check_discrimination.py:300-310`, which has classified
"gate fires but the answer asserts a deadline anyway" as a **knowingly-accepted
wrong answer since 2026-08-15**. The seat had already ruled this; M08 only
observed the deployed system doing it.

The amendment that mattered most: the draft asked the seat to rule *which* of
four pauses were wrong, on an unmeasured hypothesis. **The seat split that out
and deferred it** — and the measurement then refuted the hypothesis. See below.

## 2. The measurement — done, and it refuted the hypothesis

`supervisor_probe.py`: `supervisor()` alone, 3 calls per question, raw model
output captured, q18 and q01 as controls. 18 `MODEL_FAST` calls, no Opus, no
retrieval.

The draft's reading was *"the classifier fires on the words us/our"*. It is
wrong, and two observations kill it:

- **q19** — *"Our supplier says … Are they right?"* — asks whether a third
  party's reading of a document is correct. Nothing applies-to-the-asker about
  it. It paused stably anyway.
- **q10** extracted `claims: ['healthy']` **and returned
  `profile_sufficient: false`** — a flat contradiction of the prompt's own rule
  that naming a claim makes a question sufficient. The model was resolving an
  ambiguity the instruction never addressed: *"names a claim"* means both "the
  asker's label bears this" and "this is what the rule is about". **The model
  was right and the prompt was wrong.**
- **q16** flip-flopped 2:1 across three identical calls — unstable exactly
  where the prompt was ambiguous, which is the signature of an under-specified
  instruction rather than an unreliable model. **A single-call probe would have
  reported it settled**, which is why the probe asks three times.

Deferring 3b was the decision that paid: had it been accepted as drafted, a
refuted hypothesis would now be sitting in a ruling document as fact.

## 3. The prompt fix — done, and it took two attempts

Two changes to `_SUPERVISOR_PROMPT` (`src/graph/nodes.py`), per ruling 3b-iv:
disambiguate `claims` to mean the asker's own label, and give the prompt a way
to say *this needs no asker at all*.

**Before / after, same probe, same controls.** The column is
`profile_sufficient`, which is what the probe measures — **not** "does it
pause". `_needs_review` has four triggers and this is one of them; the other
three (uncited answer, uncited dated row, degraded timeline) are unmeasured on
the newly-sufficient path. "Stops pausing" is an inference from this table, not
a reading of it. `eng-code-reviewer` M7.

| id | before | after | wanted (ruling 3b) |
|---|---|---|---|
| q04 | insufficient | **sufficient** | should not pause ✓ |
| q10 | insufficient | **insufficient** | should pause ✓ |
| q16 | **unstable 2:1** | **insufficient, stable** | should pause ✓ |
| q19 | insufficient | **sufficient** | should not pause ✓ |
| q18 (control) | sufficient | sufficient | unchanged ✓ |
| q01 (control) | sufficient | sufficient | unchanged ✓ |

`intent` is annotation only — nothing in `graph.py` routes on it
(`src/graph/state.py`, `src/graph/instrument.py`) — so the probe's intent
column is evidence about the classifier and not about behaviour, and the prompt
change cannot have disturbed timeline routing.

`supervisor-probe.json` (before) and `supervisor-probe-after.json` (after).

### The first attempt regressed q16, and that is recorded rather than tidied

Attempt 1 said `profile_sufficient` is TRUE for *"a question about what a
document says, what a rule means, whether a date or a requirement exists"*.
That clause **swallowed q16** — *"Do we have to put a nutrition summary on the
front of our package, and by when?"* reads as "does a requirement exist", so
q16 stopped pausing. Stable, and stably wrong: it fixed the instability the
ruling complained about and stabilised it on the verdict the ruling rejected.

Attempt 2 replaced the clause with the actual semantic test — **would the
answer be the same for everyone?** A question of law has one answer for every
asker; whether a labeling requirement reaches *your* product does not, because
the exemptions turn on the product. That formulation matches all four rulings
without naming any of the four questions.

**The honest limitation:** the prompt was tuned against six questions and the
acceptance test is the same six. That is a real overfitting risk, and it is
bounded rather than eliminated — by using a semantic test rather than
question-specific wording, and by the two controls. **The real check is the
golden set, which has not been run.** See what is not done.

## 4. The suppression fix — done, at the response boundary

`graph.nodes.assertable_rows(rows, status, profile_sufficient)`, called by both
`src/api/api.py:_shape` and `evals/serve_local.py:_shape`. A response carries no
verdict rows if it ends `needs_input`, or if the run never had a sufficient
profile whatever status it ends in.

**This DEPARTS from ruling 4's layer assignment, and the reason is q16.**
Ruling 4 proposed doing it in the graph — don't synthesise once
`profile_sufficient` is false — on the ground that the draft is discarded on
resume anyway. That premise is false for q16: it pauses correctly, and its
ground truth is an HONESTY check that passes on "cannot confirm" in the
**prose**. Skipping synthesis would have deleted the text q16 scores on and
regressed a golden question in the act of fixing another. So the prose survives
and the rows — the table where a deadline is put in front of a reader — do not.
The layer was explicitly the engineering seat's call in the ruling ("ENG SEAT'S
CALL, with one domain input"), and the domain input is unchanged.

### What review caught, and it was reproduced rather than argued

`eng-code-reviewer` **H2**: the first version keyed on status alone.
`_resume_with` turns any unusable resume payload into `pending_review`, which
the status rule exempts, and the graph only re-enters retrieval on `resumed` —
so the rows synthesised while the profile was insufficient sat in the
checkpoint untouched. **Reproduced against the real graph:**

```
POST /query                              -> needs_input,    rows []
POST /resume/<id> {"unrelated":"junk"}   -> pending_review, rows [2028-02-25 …]
```

One request, by the anonymous asker who was handed the token in the first
response. Fixed by reading `profile_sufficient` — the predicate that made the
run untrustworthy — rather than only the status, which is a symptom.

`eng-code-reviewer` **H3**: the test fixture set `status: "needs_input"` in
state AND in the interrupt payload, so every suppression test passed whichever
source `_shape` read. The real `verdict()` node writes `status: "ok"`, so on a
deployed pause the interrupt payload is the ONLY source. Two one-line mutations
survived the whole suite while restoring the M08 defect. The fixture now uses
`ok`, and **both mutations were applied and confirmed red before being
reverted.**

## What is NOT done

- **Ruling 1 is HALF enforced, and the Playwright spec is no longer evidence
  for it.** `eng-code-reviewer` H1. M08's assertion is on `td.deadline`, which
  `ui/app.js` renders only from `answer_rows` — so it goes green with this fix.
  But the prose still reads *"Because your company makes a 'healthy' claim, you
  must comply … The compliance date remains February 25, 2028"*, rendered under
  the NEEDS HUMAN REVIEW banner. **A green spec must not be read as ruling 1
  closed.** Closing it is 2c's job, and 2c still has no oracle (ruling 6).
- **`make evals` has not been run.** ~118k Opus tokens, ~4.5% of the
  non-adjustable daily cap. See the desk check below for what it is expected to
  show.
- **`make ui-tests` has not been re-run** since the fix.
- **2c** — the prose defect — and its oracle.
- **q10's guard**, and see the sequencing correction below.
- **The two book-keeping defects** in `check_discrimination.py` and
  `golden_questions.json`'s `_scoring_ruling`.
- **q16's instability is fixed but unrated.** Three calls before, three after.

### Desk check, in place of the golden run I have not paid for

`eng-code-reviewer` M4 re-scored every recorded response through the real
`run_evals.check()` with `answer_rows` emptied, across all three recorded cards:

- `needs_input` is exactly q04, q10, q16, q19 in every card — as ruled.
- All four still PASS with rows emptied, in all three cards.
- Across 20 questions × 3 cards, **not one verdict changes.** There is no
  row-dependent pass anywhere in recorded history.

Ruling 3a's regression arithmetic was about withholding the **answer**;
rows-only has no regression surface. **This lowers the risk of the golden run
substantially but does not replace it** — q04 and q19 will take the unpaused
path for the first time in any recorded run.

### A sequencing correction the ruling did not anticipate

`eng-code-reviewer` M5. Ruling 4 sequenced q10's date-bound needles "after the
system fix, or it turns q10 red for a defect it did not cause" — on the
assumption the system fix removes the date. **It does not: the date is in the
prose.** Replayed through the real `check()` against q10's recorded body with
rows suppressed:

```
q10 -> ["forbidden text present: 'February 25, 2028'"]
```

So the order becomes **2c (prose) → then q10's needles**, not
"system fix → needles". Recorded here; the ruling's own sequencing text says
otherwise and should be read against this.

### Known gaps in the new prompt, recorded rather than tuned away

`eng-code-reviewer` M6, and deliberately NOT fixed — the overfitting risk is
already the honest limitation of a prompt tuned against six questions, and
adding clauses to close cases nobody has measured would make it worse:

- A question that is BOTH a third party's reading AND about the asker's own
  obligations — *"our co-packer says we're exempt, are they right?"* — has two
  rules pointing opposite ways and no tie-breaker. Same under-specification
  signature as q16's 2:1 flip.
- A question about a THIRD PARTY's obligations — *"does our supplier have to
  reformulate?"* — satisfies neither FALSE clause, so it classifies sufficient
  and the system answers about a party it has no facts about.
- *"when a rule takes effect"* remains in the TRUE list and q16 (*"…and by
  when?"*) sits on that boundary.

## What broke## What broke

**M08 shipped a latent CI failure, found here by the repo's own test.**
`ui-tests/record_verdict.py` carries a shebang and was committed with mode
`100644`. `tests/test_file_modes.py` reads the **git index**, so while the file
was untracked it was invisible — the full suite passed during M08 for that
reason — and it failed the moment the file was tracked. That is precisely the
scenario that test's docstring describes: seven EXE001 errors latent for eight
days on a branch CI had never linted. Fixed here with
`git update-index --chmod=+x` on that file and on `supervisor_probe.py`.

Worth stating plainly: **M08's own review passes did not catch it**, and the
thing that did was a test written after an earlier instance of the same
mistake.

## Evidence artifacts

- `sme-ruling-pause-suppression.md` — the ruling and the 3b addendum, with the
  seat's decisions recorded inline
- `supervisor_probe.py` — the probe; `--runs N` for stability
- `supervisor-probe.json` / `supervisor-probe-after.json` — before and after
- `src/graph/nodes.py` — the prompt change, with both attempts recorded in the
  `supervisor()` docstring
