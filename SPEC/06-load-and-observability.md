# SPEC/06 — Load Test + Observability

> **Amended 2026-08-21.** Two amendments were adopted as rulings with sources:
> `milestones/M06/spec06-disposition-amendment.md` (the Tier B disposition
> clause, the Load-test section, and the Done-when) and
> `milestones/M06/spec06-nightly-amendment.md` (the nightly). Those documents
> carry the findings, the measurements and the corrections behind every change
> here. This file carries only what the spec now requires.

## Observability
X-Ray (or Langfuse) span per graph node: retrieval ms, tokens, cache
hit/miss, tier, confidence. CloudWatch dashboard: p50/p95, cache hit rate,
Bedrock cost/query, HITL rate, current search-session cost.

A nightly Lambda runs the **reduced graph-logic set** — the parts of the graph
whose answers are deterministic and therefore checkable with no model call —
**whether or not the hot tier is up**, and runs **no golden question**.
Concretely: `graph.amendment_graph.load()` over the registry, date attribution,
the resolved search tier, and the corpus fingerprint.

It publishes `EvalStalenessHours`. **`EvalPassRate` is published by
`evals/run_evals.py --record`**, at the moment a real measurement exists.

The two alarms are different and the split is deliberate: a regression alarm on
`EvalPassRate` fires when a run measured a regression; a staleness alarm fires
when nobody has measured anything for too long — which is precisely the failure
a nightly job that runs no golden set would otherwise hide. **The staleness
metric is emitted on every nightly run, with a sentinel when no pass rate has
ever been recorded, and its alarm treats missing data as breaching**, so neither
"nobody has measured anything" nor "the nightly did not run" is silent.

**A passing nightly is not a claim that the golden set passes.** It is a claim
that the deterministic half of the graph still loads, resolves and dates the
corpus it was pointed at.

The former "full set if hot tier up" branch is **deleted, not deferred**, and
nothing is lost by deleting it: that coverage remains available on demand as
`make retrieval-evals`. Only its TRIGGER changes — from a side effect of
`make up`, a command whose job is to start a $0.24/hr search tier, into
something a person decides to run and pays for deliberately.

## Load test
Capture: p50/p95 by tier, cache hit-rate curve, Lambda concurrency, throttle
behavior — verify graceful degradation (honest message, not a 5xx storm) when
Bedrock throttles **(the throttle half of this capture is deferred at M06 —
`loadtest/DEFERRED.md` §3)**.

Both `/query` profiles — 100 and 500 concurrent users, 80/20 repeated/unique
questions — are **Bedrock-bound**: retrieval is 2.6–5.8% of an uncached request
(derived from `milestones/M04/answer-parity-3966b47.json`; the two medians are
over different question populations — a derivation, not a measured ratio) and
cached requests retrieve not at all. **Both are DEFERRED**, the
non-adjustable Opus 4.6 daily token cap being the stated reason
(`L-ED2BADF9`, 2,592,000/day, `Adjustable: false`), which the 500-user profile
exhausts in 13.6 seconds and which no budget can raise. They are deferred
rather than deleted: nothing about them is wrong, and a later milestone with a
cheaper verdict model can run them unchanged. **Neither carried Tier B's
disposition, so nothing is decided by their absence.** If a later milestone runs
them, each report states its verdict model and its token consumption against
that model's daily cap. The deferral is recorded in `loadtest/DEFERRED.md`.

## Done when
`make tier-disposition` writes `loadtest/reports/tier-disposition-<sha>.json`
and exits zero, **and its distilled copy — verdict, per-step counts and
percentiles included — is recorded in `milestones/MNN/`, because
`loadtest/reports/` is not in the tree** (`.gitignore`: the raw report carries
the per-step latency arrays and runs to megabytes). The dashboard is
screenshot-ready, **evidenced by `milestones/MNN/dashboard-*.png` and
`dashboard-snapshot.json`**, which record the rendered panels and, per
expression panel, whether it returned any datapoints — a panel can render
perfectly and be empty. **The Bedrock-throttle chaos test is DEFERRED — both
halves — with reasons recorded in `loadtest/DEFERRED.md` §3.**

