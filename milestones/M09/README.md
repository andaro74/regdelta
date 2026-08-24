# M09 — The paused-run defect: ruled, measured, and half fixed. **IN FLIGHT.**

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

**Before / after, same probe, same controls:**

| id | before | after | wanted (ruling 3b) |
|---|---|---|---|
| q04 | pauses | **does not pause** | does not pause ✓ |
| q10 | pauses | **pauses** | pauses ✓ |
| q16 | **unstable 2:1** | **pauses, stable** | pauses ✓ |
| q19 | pauses | **does not pause** | does not pause ✓ |
| q18 (control) | sufficient | sufficient | unchanged ✓ |
| q01 (control) | sufficient | sufficient | unchanged ✓ |

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

## What is NOT done

**The suppression fix itself.** The graph still synthesises a full answer once
`profile_sufficient` is false, `_shape` still copies `answer_rows`
unconditionally, and the page still renders both. **M08's failing Playwright
spec still fails**, and correctly.

Ruling 3a blocked that fix until the over-firing was resolved. **That block is
now lifted** — q04, q16 and q19 no longer depend on text a suppression would
remove, because q04 and q19 no longer pause at all.

What it needs before landing:

1. the fix, per ruling 4's ordering: **the graph, for `needs_input` only** —
   not `pending_review`, where the draft is the artifact under review;
2. `make evals` — a full golden run to confirm no regression. **≈118k Opus
   tokens, ~4.5% of the non-adjustable daily cap.** That is the real
   verification and it has not been paid for;
3. `make ui-tests` — one run, to watch M08's spec go green;
4. `eng-code-reviewer` on the graph diff.

Also still open, from the ruling:

- **2c** — the prose asserting the asker's conduct. A separate correctness
  defect, with an oracle owed (ruling 6).
- **q10's guard** — date-bound needles, replayed through `check()` first, after
  the fix.
- **The two book-keeping defects** in `check_discrimination.py` and
  `golden_questions.json`'s `_scoring_ruling`.
- **q16's instability is fixed but unrated.** Three calls established it and
  three calls now show it stable. That is not a stability measurement.

## What broke

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
