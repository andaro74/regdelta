# SME-SEAT RULING — q11 and q18: two accept tokens, seven negation bans

**Status: ADOPTED** — human SME seat, 2026-09-03. Drafted in the engineering
seat and adopted unamended; read the verification in §5 rather than the
adoption. It rules on `evals/golden_questions.json`, questions **q11** and
**q18** only. The token change it authorises has NOT been made and must arrive
in a separate pull request citing this document, per §9.

Ruling, with sources — not a signature. The verification is in this repository
rather than in anyone's say-so.

**It is a STOPGAP and says so.** The durable fix is M05 open thread 7 — *score
the structure, not the characters* — and §6 explains why that is not what this
ruling does.

## 1. One ruling, because it is one defect

Both questions failed in the same way on 2026-09-03: **a correct answer,
correctly cited, phrased outside a list of accepted substrings.** Filing them
separately would record two incidents where there is one property.

| | q18 | q11 |
|---|---|---|
| Run | PR #28 and PR #29 | PR #29 |
| Status | `ok`, confidence 0.92–0.95 | `ok`, confidence 0.97 |
| Accept tokens in the group | 11 | 14 |
| Previously widened | yes, after `2cea737` | — |
| Recorded passes before this | 12 | passed on PR #28, 90 min earlier |

q11 is the sharper evidence: it **passed at 03:22 UTC and failed at ~04:55
UTC**, with no change between the runs to prompts, retrieval or graph nodes —
PR #29 alters printing and a workflow artifact and nothing else. So the model's
phrasing varies run to run, and these groups are narrow enough that variation
flips a verdict.

## 2. What the system actually said