### Chaos test (appendix — DEFERRED at M06, specified for when it runs)
The throttle **will be** reached through the Titan Text Embeddings V2 on-demand
RPM ceiling (6,000/min, non-adjustable), producing a genuine Bedrock
`ThrottlingException` on the **retrieval** path and exercising
`shared.util.retry`'s 2/4/8-second backoff and the router's fallback.

**This narrows the criterion, and the narrowing is stated: the verdict-path
throttle — the one that would produce the answer-path 5xx storm the Load-test
section names — is NOT in scope**, because reaching a real Opus 4.6 throttle
costs 3,000,000 tokens in one minute: **$23.63** at the measured input/output
mix, and **115.7% of a non-adjustable daily cap**, disabling `make evals` until
00:00 UTC. **A simulated exception is not accepted as a substitute** — the
property claimed is degraded-but-honest behaviour under a REAL throttle, which
is precisely what a mock cannot establish.

**The retrieval half is affordable and is deferred anyway**, because it must not
run inside the `make up` window used for the disposition: it deliberately
exceeds a ceiling the disposition must stay under, and a Titan throttle
disqualifies a step. **It must run outside that window.**

## Tier B's disposition (owed by ADR-0001, homed here by ADR-0012)

**Vocabulary, because "run" carried four meanings.** A **run** is one pass of
the five-step schedule. An **attempt** is three runs against one tier, the first
discarded as warmup. A **campaign** is one attempt per tier at one sha across
one `make up` / `make down` episode. The floor below permits one repeated
CAMPAIGN, not one repeated run.

