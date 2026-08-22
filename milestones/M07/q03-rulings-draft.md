# DRAFT — two rulings owed the human seats on q03

<!-- DRAFT. Written in the engineering seat, for the SME seat (§A) and the PM
     seat (§B) to rule on, amend or reject. Nothing here has been implemented.
     `evals/golden_questions.json` has not been edited and is not proposed for
     edit by the recommended option. -->

**Status: awaiting rulings. Not adopted.**

M05 open thread 7 proposed the fix: *"score the structure, not the characters
— the defect is a TTB proposition carrying a Red No. 3 citation, and the
failing answer's `answer_rows[1].citations` was `[]`, so it is checkable
structurally."*

**That proposal was measured before being built, and it does not work.** So
this draft is not an implementation plan for the thread; it is a report that
the thread's remedy fails, with what is left.

Everything below is reproducible at $0 from four probes committed beside it.

---

## Why this is in front of a seat at all

`unit` has been red since 2026-08-20 on three tests in
`tests/test_replay_exit_codes.py`, all downstream of one FRAGILE finding on
q03. That redness now blocks every PR to `main`, and M07's Done-when requires
Door 1's blocked-merge screenshot to be blocked *for the reason its caption
gives* — a code-owner review requirement, not a red test suite. So the q03
gate is on M07's critical path whether or not it is M07's subject.

This is not a request to make a failure pass. The recommended option leaves
q03's ban, question and expected answer untouched, and leaves the defect
declared and visible.

---

## §A — For the SME seat: what instrument can score q03?

### A.1 The finding, stated so it can be falsified

Run `python milestones/M07/q03_instrument_probe.py`. Three candidate
instruments; all three fail, each for a different and checkable reason.

**Candidate 1 — key the rule on the failure reason.** Dead on a collision:

```
limit-fail  the hedged interrogative q03 wants   -> ["forbidden text present: 'TTB requires'"]
wrong       bare assertion of the same phrase    -> ["forbidden text present: 'TTB requires'"]
wrong       cue present, no `whether`            -> ["forbidden text present: 'TTB requires'"]
wrong       hedges once, then asserts once       -> ["forbidden text present: 'TTB requires'"]
```

The correct answer and three defective ones fail with **byte-identical reason
sets**. No rule that reads the scorer's own output can separate them.

**Candidate 2 — drop the TTB tokens from `must_not_contain`.** Six defective
answers become passes, including B1, the fabricated TTB obligation that got
the M05 rule reverted:

```
wrong  bare assertion of the same banned phrase   -> PASS   <-- NOW A FALSE PASS
wrong  cue present, no `whether` between them     -> PASS   <-- NOW A FALSE PASS
wrong  hedges once, then asserts once             -> PASS   <-- NOW A FALSE PASS
BAR    B1 concessive 'whether exempt or not'      -> PASS   <-- FALSE PASS
BAR    B2 hedge-then-assert, same sentence        -> PASS   <-- FALSE PASS
BAR    B4 banned token inside answer_rows         -> PASS   <-- FALSE PASS
```

`milestones/M05/negation_scope_false_passes.py` is the acceptance bar and this
fails it three times over.

**Candidate 3 — the M05 thread's own proposal, the structural row check.** Run
`python milestones/M07/q03_invariant_probe.py`. Over all 22 recorded q03
answers:

| observation | count |
|---|---|
| answers carrying `answer_rows` | 11 of 22 |
| answers carrying **no** `answer_rows` at all | 10 of 22 (5 of them agent-mode) |
| answers carrying a single row | 1 |
| row-bearing answers whose agency row carries citations | **0 — including both FAILs** |
| answers with the banned literal in the rows | **0** |
| answers with the banned literal in the prose | 2 — both FAILs |

Three things follow, and each one alone is disqualifying:

1. **It cannot discriminate.** Every one of the 11 row-bearing answers has an
   agency row with zero citations. The rule scores the passing and the failing
   answers identically, because the property it reads is the same in both.
2. **It is inert on half the evidence.** Ten recorded answers have no
   `answer_rows` for it to read. Silent inertness is this repo's recurring
   defect — the `pending_review` ban that could not fire, `_shape`'s allowlist
   dropping a field three times.
3. **It reads where the defect has never been.** The banned literal has only
   ever appeared in the prose `answer`.

The M05 thread inferred a general instrument from one field of one card. The
field is real — `answer_rows[1].citations` was indeed `[]` — but it is `[]` in
the passing answers too, so it never carried the information the thread
attributed to it.

### A.2 Why no fourth candidate is coming

The two answers are semantically identical and differ only in how the object
of the hedge is phrased (`milestones/M07/q03-prose-diff.txt`):

- **FAIL:** "I cannot confirm from these sources whether **TTB requires** a
  formula amendment filing, a label re-approval, or any notification…"
- **PASS:** "I cannot confirm from these sources whether **you must separately
  update that formula approval** … or whether that agency has issued its own
  guidance or requirements…"

Same paragraph, same hedge, same zero citations on the agency row, same
`pending_review`, same `real_deadline: none`. The passing run simply did not
happen to phrase the object as *TTB requires*.

Separating that from *"whether exempt or not, TTB requires a revised formula"*
is a judgement about **syntactic scope in natural language**. The 2026-08-12
note predicted it in the mirror direction; the M05 attempt tried to
approximate it with substrings and windows and produced four false passes.
**The ban is not a defective implementation of a good instrument. It is the
wrong kind of instrument for this proposition**, and no amount of it will do.

