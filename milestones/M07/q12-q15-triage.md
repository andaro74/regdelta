# sme-eval-triage on q12 and q15 — 2026-08-22

Run because the eval gate went live in CI (PR #17) and now blocks every merge
at 18/20. CLAUDE.md routes a golden-set failure through `sme-eval-triage` and
**stops** for the SME seat. This is the triage; **no ground truth has been
edited**, and the seats' decisions are listed at the end.

| id | class | ground truth | who rules |
|---|---|---|---|
| q12 | model/system defect, persistent | **UPHELD** — the model is wrong on the law | SME (a token tightening only) |
| q15 | **retrieval defect** | **VERIFIED correct** against primary sources | Engineering — nothing in ground truth moves |

Neither is WORLD CHANGED. Neither is a regression: both fail in every recorded
run across three milestones.

## q12 — the ground truth is right and the model is wrong

The question asks whether "not final and might never take effect" was a fair
reading of the Red No. 3 removal in mid-2025. Ground truth says it was. The
model answered "No, that was not a fair reading."

Three primary sources, each checkable:

1. **21 U.S.C. 371(e)(2)**: "Until final action upon such objections is taken
   by the Secretary under paragraph (3), the filing of such objections **shall
   operate to stay the effectiveness** of those provisions of the order to
   which the objections are made." The stay runs against *effectiveness*, and
   it runs *until final action*.
2. **90 FR 4628** (doc 2025-00830) conditions its own effectiveness: effective
   as shown in the DATES section, **except as to any provisions that may be
   stayed** by the filing of proper objections.
3. **91 FR 50475** (doc 2026-15920, 2026-08-05): "this document constitutes
   **final action on the objections**". Final action therefore did not exist in
   mid-2025 — and FDA describes continuation of the stay as an outcome that was
   available, not a formality.

So a mid-2025 adviser saying "not final" was using the statute's own
vocabulary. The model's own answer concedes the dates were "suspended" and
"unconfirmed during the stay period" and that 91 FR 50475 is the final action —
which is the ground truth's position with the verdict sentence inverted on top
of it.

The one defensible sliver: "not final" is wrong as to *document type* — 90 FR
4628 is captioned "Final amendment; order". A complete answer says both halves.
The model said neither; it denied fairness outright.

**q12 is a GOOD question.** Every other token scored clean — all three dates,
both stay groups, the citation — so the instrument isolated the disputed
proposition exactly.

### The latent false pass, and the only change proposed

`check()` is a case-insensitive substring test (`evals/run_evals.py:442-460`).
**Six of the nine tokens in q12's first accept group are substrings of their own
negation**, which contradicts what that group's 2026-08-15 ruling claims for it:

```
  safe   'was fair'                 inside 'was not fair'
  LEAKS  'fair at the time'         inside 'was not fair at the time'
  safe   'was reasonable'           inside 'was not reasonable'
  LEAKS  'reasonable at the time'   inside 'was not reasonable at the time'
  LEAKS  'accurate at the time'     inside 'was not accurate at the time'
  safe   'was a fair reading'       inside 'was not a fair reading'
  LEAKS  'fair reading at the time' inside 'not a fair reading at the time'
  LEAKS  'fair then'                inside 'was not fair then'
  LEAKS  'correct at the time'      inside 'was not correct at the time'
```

**The recorded failing answer missed a false PASS by one word.** It wrote "was
not a fair reading **in mid-2025**"; had it written "at the time", q12 would
have scored PASS while asserting the exact opposite of ground truth.

VERIFIED, not hand-read. Triage flagged its own finding as unverified — "a
hand-simulated token is not a ruled token" — so it was replayed
(`q12_token_probe.py`, output in `q12-token-probe.txt`):

- the leaking set is **exactly** the proposed deletion set
- across **12 recorded q12 answers**, deleting them changes **0 verdicts**

It is a strict tightening. **It does not make q12 pass**, and it is not
proposed in order to.

### Explicitly NOT proposed for q12

- No change to the substance, the required dates, `must_cite_any`, or the
  "the 2025 reading WAS fair" ruling. Upheld on sources.
- **No `must_not_contain` ban** on the negation. A correct answer says "it was
  fair then and is not now", so a ban would be reproduced by the correct
  answer — a defect, not a guard.
- No relaxation of the `February 18, 2025` strictness flag. It did not fire.

## q15 — ground truth verified; this is retrieval

**89 FR 106064 DATES, verbatim:** "This rule is effective February 25, 2025.
The compliance date of this final rule is **February 25, 2028**." Title: *Food
Labeling: Nutrient Content Claims; Definition of Term Healthy*, doc
2024-29957, published 2024-12-27.

The effective/compliance distinction — the thing this project was burned on —
holds cleanly. The **effective** date moved to April 28, 2025 (90 FR 10592, doc
2025-03118). The **compliance** date of February 25, 2028 was untouched. So
q15's `must_contain` is correct and **no golden-set change is proposed at all**.

**It is retrieval, and there are two independent proofs.**

1. The document is in the corpus. Live registry scan of
   `regdelta-core-RegistryTableF2430F90-2FKHSM738R7Y`: `DOC#2024-29957` is
   present with citation `89 FR 106064`, chunked from `2024-29957#0000`.
2. It was retrievable for other questions **in the same run**. At 95235d9,
   q01, q05, q07, q16, q17 and q18 all passed, and each cites 89 FR 106064 or
   produces February 25, 2028. Six hits and one miss, same index, same run.

The model said so itself — "The sources provided to me do not contain any
document addressing the healthy nutrient content claim regulation" — with
`status: pending_review`, `confidence: 0.20`, and an empty citations array on
the second row. **That is the honesty machinery working correctly on top of a
retrieval failure**, and it must not be "fixed" by raising the confidence
threshold: that would convert a visible retrieval defect into a silent wrong
answer.

Hypothesis for engineering, offered as testable and NOT as a finding:
`src/graph/nodes.py:345` embeds the raw query once, with no filters and
`NAIVE_TOP_K = 8`, and there is no query decomposition in `src/retrieval/`.
q15 is the only question naming two unrelated rules in one stem; eight slots,
and the Red No. 3 half plausibly takes all of them. Falsifiable: re-run q15
with k raised, or with the stem split, and see whether `2024-29957#*` appears.

## The thing triage did not raise, and it is the bigger one

`evals/run_evals.py:694` — **`return 0 if passed == total else 1`**. The eval
gate's bar is 20/20 with no partial credit, and this repository has never been
at 20/20 in any recorded run. So the gate, the moment it was switched on,
became un-satisfiable rather than strict.

That is inconsistent with how this project already gates elsewhere:
`replay_history.py` gates `unit` on **regression against recorded history**,
with an admission register for observations a seat has ruled on (ADR-0015).
Two gates in one repo with two different theories of what acceptable means,
and only one of them has ever been examined.

**This is not a proposal to weaken a trap question**, which ROLES.md forbids
the SME seat from doing. It is a question about the eval gate's exit criterion,
which SPEC/07 item 1 owns and which has never been looked at because the gate
had never run. Raised, not decided.

## What the seats are asked to rule

1. **SME:** adopt the six-token deletion in q12's first accept group?
   Strict tightening; verified to move no recorded verdict; does not make q12
   pass. If adopted it needs its own PR carrying the ruling, then a second PR
   citing it — the `ruling-cited` gate applies to `golden_questions.json`.
2. **SME/PM:** is 20/20 the right bar for the eval gate, or should it gate on
   regression the way `unit` already does?
3. **Engineering:** q15's retrieval defect and q12's answer-composition defect
   are logged. Neither is M07 scope.