At the **retrieval-concurrency profile** — an open-loop driver issuing
`graph.nodes.retrieval_agent` calls at a fixed stepped arrival rate, on an
identical schedule and in an identical order for both tiers, from one vantage
recorded and identical across both halves, so that offered load is exogenous to
each tier's own latency (currently `loadtest/retrieval_load.py`, in-region on
Lambda; the driver's file, runtime and invocation shape are engineering's and
may change without reopening this clause) — **one attempt per tier, both taken
across a single `make up` / `make down` cycle at one sha, with the corpus
fingerprint recorded identical across both halves, the Tier A half taken with
the collection DESTROYED and the Tier B half with it up**. That ordering is the
discipline `milestones/M04/answer-parity-3966b47.json` demonstrates, and it is
also what keeps the OCU cost to the Tier B half alone. The profile is run to
completion **three times per tier, the first discarded as warmup**, with `n` =
retrieval calls counted across the scored runs; each report states its
percentile method, `n`, and `n_dispositive`. **Samples are POOLED across the
scored runs**, and the per-run counts are reported beside the pooled figure.
("Passes" is the probe set's word and does not transfer to a load profile.)

**The schedule is fixed here and not at run time:** steps at 10, 25, 50, 75 and
90 calls per second, 60 s per step, 15,000 calls per run, **with no filters and
`k` = 8, both recorded**. 90 calls/s is 5,400 embed requests per minute against
Titan's 6,000/min, `Adjustable: false`; a throttle there disqualifies the step.
Changing the schedule after any M06 number exists reopens this clause.

**The clause states no expectation of which step will be dispositive.** The
driver may saturate before either tier does, and that is a property of the
VANTAGE which the report records as one: `n_dispositive`, the achieved rate,
`dispatch_refused` and `threads_abandoned` are reported per step. **A reader
comparing two campaigns must compare their dispositive steps, not assume a
fixed one.**

**The ceiling this vantage was measured at, so it is not re-bought:** from a
2048 MB in-region driver on 2026-08-21, 75 and 90 calls/s were unreachable —
achieved rates fell to 66–79/s with dispatch refusals at the thread ceiling —
and the dispositive step was **50/s**
(`milestones/M06/tier-disposition-f651aea.json`). **That is the driver's
ceiling, not either tier's.** A re-run of this schedule that wants a higher
dispositive step must raise the driver, not the rates.

**The tier order is recorded and fixed before the run; no other Bedrock
workload runs in the account during the window** — `make evals`, a manual
`/query` and `run_evals.py --record` consume the same Titan RPM and Opus caps
that select the dispositive step; the nightly Lambda does NOT, since it makes no
Bedrock call at all — **and the first run completed at this schedule is the
record. Any re-run is recorded in the report with its reason.**

**This clause cannot be run until the per-node retrieval span above exists** and
the driver invokes the node on the path that emits it; the report records the
span emission status.

Report to `loadtest/reports/tier-disposition-<sha>.json`, written by
`make tier-disposition` — **which exits non-zero if the sha is dirty, if the
corpus fingerprints of the two halves differ, if either half's resolved tier
does not match the half it was recorded under, or if no step satisfied the
dispositive-step condition. A gate refusal and a failed measurement are
DIFFERENT outcomes and carry different exit codes**: a failed measurement spends
one of the two attempts the floor allows, so a half that answered from the wrong
tier must be reported as a refusal rather than consuming an attempt.

The report carries, per tier: p95 retrieval latency; the retrieval error rate
defined as `(AOSS or S3 Vectors 5xx + retrieval-path 429s from the search
backend only) / retrieval calls OFFERED to that tier` — **Bedrock throttles are
excluded**, being an LLM-call property shared by both tiers and not caused by
the search backend, and **Titan embedding throttles are Bedrock throttles for
this purpose and are reported separately per step**; the **achieved** load per
step (mean and max in-flight calls, beside the arrival rate driven); the
vantage; the span status; **the known client-transport asymmetries, named**; and
the verdict.

**p95 retrieval latency** here is the `router.retrieve()` interval carried on the
per-node retrieval span (Observability, above) — the same interval
`milestones/M04/answer-parity-3966b47.json` measures, embedding call included,
both tiers. It is **not** end-to-end `/query` latency, which is Bedrock-dominated
and would read roughly equal across tiers, letting Tier B survive on noise.

**The dispositive step** is the highest arrival rate at which both tiers
completed the step, where *completed* means the achieved arrival rate stayed
within 5% of the driven rate for the whole step, neither tier recorded a Titan
throttle in it, **the driver accounted for every call it dispatched, at least
one call returned a latency, and every call that answered came from the tier the
step was pointed at** — with **any fallback counted in that tier's retrieval
error rate rather than disqualifying the step**, and contributing no latency
sample, since a fallen-back call's timing describes the tier that rescued it.
The report carries all three populations per step — dispatched, returned, and
the number carrying a latency — and, per step, the reasons any refusal was made.
p95 is computed within that step, per tier; every other step is reported beside
it and is not dispositive. **If no step qualifies the run is a failed
measurement and not a retirement**, and the campaign is repeated once at the
same schedule; a second failure is recorded and the clause is disposed of by the
default outcome.

**Tier B keeps its place only if** its p95 retrieval latency is at or below Tier
A's — **and that comparison is made only when the two tiers' error rates at the
dispositive step are within five percentage points of each other**, because a
p95 over the calls that survived is not a comparison between the same
populations, and the calls that fail are the slow ones — **or** its retrieval
error rate is at least 5 percentage points lower than Tier A's. If neither
holds, Tier B is retired: the `regdelta-search` stack, the AOSS client, the
reindex Lambda and the routing branch are removed, and
`/regdelta/search/endpoint` stops being a tier selector. **Retirement is the
default outcome**; keeping Tier B requires the recorded measurement above. M06
cannot close without disposing of this clause either way. **A difference inside
the recorded run-to-run spread is not an advantage; ties retire.**

*Out of scope for this clause:* leg 1's availability contract is not
re-litigated here; **neither the 100-user nor the 500-user `/query` profile
carries any disposition**; **corpus scale is not varied, and this disposition is
taken at whatever corpus size the recorded fingerprint names** — ADR-0012 named
the untested regime as scale *and* concurrency and this supplies only the
second; and **an in-region re-measurement of M04's *sequential* number is
welcome but is not this bar, though this profile's vantage is the in-region one
M04 lacked.**