### A.3 What is actually left

**Option A — admit the one observation the seat has already examined.
(Recommended.)**

`replay_history` re-scores every recorded answer with today's `check()`
(`replay_history.py:148`) and gates on FRAGILE. Add a file of
seat-ruled exceptions: a `(question, sha, answer digest)` triple, each citing
the ruling that created it. A recorded observation matching a triple is
counted as an admitted false fail — printed on every run, never hidden.

Measured, not assumed (`python milestones/M07/q03_admit_probe.py`):

```
BEFORE — as the repo stands
    FRAGILE (gates)   : ['q03']
    replay would exit : 1

AFTER  — admitting q03 at 1f46b92
    FRAGILE (gates)   : none
    REGRESSED (gates) : none
    replay would exit : 0
```

**How this differs from the general admit path M05 §11 refused.** That refusal
was right: *"that mechanism would then be permanently available to silence
real non-determinism, and the first thing it would silence is the detector
that just caught a real defect."* True of a rule. Not true of this, because
**the exception names an artifact, not a rule**:

- It is keyed to the digest of one recorded answer. A new failing answer has a
  new digest and is not admitted, so the detector stays live on exactly the
  thing FRAGILE exists to catch.
- It cannot turn a PASS into anything; it only ever suppresses a verdict that
  is already FAIL.
- It cannot generalise to another question, another sha, or a paraphrase.
- It does not touch `evals/golden_questions.json`, the ban, or the question.
- `check_discrimination.py`'s `LIMIT_FALSE_FAIL` specimen (line 167) stays, so
  `make discrimination` keeps reporting the underlying defect.

**What it costs, said plainly.** It is an override list, and override lists get
used. A future operator can add an entry to green a build, and the only thing
stopping them is the requirement to cite a ruling — which is a convention, not
a mechanism, in a repo with one human (ADR-0005). This is a real reduction in
assurance and should be recorded as one in the ADR, not sold as free.

**Option B — leave it, and rescope M07.** M05's standing ruling. `unit` stays
red, Door 1 cannot be filmed with the intended cause, and SPEC/07's Done-when
has to be amended. Costs nothing in assurance and costs the milestone its
deliverable.

**Option C — redesign q03.** The question's ban is proven non-discriminating,
so an SME could split q03 into a citable-date question and a decline question,
neither carrying an unusable ban. This is a ground-truth edit and squarely the
seat's. **Not recommended now**: q03 passes most runs, the failure is a rare
phrasing, and redesigning a mostly-working trap question under deadline
pressure is how the 2026-08-12 false pass got written in the first place.

### A.4 What the SME seat is asked to rule

1. Is the finding in §A.1 accepted — that the M05 thread's structural remedy
   cannot discriminate, is inert on half the recorded answers, and reads a
   field the defect has never occupied?
2. Is the reading in §A.2 accepted — that q03's ban cannot separate the hedge
   from the assertion by any lexical or structural means available here?
3. A, B or C?

If A: the exception's scope also needs ruling — **one** entry (q03 at
`1f46b92`) is what the measurement covers, and I would not open it wider.

---

## §B — For the PM seat: which SPEC owns this?

Whatever is adopted changes `evals/replay_history.py` — the thing that decides
whether a recorded answer blocks a merge. It has no owning SPEC today.

**Recommendation: SPEC/07.** M07's subject is what blocks a merge and on whose
authority; an admitted-false-fail register is an accountability mechanism with
a named ruling behind each entry, which is the same claim SPEC/07 is making
about CODEOWNERS and the eval gate. It also keeps the change inside the
milestone that has to live with it.

Rejected alternatives:

- **Amend SPEC/05.** Where the thread lives, but M05 is built, measured and
  *not closed and not tagged*. Adding scope to an open milestone to fix a
  problem discovered in a later one makes M05's close criterion recede again.
- **SPEC/02 (evals).** Owns whether answers are correct. This is about what
  gates a merge, which is not the same question.
- **No SPEC — treat it as a scorer bug fix.** It is not a bug fix. It creates a
  mechanism that can weaken a gate, and ADR-0003's premise is that those are
  visible and owned.

Adopting into SPEC/07 means adding an item to SPEC/07 and to its Done-when.
`pm-spec-reviewer` has not yet run on that diff and will before anything lands.

**The PM seat is asked to rule:** SPEC/07, an M05 amendment, or elsewhere — and
whether M07's Done-when absorbs it.

---

## Probes behind every claim here

| file | claim it settles | cost |
|---|---|---|
| `q03_rows_survey.py` → `q03-rows-survey.txt` | the real `answer_rows` shape, all 22 recorded answers | $0 |
| `q03_invariant_probe.py` → `q03-invariant-probe.txt` | the structural remedy cannot discriminate and is inert on 10/22 | $0 |
| `q03_prose_diff.py` → `q03-prose-diff.txt` | the passing and failing answers differ only in the phrasing of the hedge | $0 |
| `q03_instrument_probe.py` → `q03-instrument-probe.txt` | reason-keying collides; dropping the ban leaks 6 | $0 |
| `q03_admit_probe.py` → `q03-admit-probe.txt` | admitting one observation clears the gate, and reaches nothing else | $0 |
