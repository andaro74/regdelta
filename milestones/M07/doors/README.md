# The three doors, run for real — 2026-08-22

SPEC/07's Done-when. Every door below is a pull request that actually existed
on `andaro74/regdelta`, with its checks run by CI rather than described.

| door | PR | outcome |
|---|---|---|
| 1 — engineer edits ground truth | [#20](https://github.com/andaro74/regdelta/pull/20) | **BLOCKED** by `ruling-cited`, closed unmerged |
| 2 — the right path | [#17](https://github.com/andaro74/regdelta/pull/17) → [#18](https://github.com/andaro74/regdelta/pull/18) | **MERGED**, both CLEAN |
| 3 — IAM widened inside a real fix | [#21](https://github.com/andaro74/regdelta/pull/21) | **BLOCKED**, two HIGH findings, closed unmerged |

Doors 1 and 3 were staged and are marked as staged **in their own diffs**, not
only in their descriptions. Door 2 was **not staged**: it is the milestone
delivering itself, and it happened before anyone thought of filming it.

---

## Door 1 — engineering cannot decide what CORRECT means

**The premise is live, not invented.** `golden-set` was reporting q12 failing on
its accept group. The model's answer contains the words "a fair reading", so
adding the token `"fair reading"` makes q12 pass. One token, one line, green
build.

It is also the *exact* false-pass the SME seat had closed **earlier the same
day** in [#18](https://github.com/andaro74/regdelta/pull/18) — the model's answer
is "No, that was **not a fair reading** in mid-2025", and `"fair reading"` is a
substring of it. So the door is not a strawman: it is a real engineer
reintroducing a real hole that a real ruling had just removed, for the most
ordinary reason there is.

### What CI said (`door1-gate-output.txt`, verbatim)

```
This pull request changes what CORRECT means:

  evals/golden_questions.json

BLOCKED: no ruling cited.

  Add a `RULING: <path>` trailer to the commit that makes
  the change, naming a ruling document that is ALREADY on
  main. Register entries cite theirs in their own `ruling`
  field instead.

  Engineering may not decide what correct means (ROLES.md,
  CLAUDE.md). Route the question through sme-eval-triage and
  land the ruling first, in its own pull request.
```

### The merge state (`door1-state.json`)

```
ruling-cited  FAILURE
unit          SUCCESS      <-- so the block is attributable
golden-set    FAILURE      <-- see the finding below
mergeStateStatus: BLOCKED
```

### And the bypass (`bypass-at-door1.json`), which is the clause that matters

```
bypass_actors           []
current_user_can_bypass 'never'
```

`unit` passing is what makes this evidence rather than a screenshot. This
milestone opened by finding a red `unit` captioned as an org chart
(`milestones/M07/baseline/`); here the ground-truth gate is the only governance
check failing, and the merge button offers the repository owner no override.

**What it does NOT show.** That some *other* person was prevented. There is no
other person. It shows that the rule binds the one who owns the repository, and
that satisfying it requires a document that cannot be written inside the pull
request it is blocking.

### A FINDING FROM THIS RUN, and it is a defect in M07's own work

`golden-set` also failed, and not for the reason the door was designed to show.
The scorecard (`door1-scorecard.md`):

```
KNOWN, not gating (1): q15
REGRESSION (1): q03
```

Two things happened. **q12 passed** — the false pass, demonstrated live, which is
the door working. And **q03 regressed**, which is not.

q03 is the FRAGILE question: `replay_history.py` classifies it as "agent answers
disagree across runs", and the admitted-false-fail register (ADR-0015) exists
precisely so one recorded q03 failure does not gate a merge. **`run_evals.py`'s
new `gate_verdict()` does not consult that register.** So the PM ruling of
2026-08-22 (`eval-gate-bar-ruling.md`) claims the two gates now share one theory,
and they do not: `unit` admits a ruled q03 observation and `golden-set` does not.

**Consequence: a flaky question intermittently blocks merges through the eval
gate.** It did here, on the first pull request after the bar changed.

This is carried as **OPEN**, not fixed at the end of the session that created it.
Making `gate_verdict()` consult the register is not a small change — the register
is keyed per recorded artifact (sha + scored digest) and a live CI run has no
recorded artifact to match — and the ruling it would amend is hours old. It is a
seat decision with a measurement already attached, which is the right shape to
hand over.

---

## Door 2 — the right path, and it was not staged

Door 2 is the only door that needed no setup, because the milestone had already
walked it. `evals/admitted_false_fails.json` and `evals/golden_questions.json`
are SME-owned, and M07 had to change both.

| | |
|---|---|
| [#17](https://github.com/andaro74/regdelta/pull/17) | carries `milestones/M07/q12-token-ruling.md`. Touches no SME-owned path, so `ruling-cited` passes trivially. **MERGED CLEAN.** |
| [#18](https://github.com/andaro74/regdelta/pull/18) | changes `evals/golden_questions.json`, carrying `RULING: milestones/M07/q12-token-ruling.md`. **MERGED CLEAN.** |

The same shape ran once before, for the register itself: the ruling in
[#15](https://github.com/andaro74/regdelta/pull/15), the change in
[#16](https://github.com/andaro74/regdelta/pull/16).

**The triage is the part worth showing**, not the merge. `sme-eval-triage` was
run on q12 and q15 (`milestones/M07/q12-q15-triage.md`) and **upheld ground truth
on both** — q12's model is wrong on 21 U.S.C. 371(e)(2), and q15's expected
compliance date is quoted verbatim from 89 FR 106064 with the miss being
retrieval. Not one expected answer moved. The seat's output was a ruling with
citations a reader can falsify, and #18 merged because that document existed on
`main` and named the file — not because anyone approved it.

---

## Door 3 — the engineer owns every line the AI wrote

A `resources=["*"]` widening on the `regdelta-ci-eval` role, hidden inside a
plausible pagination fix. `security-reviewer` returned **two HIGH findings**
(full text on [#21](https://github.com/andaro74/regdelta/pull/21)):

- **HIGH** `core_stack.py:1138` — `resources=["*"]` gives unrestricted
  `Scan`/`Query`/`GetItem` over **every DynamoDB table in the account**. The
  role is assumable by any pull request in a public repo, and `golden-set` runs
  PR-branch-controlled code with those credentials in the environment. Whatever
  the policy grants, arbitrary code in a pull request spends.
- **HIGH** `core_stack.py:1136-1137` — three actions the caller never makes.
  `fingerprint()` calls `table.scan` and nothing else.

It also dismantled both stated justifications and made the point the door
exists for: **neither would require `resources=["*"]` even if it were true.**

### The reviewer found something that was not staged

> `e590c7f` is `1 file changed`. `src/shared/corpus.py` **already paginates on
> `main`**, unchanged. The bug the commit claims to fix was already fixed, so the
> commit contains *only* the IAM widening.

The diff was written to hide a widening behind a plausible fix. The reviewer
found that the plausible fix **does not exist at all** — the justification is
fabricated. That is a better Door 3 than the one designed, and it is recorded as
**found, not intended**.

### Defence in depth

`unit` **FAILED** on this PR (`door3-state.json`), on the two tests written for
this role at M07:

```
test_it_holds_exactly_one_statement_granting_exactly_one_action
test_the_grant_reaches_the_registry_table_and_no_index   AssertionError: "*"
```

So the diff was blocked **mechanically as well as by review**, with the bypass
gone. And `golden-set` **SKIPPED** behind the failed `unit` — which is why Door 3
cost $0, and is also a live instance of the skip-does-not-block finding in
`milestones/M07/skipped-check.txt`.

---

## What the three doors establish together

- **Door 1** — the rule binds the repository owner, and asks for evidence rather
  than a signature.
- **Door 2** — the path it forces is walkable, and this project walked it four
  times before filming it.
- **Door 3** — the review seat catches what the tests would not have described,
  and the tests catch what a review might have waved through.

And one thing they establish that was not planned: **the gate found a defect in
the gate.** Door 1's run surfaced the q03/register inconsistency in a ruling made
the same day. That is the demo's actual claim — not that the controls are
perfect, but that they are the kind of thing that can be caught being wrong.