**q18** — four observations (three probe runs 2026-09-03, cache bypassed both
ways, plus the PR #29 CI run), all opening identically:

> "**Yes**, your shelf-stable lentil soup labeled 'healthy' **is directly
> affected** by the updated definition of the term 'healthy' under the final
> rule published at 89 FR 106064 (Doc. 2024-29957, published 2024-12-27)."

The group contains `is affected`. `"is affected" in "is directly affected"` is
`False`. **One adverb.** And it is the same sentence as the `2cea737`
specimen — "…labeled 'healthy' **is affected** by the updated definition…" —
for which `is affected` was added. The widening held 12 runs and then lost to
an adverb.

**q11** — the PR #29 CI run, recovered from the scorecard artifact that PR
added:

> "**Your colleague is incorrect that the deadline moved.** Here is what
> happened: 1. Original order (90 FR 4628, published 2025-01-16, doc
> 2025-00830): FDA revoked the color additive listings for FD&C Red No. 3. The
> order set two effective dates: **January 15, 2027** for food uses… and
> January 18, 2028 for ingested drug uses…"

It denies the move, gives the right date, and cites the right documents. It
phrases the denial by negating the colleague's claim rather than by asserting
any of the fourteen listed forms. `must_contain` (`January 15, 2027`),
`must_cite_any` and the SECOND accept group (`91 FR 50475` / `2026-15920`) all
passed; only group 1 failed.

**A LIMITATION, STATED NOT PAPERED OVER.** For q11 only the first **420 of
1,780 characters** exist — the card's excerpt cap applies to the artifact too.
The proposed token is in the first sentence, so the fix is sound, but I cannot
rule out that the unseen tail contains something tripping a proposed ban. The
two-budget fix — bounded excerpt in the card, full answer in the artifact —
is owed and named in §7.

An earlier draft of this ruling's probe **extrapolated q11's tail and wrote in
`confirmed both dates`**, an accept token, which made the probe report `PASS`
for an answer CI had failed. Recorded because a ruling resting on text the
system never emitted is precisely what this mechanism exists to prevent, and
because it was caught by the probe disagreeing with CI rather than by care.

## 3. Neither expected answer moves

**q18 — the healthy claim.**
- **89 FR 106064**, doc **2024-29957**, published 2024-12-27. DATES, verbatim:
  "This rule is effective February 25, 2025. The compliance date of this final
  rule is February 25, 2028."
- **90 FR 10592**, doc **2025-03118**, delays the **effective** date to
  2025-04-28. The compliance date is untouched.
- Revised **21 CFR 101.65(d)(3)** chapeau: "You may use the term 'healthy' …
  **if** the food meets the criteria of one or more of the following
  paragraphs". A label bearing the claim is inside the paragraph by bearing it.
- No exemption by category, company size or grandfathering. The only carve-outs
  sit inside the **(d)(4) recordkeeping** duty — records, not the definition.
- The one favourable pathway, **(d)(3)(i)** (solely listed foods, "no other
  added ingredients except for water"), is defeated by added salt in any
  shelf-stable soup — and qualifying under a new criterion is still being
  governed by it.

**q11 — the Red No. 3 stay.**
- **21 U.S.C. 371(e)(2)**: filing objections "shall operate to **stay the
  effectiveness**" of the provisions objected to. A stay **suspends**; it does
  not toll, so there is no day-for-day extension.
- **90 FR 4628**, doc **2025-00830**, set 2027-01-15 (food, 21 CFR 74.303) and
  2028-01-18 (ingested drug, 21 CFR 74.1303).
- **91 FR 50475**, doc **2026-15920**, 2026-08-05: final action on the
  objections, lifting the stay and **confirming both dates** — recorded as
  `scope=dates_confirmed`, predicate CONFIRMS, never SUPERSEDES (ADR-0007).
- So a ~17.5-month suspension (2025-02-18 → 2026-08-05) left 2027-01-15 at
  2027-01-15. The stem's premise is true; the inference from it is false.

## 4. What would change

`must_contain_any` group 1 — **one token each**:

```
q18   ADD  'is directly affected'
q11   ADD  'colleague is incorrect'
```

`must_not_contain` — **the compensating tightening, seven bans**:

```
q18   ADD  'is not affected'         'are not affected'
           'is not directly affected'  'does not apply to your'
q11   ADD  'colleague is correct'    'colleague is right'
           'the deadline did move'
```

Nothing else changes: not `must_contain`, not `must_cite_any`, not
`expect_status_any`, not either second accept group, not the notes.

## 5. Verified, because a hand-read is not a ruling

`milestones/M08/q11-q18_token_probe.py`, output in
`q11-q18-token-probe.txt`. It runs the real `run_evals.check()` against the
real `check_discrimination` specimens — no API, no cost:

1. **No accept token passes inside its own negation**, the two proposed
   included. Checked because the 2026-08-22 q12 ruling found six of nine
   leaking in a ruling that had claimed none did.
2. **Both observed answers go FAIL → PASS**, and the `before` line reproduces
   CI's failure message verbatim.
3. **All 16 discrimination specimens keep their verdicts** — 5 CORRECT still
   pass, 11 WRONG still fail, including q11's "tolling, avoids every banned
   verb" and q18's "denies applicability — the substring trap".
4. **No proposed ban fires on any CORRECT specimen.**

Worth recording from (3): q11's specimen set already contains "negation-only
phrasing, no 'unchanged'" as a CORRECT case, and it passes. The live answer
still used a negation form the specimen set did not anticipate. That is the
2026-08-15 lesson — *"a specimen set is only as adversarial as the imagination
of whoever wrote it"* — arriving for the third time.

## 6. Why this is a stopgap, and what the real fix is

**The set of wrong answers that can pass shrinks**, so the change is
net-hardening: seven bans against two tokens. Today both questions catch a flat
denial only by the *absence* of an accept token, which is why q18's signature
was ambiguous enough to need three live Bedrock calls to diagnose. With the
bans, a wrong answer trips a named ban and prints it.

**But it will not hold.** The numbers are against it: **216 accept tokens
across 31 groups in 18 of 20 questions** are already written; q18's group had
11 and had already been widened once; q11's had 14. Both failed anyway.
Historically a marginal token buys about twelve runs.

**The variation space is unmeasurable today**, which is why nobody can say how
many tokens would be enough. `evals/history/` stores `id`, `pass` and `fails`
and no answer text, so every estimate — including the one above — is inference
from four observations. **PR #29 changes that from today forward**; it is
blocked by these very failures, which is the main reason to adopt a stopgap
rather than wait.

**The durable fix is M05 open thread 7: score the structure, not the
characters.** The evidence is already in the response and needs no wording.
q18 returned `rows=1` with `product: "shelf-stable lentil soup labeled
'healthy'"` and `real_deadline: "2028-02-25"`; q11 returned rows carrying
2027-01-15. A "not affected" answer has no such row. Asserting on
`verdict_rows` is immune to adverbs. That is a SPEC change through
`pm-spec-reviewer`, and PR #29's recorded answers are the evidence it should be
argued from.

## 7. What this does NOT do

- **It does not fix the brittleness.** The next unanticipated adverb fails the
  next question. §6 is the answer, not this.
- **It does not touch q12 or q15.** Those are KNOWN, never passed, and their
  defects are real: q12's PR #29 answer opens *"No, that was not a fair reading
  in mid-2025"* — the model asserting the opposite of ground truth. q15
  returned `status='pending_review'`, confidence 0.25, citing Red No. 3
  documents for a healthy-claim question — the retrieval-decomposition defect
  of `milestones/M07/q12-q15-triage.md`.
- **It does not fix the excerpt budget.** The card and the artifact share a
  420-character cap, which is why q11's tail is unavailable to this ruling. The
  artifact has no 3,000-character constraint and should carry the full answer.
  A small follow-up to PR #29.

## 8. Open question for the seat

I verified the world against ecfr.gov and federalregister.gov only. **I did not
check for a judicial stay or vacatur** of 2024-29957 or 2025-00830. A stay
would change the ANSWER rather than the assertion, which is a larger finding
than this ruling, and a complete ruling should close it.

## 9. How this lands

`evals/golden_questions.json` is SME-owned, so `ground-truth-gate /
ruling-cited` refuses a pull request touching it unless it cites a ruling
**already on main**:

1. This document lands on `main` in its own pull request, **Status: ADOPTED**,
   with whatever the seat amends.
2. The token change follows in a second pull request whose commit carries
   `RULING: milestones/M08/q11-q18-token-ruling.md`.
3. PR #28 and PR #29 unblock. #29 merges and begins recording answers, which is
   what makes §6's SPEC change arguable from data rather than from four
   observations.
