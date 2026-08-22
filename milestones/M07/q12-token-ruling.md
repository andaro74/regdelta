# SME-SEAT RULING — 2026-08-22: q12's first accept group loses six tokens

**Status: ADOPTED.** This ruling authorises a change to
`evals/golden_questions.json`, question **q12**, `must_contain_any` group 1
only. It rules on the file `evals/golden_questions.json`.

Ruling, with sources — not a signature. The change it authorises is a strict
tightening, and the verification is in this repository rather than in my
say-so.

## What is being changed

Delete six tokens from q12's first `must_contain_any` group. Keep three.

```
KEEP    'was fair'
DELETE  'fair at the time'
KEEP    'was reasonable'
DELETE  'reasonable at the time'
DELETE  'accurate at the time'
KEEP    'was a fair reading'
DELETE  'fair reading at the time'
DELETE  'fair then'
DELETE  'correct at the time'
```

Nothing else in q12 changes: not the required dates, not `must_cite_any`, not
`must_not_contain`, not the note's substantive ruling that the 2025 reading
**was** fair at the time.

## Why — the group admits the answer it exists to reject

`check()` is a case-insensitive substring test
(`evals/run_evals.py`, `n.lower() in low`). Six of the nine tokens are
substrings of their own negation, so an answer asserting the **opposite** of
ground truth satisfies the group:

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

**This is not hypothetical, and it is not distant.** The recorded failing
answer at 95235d9 opens *"No, that was not a fair reading **in mid-2025**"*.
Had it written *"at the time"* — the same claim, four words different — q12
would have scored **PASS** while denying exactly what the question was written
to test.

That group was added by the 2026-08-15 scoring ruling, which recorded the
defect it was fixing as: *"a wrong answer opening 'That was never a fair
reading' scored PASS"*, and stated that the new tokens were chosen *"so that
none is a substring of its own negation"*. **Six of them are.** This ruling
corrects that ruling on its own stated terms; it does not overturn it.

## Verified, because a hand-read is not a ruling

`sme-eval-triage` found this by reading, and flagged its own finding: *"a
hand-simulated token is not a ruled token."* So it was replayed —
`milestones/M07/q12_token_probe.py`, output in `q12-token-probe.txt`:

1. The leaking set computed mechanically is **exactly** the six proposed for
   deletion. Not a superset, not a subset.
2. Replayed across **all 12 recorded q12 answers** in `evals/history/`,
   deleting them changes **0 verdicts**.

So it removes accept surface and flips nothing that exists. It is a tightening
in the strict sense.

## What this does NOT do, stated because it is the obvious suspicion

**It does not make q12 pass.** q12 fails today because the model asserts the
2025 reading was *not* fair, and it will fail after this change for the same
reason. This ruling makes the question harder to satisfy, not easier. Nothing
here greens a build, and no expected answer moved.

**No `must_not_contain` ban is added** on "was not a fair reading" or its
relatives, and this was considered and rejected. A correct answer to q12 says
*"it was fair then and is not now"* — so a ban on the negation would be
reproduced by the correct answer, which this file's own rule (5) calls a defect
rather than a guard. The tightened accept group already fails the negation
without one.

**The `February 18, 2025` strictness flag is not relaxed.** It did not fire;
the model produced all three dates. The flag stays as written.

## The substantive ruling behind it, upheld on sources

The note's claim that the mid-2025 reading was fair is **upheld**, against
three primary sources a reader can check:

- **21 U.S.C. 371(e)(2)**: "Until final action upon such objections is taken by
  the Secretary under paragraph (3), the filing of such objections shall
  operate to **stay the effectiveness** of those provisions of the order to
  which the objections are made."
- **90 FR 4628** (doc 2025-00830) conditions its own effectiveness: effective
  as shown in DATES **except as to any provisions that may be stayed** by the
  filing of proper objections.
- **91 FR 50475** (doc 2026-15920, 2026-08-05): "this document constitutes
  **final action on the objections**" — so final action did not exist in
  mid-2025, and FDA describes continuation of the stay as an available outcome.

The model is wrong, and its own answer concedes the premises: it states the
dates were "suspended" and "unconfirmed during the stay period", then inverts
the verdict sentence on top of them. q12 is a **good** question — every other
token scored clean, which is what isolated the disputed proposition.

## How this lands

`evals/golden_questions.json` is an SME-owned path, so `ground-truth-gate /
ruling-cited` refuses a pull request touching it unless it cites a ruling that
is **already on main** and names the file. This ruling therefore lands in its
own pull request, and the token deletion follows in a second one carrying
`RULING: milestones/M07/q12-token-ruling.md`. That is Door 2's path, run on a
real change rather than a staged one.
