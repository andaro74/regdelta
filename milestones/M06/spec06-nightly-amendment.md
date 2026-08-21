# DRAFT — proposed amendment to SPEC/06's Observability section

**Status: DRAFT for the PM seat. Not adopted.** One change, already
implemented, split out of `spec06-disposition-amendment.md` at that document's
third review pass.

**Why it is its own document.** It was Change 8 of the Tier B disposition
amendment, whose title is "amendment to SPEC/06's *Tier B disposition clause*".
This change amends the **Observability** contract instead: it rewrites
`SPEC/06:6-8` and deletes a branch of it. `pm-spec-reviewer` blocked on the mix
(blocker B2) — a ruling on the disposition clause should not silently carry a
change to what the nightly job does — and recommended the split. Engineering had
no preference and took the reviewer's.

Nothing here depends on the disposition amendment, and vice versa. The two can
be ruled on separately and in either order.

---

## The clause today

`SPEC/06:6-8`:

> Nightly eval Lambda: full set if hot tier up, else reduced graph-logic set;
> pass-rate metric + regression alarm.

## The finding

**The full set nightly is not affordable, and the coupling is the wrong shape.**

Twenty golden questions is **$0.95 and 117,636 Opus tokens — 4.5% of a daily cap
that reports `Adjustable: false`** — every night, before anyone does any work.
That is **$29/month unattended**, and a standing charge against an allowance
that cannot be bought back: `L-ED2BADF9` is 2,592,000 Opus tokens per day, which
at the measured 5,881.8 tokens per uncached `/query` is 440 queries a day for
everything this account does.

*Both figures are the ones derived in `spec06-disposition-amendment.md`
Finding 1, from CloudWatch `AWS/Bedrock` over 60 invocations and Cost Explorer
rates that agreed across two days.*

**And "if hot tier up" is the wrong condition.** Whether the hot tier is up says
nothing about whether an Opus allowance should be spent. Coupling them makes
`make up` — a command whose job is to start a $0.24/hr search tier — silently
commit the account to $29 a month of unattended model spend. In a milestone
whose subject is unattended cost, that is the defect rather than the design.

The human seat's instruction at M06 open was that **the nightly job must stay
free**. This is that instruction expressed as a spec change.

## The proposed clause

`SPEC/06:6-8` becomes:

> A nightly Lambda runs the **reduced graph-logic set** — the parts of the
> graph whose answers are deterministic and therefore checkable with no model
> call — **whether or not the hot tier is up**, and runs **no golden
> question**. Concretely: `graph.amendment_graph.load()` over the registry,
> date attribution, the resolved search tier, and the corpus fingerprint.
>
> It publishes `EvalStalenessHours`. **`EvalPassRate` is published by
> `evals/run_evals.py --record`**, at the moment a real measurement exists.
>
> The two alarms are different and the split is deliberate: a regression alarm
> on `EvalPassRate` fires when a run measured a regression; a staleness alarm
> fires when nobody has measured anything for too long — which is precisely the
> failure a nightly job that runs no golden set would otherwise hide. **The
> staleness metric is emitted on every nightly run, with a sentinel when no
> pass rate has ever been recorded, and its alarm treats missing data as
> breaching**, so neither "nobody has measured anything" nor "the nightly did
> not run" is silent.
>
> **A passing nightly is not a claim that the golden set passes.** It is a
> claim that the deterministic half of the graph still loads, resolves and
> dates the corpus it was pointed at.

The "full set if hot tier up" branch is **deleted, not deferred** — see the
finding above. It is not a budget question that a later milestone might revisit
with more money; the coupling is wrong at any price.

## What this does NOT change

- SPEC/06's Load test section and its Done-when clauses — those are
  `spec06-disposition-amendment.md`'s and `loadtest/DEFERRED.md`'s.
- The Tier B disposition clause, in any respect.
- `EvalPassRate`'s threshold (0.85 = 17/20, the M05 baseline less the one ruled
  false fail) or the regression alarm that watches it.
- Any golden question, or what any of them assert.

## What it costs, and the correction the reviewer forced

DynamoDB reads on-demand, one SSM read, one CloudWatch **read**. No
`PutMetricData` — the metrics leave through EMF on stdout, which is why the
role holds no metric-write grant and the dashboard numbers are not forgeable
from a second place. No Bedrock, no S3 Vectors query, no AOSS query.

**Rounds to zero, and it is designed to.** A nightly job that costs money is a
nightly job someone eventually turns off.

## The evidence

`pm-spec-reviewer` blocker B8: the claim behind this change was *"verified
live, 2026-08-20, for $0: 52 documents, 3/3 dated, no Bedrock call"* — a
remembered result, in a document where every other measurement names an
artifact a reader can check.

**Closed.** `milestones/M06/verify_nightly.py` runs the check and records
`milestones/M06/nightly-verification.json`, with the command in the artifact:

    eval "$(python evals/local_env.py)" && python milestones/M06/verify_nightly.py

Recorded 2026-08-21 against the live account: **52 documents**, fingerprint
`35a293e17117`, pub dates 2024-12-27 to 2026-08-19, **3 of 3 documents dated,
0 undated, 0 errors**, tier `s3vectors`, status `ok`.

**IN-PROCESS, and the artifact says so.** `NightlyCheckFn` is not deployed —
nothing in this milestone is — so this exercises the same code and the same
AWS reads, but not the Lambda's IAM role, its EventBridge schedule, or EMF
reaching CloudWatch. That is what "verified live" meant last session and what
the record should have said. Those three remain unexercised until the deploy.

**The cost claim is now a measurement.** The script reads the account's Opus
token counter before and after and records the difference: **0**. If the
nightly ever grows a model call, that stops being zero and the script exits
non-zero rather than filing a verification that says "free".

## The hole this change also closed, recorded because it was found late

`eng-code-reviewer` found that `EvalStalenessHours` was omitted entirely when no
`EvalPassRate` had ever been published, while its alarm was `NOT_BREACHING`. No
datapoint, no alarm — **in exactly the state the alarm exists to catch**, which
is "nobody has measured anything". `src/ops/nightly.py` asserted the opposite in
a comment.

Both halves are fixed and both are in the proposed clause above, because a
staleness watch that can go silent is not a watch and the spec should say what
it requires: a sentinel on every run, and missing-data-breaches on the alarm.

**And the fix is demonstrated rather than argued.** The verification run above
landed in exactly the state the hole was about — `eval_staleness` reports
`{"hours": null, "reason": "no EvalPassRate ever published"}` — and emitted
`EvalStalenessHours: 8760.0` anyway. Before the fix that run published no
datapoint at all, and the alarm would have sat in INSUFFICIENT_DATA, which was
NOT_BREACHING. The one state the watch exists for was the one state it could
not see, and the artifact now shows it seeing it.
