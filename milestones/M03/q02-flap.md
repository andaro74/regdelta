# q02 flaps, and its passing mode asserts the opposite of its ground truth

Measured 2026-08-15 on `585a95f`, S3 Vectors tier, agent mode, against the
live corpus (49 FR documents). This sits beside
`evals/history/585a95f-s3vectors-full.json`, which records **10/10**, because
that card on its own is misleading and this file is the reason.

## The measurement

Ten consecutive runs of q02 alone through `POST /query?mode=agent`, scored
with the real `run_evals.check()`:

| runs | q02 passed |
|---|---|
| first batch of 4 | **1 / 4** |
| second batch of 6 (probing for the passing text) | 1 hit on attempt 1 |

**q02 passes roughly one run in four.** The recorded 10/10 is a lucky draw
from that distribution, not a reproducible result. The immediately preceding
card at `fd98d64` scored 9/10 with q02 as the single failure, and the run
before that — against a 34-document corpus — did the same.

## Why it passes when it passes

q02's accept group is `["not adulterated", "may remain", "manufactured
before"]`. The passing runs match on **`manufactured before`**, in this
sentence:

> "The sources do not provide an explicit FDA enforcement-discretion statement
> or transition period for products **manufactured before** the effective date
> but still in commerce after it."

That is the answer stating it **cannot confirm** a sell-through allowance. The
question's ground truth is the opposite: that inventory manufactured before the
effective date **is not** adulterated. The substring scorer cannot tell the two
apart, so the question's only passing mode is an answer that contradicts what
it exists to verify.

In the failing runs the model says the same thing in different words —
"regardless of when it was manufactured" — and scores zero. The score is
tracking phrasing, not correctness, in **both** directions.

## This is the q07 defect, not a new one

The SME ruling of 2026-08-12 found exactly this shape in q07 and named it as a
defect neither the author nor the first review caught: the question "could not
distinguish true from false answers in EITHER direction ... It scored a stable
0/3 while being unable to measure the thing it existed to test." q02 is the
same failure with a flap on top.

There is a second, independent defect, found first: q02 requires an answer the
corpus cannot support. All three accept tokens return **zero hits** across the
live corpus, as do `manufactured prior`, `existing stocks` and `sell-through`.
The domain skill does state the inventory rule — but a rule the corpus cannot
cite is not a rule this system may assert, which is the whole holding of the
q03 ruling.

## What was deliberately not done

The question was not edited and the verdict prompt was not tuned to emit the
phrase. Tuning would be worse than the failure: it would make the model assert
a sell-through exemption it cannot cite, which is the q03 false pass rebuilt
with a milestone deadline as the motive.

## What this needs

An `sme-eval-triage` pass and a human ruling from the SME seat, with two
questions to answer and one consequence to accept:

1. Is the inventory rule citable from any document in the corpus? If not, the
   requirement is uncitable and the accept group cannot stand as written.
2. If it is retained in some form, `manufactured before` must go — it matches
   the negation of the intended answer, so it cannot discriminate.
3. Either way **SPEC/03's "Done when" is not met.** The bar is `>=80% overall
   AND 100% on q01-q04`. Overall passes; the trap set does not, and a 10/10
   card that turns on a false pass does not change that.
