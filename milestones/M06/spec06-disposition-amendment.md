# DRAFT v4 — proposed amendment to SPEC/06's Tier B disposition clause

**Status: DRAFT for the PM seat. Not adopted. Nothing has been spent.**

> ## Rulings taken 2026-08-21, and the sources they rest on
>
> The human seat ruled on the five items this document had open. Recorded as
> **rulings with sources**, not as approvals: what makes a ruling here sound is
> a citation a reader can falsify, never a signature (CLAUDE.md, ADR-0005).
>
> | item | ruling | the source it rests on |
> |---|---|---|
> | **IIb E** — a fallback disqualifies a step | **SPLIT ADOPTED.** A resolved-tier mismatch is a gate refusal; a fallback during a step is a search-backend failure, goes in the error rate, and leaves the step dispositive with no latency sample from it. | `router._resolve` catches `AossError` and RETURNS, so the call is not an error — traced by `pm-spec-reviewer`. Under the old rule Tier B's most likely failure mode produced no error, no dispositive step, no failed measurement and no attempt. Implemented; `tests/test_retrieval_load_driver.py` carries the three cases. |
> | **IIb D** — the AOSS transport asymmetry | **OPTION 2.** Record it as a stated limitation and run. | The clause retires "the `regdelta-search` stack, the AOSS client, the reindex Lambda and the routing branch" — an implementation, not a judgement about OpenSearch Serverless. `loadtest/retrieval_load.py:KNOWN_LIMITATIONS` is the field blocker B9 required; without it option 2 was a promise the report could pass every gate without keeping. |
> | **IIb B** — comparability | **RATIFIED**, with its direction as the review corrected it: a strictness change against Tier B in one region (>5 pp worse on errors *and* faster on p95). | `security-reviewer` measured a step reporting `n 3`, `error_rate 0.95`, `dispositive_eligible true`. The threshold is non-binding wherever the error disjunct decides, so it adds no new material number. |
> | **IIb A / C** | **CORRECTION and RATIFICATION** as proposed. | `n_dispositive` pooled is 1,200–10,800; the completeness condition makes Change 3's own words operative. |
> | **Change 8** — the nightly set | **SPLIT OUT.** It amends the Observability contract, not this clause. | `pm-spec-reviewer` blocker B2. Now `milestones/M06/spec06-nightly-amendment.md`, ruled separately. |
> | **Done-when** — both `/query` profiles, the report artifacts, the chaos test | **DEFERRED, with reasons in writing.** | `loadtest/DEFERRED.md`. Change 7 carries the profiles; the chaos test is narrowed and deferred because reaching a real Opus throttle is $23.63 and 115.7% of a non-adjustable daily cap, and the seat's standing instruction is that Opus must not reach throttle (`evals/check_opus_headroom.py` enforces it). |
>
> **The seat also set a $25 ceiling on the session** and required that Opus not
> reach throttle. `config.LOADTEST_BUDGET_USD` stays at the $20 ruled at M06
> open — the disposition prices at $0.23 — and the Opus instruction is
> implemented as a measured pre-flight refusal rather than as a note.
Raised by engineering at M06 open, before any M06 measurement exists, because
the clause as written **cannot be executed in this account**.

**Revised three times.** Two `pm-spec-reviewer` passes returned ten blockers on
v1 and thirteen on v2; v4 adds two changes the seat has already decided and
records what BUILDING the thing taught. Corrections are marked inline as
"v1"/"v2"/"v3" rather than edited away: six of the twenty-three review blockers
were arithmetic that did not re-derive, in a document whose argument is that
figures must, and one was an argument that contradicted this document's own
finding at the exact point where it asked the seat to act.

**v4 is not a re-argument.** Changes 7 and 8 write down decisions the human seat
made at M06 open and that are already implemented. What is genuinely NEW is
Part IIb — four things the implementation and two security reviews found that
change what this clause MEANS, three of which are corrections to figures in this
document. They are separated out and each says what it is asking for.

**There are EIGHT proposed changes**, plus four findings from building it. v1
claimed to change only the vehicle and was wrong; v2 named four and the review
found two more; v4 adds the two the seat had already decided. Each is stated as
itself, with its direction:

| # | change | status | direction on a `keep` verdict |
|---|---|---|---|
| 1 | the vehicle: an open-loop retrieval driver | proposed | see Change 4 — **not derivable** |
| 2 | the clause's surroundings, which break under 1 | proposed | none |
| 3 | which samples the dispositive p95 is taken over | proposed | none intended; stated |
| 4 | the load each tier receives | proposed | **two opposing effects, net sign unknown** |
| 5 | the vantage moves in-region | proposed | **unknown**; ADR-0012 flagged it |
| 6 | a floor: a run that reaches no real load is a failed measurement | proposed | **toward `keep`**, and bounded |
| 7 | both `/query` load profiles are DEFERRED, quota as the reason | **DECIDED at M06 open, built** | none — they carry no disposition |
| 8 | the nightly set is the deterministic graph checks, and no golden question | **DECIDED at M06 open, built** | none |
| — | the error-rate disjunct narrows under the new vehicle | proposed | **toward `retire`** |
| — | the latency disjunct requires comparable populations (IIb B) | built, needs ratifying | **toward `retire`**, in one region: Tier B >5 pp worse on errors *and* faster on p95 |
| — | a fallback disqualifies a step (IIb E) | built, and the review calls it wrong | **toward `keep`**, undeclared — see IIb E |

And four things found by building it (Part IIb), which are not proposals in the
same sense — three are corrections to figures in this document and one is an
interpretation the run could not wait for:

| # | found | asking for |
|---|---|---|
| A | `n_dispositive` was computed for one run, not two | a correction, and the seat's word on which reading |
| B | a p95 over survivors can hand Tier B a keep for having broken | ratification of the reading already implemented |
| C | a step must account for every call it dispatched | ratification; it is the clause's own refusal of sample exclusion |
| D | Tier B's client pays 6.4 ms/call this repo wrote | a ruling on the unfixed half before the run |

---

## Part I — the findings

*v2 titled this "three findings, each measured against the live account". Only
Finding 1's quota and rate tables are measurements; Findings 2 and 3 are models
built on them and on M04's artifact. Retitled.*

### Finding 1 — MEASURED. The Opus 4.6 daily token cap is non-adjustable, and the profile exhausts it in about fourteen seconds

`aws service-quotas list-service-quotas --service-code bedrock --region us-west-2`:

| quota code | quota | value | adjustable |
|---|---|---|---|
| `L-ED2BADF9` | Global cross-region model inference **tokens per day**, Claude Opus 4.6 V1 | **2,592,000** | **false** |
| `L-82CD9B28` | Model invocation max tokens per day, Opus 4.6 V1, doubled for cross-region | 1,296,000 | **false** |
| `L-0AD9BBE8` | Cross-region model inference tokens per minute, Opus 4.6 V1 | 3,000,000 | true |

`config.MODEL_VERDICT` is `us.anthropic.claude-opus-4-6-v1`, a US cross-region
inference profile, so the binding figure is **2,592,000 Opus tokens per day,
account-wide, and AWS will not raise it.**

**Per uncached `/query`** — CloudWatch `AWS/Bedrock`, 2026-08-20T14:00–16:00Z:

| call | model | input mean | output mean |
|---|---|---|---|
| `nodes.verdict` | Opus 4.6 | **5,246.3** (max 7,987) | **635.5** (max 1,040) |
| `nodes.supervisor` | Sonnet 4.6 | 241.5 | 30.0 |

*How this window is attributed to the golden runs, corrected.* v2 said the
`ModelId` dimension identifies the caller. **It does not**: `config.NAIVE_MODEL`
is the same string as `MODEL_VERDICT`, so a baseline run inside the window would
contaminate the means. The load-bearing fact is that `Invocations` Sum is
**exactly 60 on each of the two models** — three golden runs of the twenty
questions in `evals/golden_questions.json`, one supervisor and one verdict call
each — which is what rules a baseline run out.

**5,881.8 Opus tokens per uncached `/query`** → **440 uncached queries per day**
for everything this account does.

**Rates** — Cost Explorer, `UnblendedCost ÷ UsageQuantity` per usage type,
2026-08-19 and 2026-08-20 agreeing:

| service | input | output |
|---|---|---|
| Claude Opus 4.6 (Amazon Bedrock Edition) | $5.50/M | $27.50/M |
| Claude Sonnet 4.6 (Amazon Bedrock Edition) | $3.30/M | $16.50/M |
| Claude Haiku 4.5 (Amazon Bedrock Edition) | $1.10/M | $5.50/M |
| Amazon Bedrock — `USW2-TitanEmbeddingV2-Text-input-tokens` | $0.0199/M | — |

→ `5,246.3 × 5.50e-6 + 635.5 × 27.50e-6 = $0.046331` (Opus)
→ `241.5 × 3.30e-6 + 30.0 × 16.50e-6 = $0.001292` (Sonnet)
→ **$0.047623 per uncached `/query`.**

*The Haiku row is a measurement, and the second review was wrong to say the
account has no Haiku usage for Cost Explorer to have measured: month-to-date
"Claude Haiku 4.5 (Amazon Bedrock Edition)" is $6.5036 over 5.4352 M input and
0.0951 M output tokens, which is where $1.10 and $5.50 come from. It is quoted
here rather than only in the Alternatives, which is the half of that finding
that was right.*

**The closed-loop model, with every assumption stated.** *v1 applied the 80/20
split to tokens but used the M04 `wall_s` medians as the response time for 100%
of requests. Those medians are cache-bypass measurements — every run in
`milestones/M04/answer-parity-3966b47.json` carries `"cache": "bypass"` — so
they describe only the 20%.*

- `R_miss` = 13.48 s (A) / 15.22 s (B) — median of the six per-scenario `wall_s`
  values recorded per tier in the M04 artifact.
- `R_hit` ≤ 0.5 s — **`SPEC/04:40`, "a cached repeat query returns < 500ms".
  A criterion, not a measurement**, used as an upper bound. Faster hits make
  this finding stronger.
- **Think time zero.** There was no `wait_time` to cite either way:
  `loadtest/locustfile.py` was a two-line TODO stub, and at M06 close it was
  deleted — locust is not a dependency and the profiles it named are deferred
  (`loadtest/DEFERRED.md`).
- **No server-side saturation** — per-request latency is held at its unloaded
  value with 500 in flight. This flatters the finding, and it is harmless:
  `R` would have to rise from 3.096 s to **68 s — 22× — before even one
  300-second Tier A hold fitted inside a whole day's cap.**

| | Tier A | Tier B |
|---|---|---|
| `R = 0.8(0.5) + 0.2(R_miss)` | 3.096 s | 3.444 s |
| `λ = 500 / R` | 161.50 req/s | 145.18 req/s |
| `λ_uncached = 0.2λ` | 32.30 /s | 29.04 /s |
| Opus tokens/s `= λ_uncached × 5,881.8` | 189,981 | **170,784** |
| **seconds to 2,592,000** | **13.6 s** | **15.2 s** |
| tokens/min vs the 3,000,000 quota | 11.40 M — 3.8× over | 10.25 M — 3.4× over |

*v1 said 59 s and 67 s; v2 said Tier B ran at 170,795 tok/s. Both corrected.*

Six five-minute holds — three per tier, the first discarded:

```
Tier A  3 × 300 s × 189,981 = 170,982,900
Tier B  3 × 300 s × 170,784 = 153,705,600
                      total = 324,688,500 Opus tokens = 125× the daily cap
uncached queries              55,202  ->  $2,629
```

**There is no duration at which this clause runs**, and the shortfall is a quota
AWS does not adjust.

### Finding 2 — DERIVED. The profile applies 11–26-way concurrency to the search tier, not 500

| tier | `router.retrieve()` median | uncached request median | share |
|---|---|---|---|
| A — S3 Vectors | 354.1 ms | 13.48 s | 2.6% |
| B — AOSS | 889.3 ms | 15.22 s | 5.8% |

*These two shares are a DERIVATION, not a quotation from the M04 artifact, and
the populations differ: the numerator is a median over the nine-probe retrieval
set, the denominator a median over the three demo scenarios. It is a sound
approximation for an order-of-magnitude argument and it is not a measured
ratio.*

Only uncached requests retrieve at all — `api.query` consults `response_cache`
before the graph, so a hit calls no tier. In-flight `router.retrieve()` calls
are `λ_uncached × retrieval time`:

- Tier A: `32.30 × 0.3541` = **11.4** — Tier B: `29.04 × 0.8893` = **25.8**

*v1 said 13.1 and 29.2, from the broken cache model.*

The 500 is spent on Bedrock. Tier B's only remaining case is concurrency
(ADR-0012 Ruling 3), and this profile never applies more than ~26 of it.

### Finding 3 — DERIVED. The closed loop makes both offered quantities depend on the variable under test, in opposite directions

*v1 said the open loop "removes the disparity"; v2 corrected that for in-flight
concurrency and then re-asserted the removal inside Change 4. Both are wrong,
and the honest statement needs both quantities:*

| quantity | closed loop, 500 users | open loop, 90 calls/s | who it favours |
|---|---|---|---|
| arrival rate, B ÷ A | **0.899** — B receives 10% fewer requests | **1.000** — identical by construction | closed loop favoured **B**; the change removes that |
| in-flight retrievals, B ÷ A | **2.26×** (25.8 vs 11.4) | **2.51×** (80.0 vs 31.9) | both favour **A**; the change *widens* it |

An open loop equalises the **arrival rate**. It does not equalise **in-flight
concurrency**, which stays `arrival rate × service time` and therefore stays
proportional to each tier's own latency — and because the arrival rates are now
equal and Tier B is slower, the concurrency ratio *rises*.

**So Change 1 removes an advantage Tier B held and widens a disadvantage it
carried. The net direction on a keep verdict is not derivable from M04's data
and is not claimed here.** What is claimed is narrower and is the whole
argument: under the open loop, **offered load is exogenous** — it is set by the
schedule, recorded, and identical for both halves — instead of being an output
of the result being measured.

### What no route in this account can do

`router.retrieve()` includes the embedding call, and **Titan Text Embeddings V2
is capped at 6,000 on-demand requests per minute, `Adjustable: false`** — 100
retrieval calls per second, whatever drives them.

| | at 90 calls/s | via the 500-user `/query` profile |
|---|---|---|
| Tier A in-flight | 31.9 | 11.4 |
| Tier B in-flight | 80.0 | 25.8 |

**Neither route reaches 500, and no quota increase is available on either
binding limit.** The choice is between disposing of Tier B at roughly 3× the
concurrency the `/query` profile could deliver, or not disposing of it, which
`SPEC/06:48-49` forbids M06 from doing.

---

## Part II — the eight changes

### Change 1 — vehicle: an open-loop retrieval driver

The disposition is measured by an open-loop driver issuing
**`graph.nodes.retrieval_agent`** calls at a fixed stepped arrival rate,
identical schedule and order for both tiers. That node calls
`router.retrieve_traced` with `Filters()` and `config.NAIVE_TOP_K = 8` — the
same interval, no filters and the same `k` as M04 — and invokes no model beyond
the embedding.

**The schedule is pre-registered here, numerically, before any M06 number
exists:** steps at **10, 25, 50, 75 and 90 calls per second, 60 s per step**,
15,000 calls per run. Changing it after any M06 number exists reopens the
clause.

*Implementation is deliberately NOT written into the clause.* v2 put the file
path, the runtime and the invocation shape into binding text; those are HOW and
will be wrong the first time engineering learns something. The clause binds the
property — offered load exogenous to each tier's latency, at the pre-registered
schedule, on the real retrieval node, from one vantage identical across halves —
and names the current implementation parenthetically.

**This change has a prerequisite that does not exist yet.** `SPEC/06:37-39`
defines the measured interval as the one "carried on the per-node retrieval
span", and there is no such span in the repo today:
`shared/observability.py:node_span` was written at M06 and **has no call site
in `src/graph/`**. The disposition run is therefore blocked until the
Observability span is wired and the driver invokes the node on the path that
emits it, and the report records the emission status
(`sent | unsampled | off | failed`) that module already distinguishes. An
artifact claiming a span it did not emit is ADR-0013's defect exactly.

### Change 2 — the clause's surroundings, which break under Change 1

- **`SPEC/06:25-26`** — "**The 500-user profile** is run to completion three
  times per tier" must be re-pointed, or the clause requires six runs Finding 1
  has proved impossible.
- **`SPEC/06:52-54`, Out of scope** — must add that the 500-user profile now
  carries no disposition either, and that **corpus scale is not varied**:
  `ADR-0012:111-112` named the untested regime as "scale *and* concurrency" and
  recorded "corpus size is 49 documents" — ADR-0012's count, and stale: the
  poller has since taken it to 52 (`src/ops/nightly.py`, verified 2026-08-20).
  The Out-of-scope bullet names the recorded FINGERPRINT rather than a count
  for exactly this reason, and is unaffected. *v2 cited `:110-112` and the second
  review corrected it to `:113-114`; both are wrong — it is `:111-112`.*
- **`SPEC/06:16-17`, the Done-when's first clause** — "Both profiles produce
  report artifacts in `loadtest/reports/`". Finding 1 proves the 500-user
  profile cannot run, and v2 removed only its *disposition*, leaving this
  standing. **On Opus, this account permits about 13.6 seconds of 500-user load
  per day in total, for everything.** See "The `/query` profiles" below.
- **Report contents** — add achieved load per step (mean and max in-flight
  calls beside the arrival rate driven), the vantage, and the span status.
  ADR-0013 is the precedent: an instrument reads the field that describes its
  own claim.

### Change 3 — which samples the dispositive p95 is taken over

The existing clause takes `n` = retrieval calls across the scored runs,
undifferentiated. A stepped profile must say which steps count:

> The **dispositive step** is the highest arrival rate at which **both** tiers
> completed the step. A step is **completed** when the driver's achieved
> arrival rate stayed within **5%** of the driven rate for the whole step,
> recorded — a driver that could not keep up must be distinguishable from a
> tier that was fast, which is where coordinated omission lives — and when
> neither tier recorded a Titan throttle in it. p95 is computed **within that
> step**, per tier; every other step is reported beside it and is not
> dispositive.

This does **not** add a sample-exclusion rule to the p95 definition, which is
what v1 proposed and which would have silently removed the highest-load steps —
the regime under test — from the dispositive statistic. Selecting a step is
visible in the artifact; excluding samples inside a step is not.

**`n` now means two things and both must be reported.** `n` stays "retrieval
calls across the scored runs" (30,000 per tier). **`n_dispositive`** is the
count within the dispositive step: **600 at the 10/s step to 5,400 at 90/s.**
*v2 claimed "`n` per scored run rises to 15,000", which is the wrong population,
and gave the `/query` profile's baseline as "~2,000", which is its request
count — cache hits retrieve nothing, so its true retrieval ceiling is the
440-query daily cap. The honest comparison is **440 → up to 5,400**, against
M04's `n = 27`.*

*One sequencing note.* `router._TTL` is 60.0 s and the memoised SSM lookup sits
inside the timed region — M04's artifact lists it under `latency.includes`, so
it is inside the measured interval by the clause's own definition. Each 60 s
step therefore straddles at most one TTL refresh, and each in-Lambda step
carries one cold sample with boto3 client construction (M04 measured 819.7 ms
and 1,019.6 ms for these and excluded them at run level). Both are **recorded
and identified in the report, not excluded** — at n ≥ 600 one sample cannot move
a p95, and M04's warmup exclusion was run-level while Change 3 refuses
sample-level exclusion. The two are consistent and the distinction is stated
rather than left for a reader to reconcile.

### Change 4 — the load each tier receives, and the seat is asked to accept an unknown sign

Finding 3 is the substance. Restated as the ask:

- The closed loop gave Tier B **10% fewer arrivals** than Tier A. Change 1
  removes that advantage.
- The closed loop gave Tier B **2.26×** Tier A's in-flight retrieval
  concurrency. Change 1 raises that to **2.51×** at the dispositive step.

**The net effect on a keep verdict is not derivable from M04's data, and this
document does not claim one.** What the seat is asked to accept is a comparison
whose offered load is exogenous and recorded, in place of one whose offered load
was an output of the result — not a more lenient bar and not a stricter one.

*v1 argued a strictness change away with "retirement is the default", which is a
non sequitur — a keep is a keep however obtained. v2 retracted that and then
asserted "Change 1 removes it", which Finding 3's own table contradicts.*

**The seat should see what rides on the verdict.** `ADR-0012:403-412` lists the
eight things that break if Tier B retires — SPEC/02 criteria 2 and 3, its
Done-when (B) and (D), SPEC/04's comparability criterion and its `:32-33`,
CLAUDE.md's routing rule, and ADR-0001 itself.

### Change 5 — the vantage moves in-region

*Not named in v2; found by the second review.* The driver runs in-region rather
than from the dev laptop. `ADR-0012:105-108` says Lambda-to-AOSS in-region "has
not been measured and **could move the ratio**", and ADR-0012's Alternatives
rejected "blame the vantage, re-measure from Lambda" as *motivated
re-measurement* while allowing an in-region number as welcome.

- **Direction: unknown**, and it is precisely the change ADR-0012 flagged.
- **Internal validity is preserved**: both halves share the vantage, the clause
  requires it recorded and identical, and the comparison is between tiers rather
  than against M04's number.
- It is not motivated re-measurement of a *retired* claim: leg 2 stays retired,
  and this profile measures concurrency, which was never measured at all.
- **`SPEC/06:53-54` must be rewritten**, because it currently says an in-region
  re-measurement "is welcome but is not this bar" inside a clause whose bar
  would now be taken in-region. It should distinguish the two: M04's
  *sequential* number is still not this bar, though this profile's vantage is
  the one it names.

### Change 6 — a floor, bounded so it cannot become a stall

*Not named in v2; found by the second review.* Finding 2's objection — that a
profile which never applies real concurrency does not test the concurrency case
— applies to this profile too. So:

> A run in which no step satisfied the dispositive-step condition is a **failed
> measurement, not a retirement**, and `make tier-disposition` exits non-zero.
> **It is re-run once at the same schedule. A second failure is recorded in the
> report and the clause is disposed of by the default outcome** — Tier B is
> retired — because "M06 cannot close without disposing of this clause either
> way" (`SPEC/06:48-49`) outranks the convenience of a third attempt.

Unbounded, this floor is a route to M06 ending with Tier B alive and the bar
never met. Bounded at one re-run, it is what stops a dead profile being used
against Tier B, and nothing more.

### The unnamed change the second review found, going the other way: the error-rate disjunct narrows

The existing definition counts "retrieval-path 429s" and excludes "Bedrock
throttles". Under the ruled clause that was clean: retrieval-path throttles came
from AOSS or S3 Vectors, and "Bedrock" meant Opus. **Under Change 1 the only
Bedrock call left is Titan, it is on the retrieval path, and it is inside the
measured interval** — so one event is both included and excluded.

Worse, both tiers share one Titan path, so a rate dominated by it reads equal by
construction and the disjunct dies — leaving only the p95 route, which
`ADR-0012:322-323` calls "a real climb". **That narrows Tier B's routes to a
keep from two to approximately one, and it is a strictness change against Tier
B that no one intended.** The fix is to say what was always meant:

> …retrieval-path 429s **from the search backend only**. Titan embedding
> throttles are excluded — they are the Bedrock property this definition
> already excludes, shared by both tiers and not caused by either search
> backend — and are **reported separately per step**, because a step carrying
> them is not a dispositive step (Change 3).

### The `/query` profiles, which the clause does not dispose of but SPEC/06 still requires

> **SUPERSEDED AT v4 BY CHANGE 7.** The seat chose DEFERRAL over both options
> below. This section is kept rather than deleted because the alternative it
> priced is still available to a later milestone, and because a reader should
> be able to see what was on the table when the decision was made. Read it as
> history, not as a recommendation.

`SPEC/06:16-17` requires both profiles to produce report artifacts. On the
deployed verdict model they cannot meaningfully: **13.6 seconds of 500-user load
exhausts the day's Opus cap.** Two options, and engineering recommends the
first:

**(a) Run the `/query` profiles with `MODEL_VERDICT` set to Haiku 4.5, stated in
the report.** Haiku's daily cap is 27,000,000 — `Adjustable: false`, 10.4× Opus's
— at $1.10/M in and $5.50/M out.

| profile | hold | uncached | Haiku tokens | cost |
|---|---|---|---|---|
| 100 users | 60 s | 388 | 2.28 M — 8% of cap | $4.09 |
| 500 users | 30 s | 969 | 5.70 M — 21% of cap | $10.23 |

This is defensible **only because these profiles carry no disposition**. It is
not free of cost: a faster verdict model changes `/query` p50/p95, the Lambda
concurrency curve and the throttle behaviour, so the report measures
RegDelta-with-Haiku and must say so in its first line. The cache-hit-rate curve
and the Lambda concurrency ramp are unaffected in shape.

**(b) Re-specify `SPEC/06:16-17` as a fixed uncached-request budget** — "each
profile produces a report over N uncached requests, N stated, with its Opus
consumption recorded against the 2,592,000/day cap" — and accept that the
500-user profile is a **~5-second burst** on the deployed model. Honest, and
too short for a hit-rate curve or a concurrency ramp to exist.

Either way `SPEC/06:16-17` needs re-specifying, because a duration-or-user-count
Done-when that Finding 1 has proved impossible is the same defect this amendment
exists to fix, one section up.

### Change 7 — both `/query` load profiles are deferred, and the quota is the reason

*Decided by the human seat at M06 open and implemented; written into this
document at v4 so the ruling covers it. v3 argued the case under "The `/query`
profiles" above and then left the Done-when unresolved, which is the defect
this change closes.*

`SPEC/06:16-17` requires "Both profiles produce report artifacts in
`loadtest/reports/`". Finding 1 proves the 500-user profile cannot run here:
**13.6 seconds of it exhausts a daily Opus cap that reports
`Adjustable: false`**, and the six runs the clause asks for are 125x that cap
and $2,629. The 100-user profile is affordable but measures the same
Bedrock-bound quantity.

> **`SPEC/06:10-19`**: the 100- and 500-concurrent-user `/query` profiles are
> **DEFERRED**. The stated reason is the non-adjustable Opus 4.6 daily token
> cap (`L-ED2BADF9`, 2,592,000/day, `Adjustable: false`), which the 500-user
> profile exhausts in 13.6 seconds and which no budget can raise. They are
> deferred rather than deleted: nothing about them is wrong, and a later
> milestone with a cheaper verdict model can run them unchanged. Neither
> carried a disposition, so nothing is decided by their absence.
>
> The Done-when's first clause becomes: **the retrieval-concurrency profile
> produces its report artifact in `loadtest/reports/`.** The dashboard and
> chaos-test clauses are unchanged.

**Engineering's recommendation in v3 was option (a)** — run the `/query`
profiles against Haiku 4.5 and say so in the report. The seat chose deferral
instead. Recorded because the alternative was priced and is still available:
$4.09 and $10.23, both inside the $20 ceiling, and both measuring
RegDelta-with-Haiku rather than RegDelta.

### Change 8 — MOVED to `milestones/M06/spec06-nightly-amendment.md`

*`pm-spec-reviewer` blocker B2, ruled 2026-08-21: this amends SPEC/06's
**Observability** section, not the Tier B disposition clause, and a ruling on
the disposition should not silently carry it. Split into its own one-page
amendment, which can be ruled on separately and in either order. The finding,
the proposed clause text, the cost and the staleness-alarm hole are all there.*

*Kept as a heading rather than deleted so the numbering in the table above and
in the corrections list still resolves.*

### Change 8, as it stood here — the nightly set is the deterministic graph checks

*Also decided at M06 open — "the nightly job must stay free" — and implemented
in `src/ops/nightly.py`. Written here because it is an INTERPRETATION of
`SPEC/06:6-8` rather than an implementation detail, and the spec sentence it
interprets is still on the page.*

`SPEC/06:6-8` asks for a "Nightly eval Lambda: full set if hot tier up, else
reduced graph-logic set; pass-rate metric + regression alarm."

The full set nightly is **$0.95 and 117,636 Opus tokens — 4.5% of the
non-adjustable daily cap — every night, before anyone does any work**: $29 a
month unattended, and a standing charge against an allowance that cannot be
bought back. In a milestone whose subject is unattended spend, that is the
wrong default.

> **`SPEC/06:6-8`** becomes: a nightly Lambda runs the **reduced graph-logic
> set** — the parts of the graph whose answers are deterministic and therefore
> checkable with no model call — **whether or not the hot tier is up**, and
> runs **no golden question**. Concretely: `graph.amendment_graph.load()` over
> the registry, date attribution, the resolved search tier, the corpus
> fingerprint. It publishes `EvalStalenessHours`; **`EvalPassRate` is published
> by `evals/run_evals.py --record`**, at the moment a real measurement exists.
>
> **A passing nightly is not a claim that the golden set passes.** It is a
> claim that the deterministic half of the graph still loads, resolves and
> dates the corpus it was pointed at. `src/ops/nightly.py` already says this;
> it belongs in the spec, so that a green nightly cannot be read as an
> answer-quality gate by someone who has not read the code.
>
> The two alarms are different and the split is deliberate: a regression alarm
> on `EvalPassRate` fires when a run measured a regression; a staleness alarm
> fires when nobody has measured anything for too long — which is precisely
> the failure a nightly job that runs no golden set would otherwise hide.

The "full set if hot tier up" branch is **deleted, not deferred**. It is not a
question of budget: the hot tier being up says nothing about whether an Opus
allowance should be spent, and coupling them would make `make up` silently
commit the account to $29/month.

*Verified live, 2026-08-20, for $0: 52 documents, 3/3 dated, no Bedrock call.*

**THAT SENTENCE WAS THE ONLY LOAD-BEARING CLAIM IN THIS DOCUMENT CITING
NEITHER A FILE NOR A COMMAND** — `pm-spec-reviewer` blocker B8, and it was
right. **Closed 2026-08-21**: `milestones/M06/verify_nightly.py` and
`nightly-verification.json` record it with the command beside it — 52
documents, 3 of 3 dated, 0 errors, and 0 Opus tokens measured before and
after rather than asserted. The change itself now lives in
`milestones/M06/spec06-nightly-amendment.md`.

---

---

### The chaos test — proposed as an APPENDIX to `SPEC/06:18-19`

*v2 gave this text no address; if the seat rules yes, it was undefined what
changed.* Appended to the Done-when sentence ending "returns the
degraded-but-honest response":

> The throttle is reached through the Titan Text Embeddings V2 on-demand RPM
> ceiling (6,000/min, non-adjustable), producing a genuine Bedrock
> `ThrottlingException` on the **retrieval** path and exercising
> `shared.util.retry`'s 2/4/8-second backoff and the router's fallback.
> **This narrows the criterion, and the narrowing is stated: the verdict-path
> throttle — the one that would produce the answer-path 5xx storm the Load-test
> section names — is NOT exercised at M06**, because reaching a real Opus 4.6
> throttle costs 3,000,000 tokens in one minute: **$23.63** at the measured
> input/output mix, and **115.7% of a non-adjustable daily cap**, disabling
> `make evals` until 00:00 UTC. A simulated exception is not accepted as a
> substitute for the half that is covered. **The chaos test runs outside the
> `make up` window used for the disposition**, since it deliberately exceeds a
> ceiling the disposition must stay under.

*v2 said $20.6, which had no stated basis; $16.50 is the all-input figure and
$23.63 is the figure at this document's own measured mix.*

---

## Part IIb — what building it found

*Not in v1, v2 or v3, and not proposals of the same kind. Three are corrections
to figures in THIS document; the fourth is a measurement about the code being
disposed of. Each says what it asks the seat for.*

### A — CORRECTION. `n_dispositive` was computed for one scored run, not two

This document says `n` is "retrieval calls counted across the scored runs" and
then gives `n_dispositive` as "**600 at the 10/s step to 5,400 at 90/s**".
Those are `rate x 60` — **one run**. The clause scores **two** runs per tier
(three, first discarded), so the pooled figures are **1,200 to 10,800**.

One more figure in this document that did not re-derive, and it is the one a
reader would use to judge whether the sample is large enough.

**What is implemented, and what the seat is asked for.** Percentiles cannot be
averaged, so the two scored runs' samples are POOLED and the p95 taken over the
pool; the per-run counts are reported beside it, so the other reading costs a
reader nothing. Pooling is the reading consistent with the sentence that defines
`n` and it uses all the evidence. **The seat is asked to confirm the pooled
reading, or to say the per-run one was meant.**

### B — INTERPRETATION, already implemented, and the run cannot wait for the ruling

A p95 exists only for a call that RETURNED a latency. So a tier that failed most
of its calls is compared on the few that survived — and the calls that fail are
the slow ones. **Survivor bias makes the worse tier look faster**, and the keep
condition is a disjunction, so a low p95 over a small surviving sample keeps
Tier B on the strength of having broken.

Measured by `security-reviewer` against the driver: with 95% of calls raising,
a step reported `n 3`, `error_rate 0.95` and `dispositive_eligible true`.

> **The latency disjunct is available only between comparable populations.**
> The p95 comparison is made when the two tiers' retrieval error rates at the
> dispositive step are within **five percentage points** of each other. If they
> are not, the surviving samples are not the same population, and the
> error-rate disjunct settles the clause in whichever direction it points.

**The threshold is not invented, and the reason is sharper than v4 gave.**
`pm-spec-reviewer` supplied it: work the keep condition out in full —

    keep  ⟺  (p95_B ≤ p95_A  AND  |err_B − err_A| ≤ 5pp)  OR  (err_B ≤ err_A − 5pp)

Wherever Tier B is five or more points BETTER on errors, the error disjunct
keeps it regardless of the gate, so the gate is **non-binding wherever the
error disjunct decides**. Reusing the same number therefore introduces no new
material threshold. That is the argument; "it is the clause's own figure" was
only half of it.

**AND THE DIRECTION IS NOT WHAT v4 CLAIMED.** v4 said "conservative and matches
what the clause already declares". It does not. The gate binds in exactly one
region — **Tier B more than 5 pp WORSE on errors and FASTER on p95** — and
there it flips a `keep` to a `retire`. Under the ruled clause that case is a
keep. So this is a genuine strictness change against Tier B: small, and
defensible on the grounds that the p95 is over survivors, but a strictness
change, and it now has its row in the table at the head of this document.
`pm-spec-reviewer`, third pass, blocker B5.

**Asked for: ratification.** It is implemented, it is stated in the artifact it
produces, and without it the clause can return a `keep` that means "Tier B
broke more often and its survivors were quick".

### C — RATIFICATION. A step must account for every call it dispatched

A call that raises is a sample carrying an error. A call that never returns is
in **no sample at all** — invisible in `n` AND in the error rate. Measured: a
step in which 2 of 20 calls returned reported `error_rate 0.0`,
`tier_as_asked true` and `dispositive_eligible true`, with a p95 over two
samples.

That is **the sample exclusion this document already refuses** — Change 3: "This
does not add a sample-exclusion rule to the p95 definition… Selecting a step is
visible in the artifact; excluding samples inside a step is not." Performed
invisibly, and biased toward whichever tier failed more.

> A step is **completed** only if the driver accounted for every call it
> dispatched and at least one call returned a latency. The report carries all
> three populations — dispatched, returned, and the number carrying a latency —
> per step.

**Asked for: ratification**, as making Change 3's own words operative rather
than as a new rule.

### D — MEASURED, and the seat is asked to rule BEFORE the run

Tier B's client pays two per-call costs Tier A does not, both **inside
`router.retrieve()`** — the interval this clause defines its p95 over — and
neither of them a property of AOSS.

**Fixed.** `aoss_client.request` called
`botocore.session.get_session().get_credentials()` per request; `get_session()`
constructs a session rather than returning a cached one. Measured offline, local
CPU only, n=30 (`milestones/M06/aoss_per_call_overhead.json`): **6.430 ms
median, 81.0 ms max**, against 0.000 ms for frozen credentials off a reused
session, and 0.084 ms for the SigV4 signing both tiers pay. It is pure Python,
so it is GIL-serialised: at this clause's top step that is **579 ms of CPU per
second of wall clock** in a ~1.2-vCPU Lambda. It does not add 6 ms per call; it
saturates and queues. Now memoised.

**Not fixed, and this is the question.** `urllib.request.urlopen` opens a fresh
**TCP + TLS connection on every AOSS call**, because nothing installs an opener
holding a pool — while the S3 Vectors path goes through botocore, which keeps a
urllib3 pool per client. (Tier A's pool was 10 against ~32-80 calls in flight;
that IS fixed, `config.RETRIEVAL_POOL_SIZE`.) The handshake is not measurable
offline and it is not a four-line change.

**Three options, and engineering recommends the second:**

1. **Run as-is.** Tier B is measured with a per-call handshake Tier A does not
   pay. If it retires, part of the reason is this repo's transport, not AOSS.
2. **Record it as a stated limitation of the disposition and run.** The report
   names the asymmetry; a `retire` verdict is understood to be about
   *RegDelta's AOSS tier as implemented*, which is what is actually being
   retired — the stack, the client, the reindex Lambda and the routing branch.
   Nothing in the clause promises a verdict about OpenSearch Serverless.
3. **Pool the connections first, then run.** The fairest measurement and the
   largest change, to a tier that may be retired a day later.

The clause's retirement text supports (2): it removes *this* implementation, not
a judgement about the service. But the seat should choose, because "Tier B was
slower" and "our AOSS client was slower" are different sentences and the
artifact will carry one of them.

### E — RULED 2026-08-21. The split is adopted, and implemented

*Blockers B1 and B6 from `pm-spec-reviewer`'s third pass. Left OPEN rather than
resolved: this is a change to what the clause means, in the direction of `keep`,
and it is the one item in Part IIb where engineering and the product seat's
reviewer disagree about the design rather than about a figure.*

**What is built.** A step is dispositive only if every call that answered came
from the tier the step was pointed at, with no fallback recorded; and a half
whose scored steps observed another tier is a GATE REFUSAL, which by Change 6's
wording does not consume one of the two attempts the floor allows.

**Why it was built that way.** `security-reviewer` measured a step reporting
`tiers_observed ["s3vectors"]`, `errors 0`, `error_rate 0.0` and
`dispositive_eligible true` while pointed at AOSS — Tier A's latencies filed
under Tier B, in a clause whose default outcome is retirement. A
data-access-policy propagation delay after `make up` produces exactly that.

**What the review found, and it is right.** Trace a real AOSS failure under
load. `router._resolve` catches `AossError`, falls back, and RETURNS
SUCCESSFULLY, so the call is not an error. The step is then not dispositive, the
half is a gate refusal, and the refusal consumes no attempt. Tier B breaking
under concurrency therefore produces: nothing in the error-rate numerator,
nothing dispositive, no failed measurement, and no attempt — **only unbounded
re-runs**. The clause's default outcome becomes unreachable by precisely the
behaviour the clause exists to measure, and Change 6's bound is defeated. The
review also notes this makes leg 1's designed behaviour a disqualifier, inside
a clause whose Out-of-scope says leg 1 is not re-litigated here.

**The review's proposal, which engineering accepts as better:**

> Split the two cases, because they are different facts.
>
> - The **resolved tier at step start** disagreeing with the half it is
>   recorded under is a CONFIGURATION ERROR → gate refusal, exit 1, no attempt
>   consumed. This is the propagation-delay trap.
> - A **fallback recorded during a step** is an AOSS FAILURE → it belongs in
>   that tier's retrieval error-rate numerator, which is where the clause
>   already puts "AOSS or S3 Vectors 5xx"; the step stays dispositive-eligible;
>   the fallen-back call contributes NO latency sample, because its latency is
>   the other tier's; and the fallback count is reported per step.
>
> Under the split, a Tier B that fails half its calls records a 50% error rate
> and a p95 over the half that AOSS answered — and IIb B's comparability gate
> then removes the latency route, so it retires on the measurement rather than
> stalling.

**What the seat is asked.** Adopt the split, or keep what is built and accept
that a fallback stalls the clause. **Engineering recommends the split**, and
notes one residual it does not remove: if EVERY call falls back, no latency
sample exists at that step, so no step qualifies and the run is a failed
measurement — bounded at two attempts by Change 6, reaching `retire` by the
default outcome. That terminates, which is the property the current design
lacks.

**RULED: the split is adopted.** Implemented in `src/ops/retrieval_load.py`
(the sample partition: a fallen-back call carries no latency and is counted in
the error-rate numerator) and in `loadtest/retrieval_load.py` (`_step_ok` no
longer refuses on a fallback). `tests/test_retrieval_load_driver.py` carries
the three cases — wholesale fallback, partial fallback, and a fallback that
lands back on the expected tier — and the mutation harness carries the
mutations that would undo it.

*The three tests that encoded the OLD rule were rewritten rather than deleted,
so the diff shows the semantics changing rather than assertions disappearing.*

---

## Part III — the amended clause, in full

**FIVE ADDRESSES ARE TOUCHED, and this Part is only two of them.** v2 was
blocked for leaving proposed edits outside the clause text; v4 repeated it in
the other direction. The full set, so that adopting Part III alone cannot leave
SPEC/06 self-contradictory:

| address | what changes | where the replacement text is |
|---|---|---|
| `SPEC/06:6-8` | the nightly set | **Change 8**, and see the struck disclaimer above — this may belong in its own amendment |
| `SPEC/06:10-14` | the Load test section | end of this Part |
| `SPEC/06:16-17` | the Done-when's first clause | **Change 7** |
| `SPEC/06:18-19` | the chaos-test sentence | **the chaos-test appendix**, Part II |
| `SPEC/06:21-54` | the disposition clause | below |

Adopting only the text below leaves `SPEC/06:17` reading "Both profiles produce
report artifacts" three lines under a Load-test section saying both are
deferred. `pm-spec-reviewer`, third pass, blocker B3.

`SPEC/06:21-54` becomes:

> **Vocabulary, because "run" carried four meanings and one of them produced a
> wrong number** (correction 24, and `pm-spec-reviewer` blocker B7). A **run**
> is one pass of the five-step schedule. An **attempt** is three runs against
> one tier, the first discarded as warmup. A **campaign** is one attempt per
> tier at one sha across one `make up`/`make down` episode. Change 6's floor
> permits one repeated CAMPAIGN, not one repeated run.
>
> **Tier B's disposition (owed by ADR-0001, homed here by ADR-0012).** At the
> **retrieval-concurrency profile** — an open-loop driver issuing
> `graph.nodes.retrieval_agent` calls at a fixed stepped arrival rate, on an
> identical schedule and in an identical order for both tiers, from one vantage
> recorded and identical across both halves, so that offered load is exogenous
> to each tier's own latency (currently `loadtest/retrieval_load.py`, in-region
> on Lambda; the driver's file, runtime and invocation shape are engineering's
> and may change without reopening this clause) — **one run per tier, both
> taken across a single `make up` / `make down` cycle at one sha, with the
> corpus fingerprint recorded identical across both halves, the Tier A half
> taken with the collection DESTROYED and the Tier B half with it up** — which
> is why the OCU cost is 35 minutes and not 50 — the discipline
> `milestones/M04/answer-parity-3966b47.json` demonstrates. The profile is run
> to completion **three times per tier, the first discarded as warmup**, with
> `n` = retrieval calls counted across the scored runs; each report states its
> percentile method, `n`, and `n_dispositive`. **Samples are POOLED across the
> scored runs**, so `n_dispositive` at the dispositive step is 1,200 at 10/s
> rising to 10,800 at 90/s — two scored runs, not one (Part IIb A corrects v3's
> "600 to 5,400", which was one run's arithmetic). The per-run counts are
> reported beside the pooled figure. ("Passes" is the probe set's word and does
> not transfer to a load profile.)
>
> **The schedule is fixed here and not at run time:** steps at 10, 25, 50, 75
> and 90 calls per second, 60 s per step, 15,000 calls per run, **with no
> filters and `k` = 8, both recorded** (the same `Filters()` and
> `config.NAIVE_TOP_K` M04 used, so the comparability this clause invokes twice
> is a comparison of like with like).
>
> **The top step is 90% of a non-adjustable ceiling and the expected
> dispositive step is therefore 75/s, not 90.** 90 calls/s is 5,400 embed
> requests per minute against Titan's 6,000/min, `Adjustable: false`; a throttle
> there disqualifies the step. Expected `n_dispositive` is **9,000 pooled**,
> with 10,800 as the ceiling if 90/s holds. Changing it
> after any M06 number exists reopens this clause. **The tier order is recorded
> and fixed before the run; no other Bedrock workload runs in the account during
> the window** — `make evals`, a manual `/query` and `run_evals.py --record`
> consume the same Titan RPM and Opus caps that select the dispositive step; the
> nightly Lambda does NOT, since Change 8 leaves it making no Bedrock call at
> all — **and the first run
> completed at this schedule is the record. Any re-run is recorded in the report
> with its reason.**
>
> **This clause cannot be run until SPEC/06's per-node retrieval span exists**
> and the driver invokes the node on the path that emits it; the report records
> the span emission status.
>
> Report to `loadtest/reports/tier-disposition-<sha>.json`, written by
> `make tier-disposition` — **which exits non-zero if the sha is dirty, if the
> corpus fingerprints of the two halves differ, if either half's resolved tier
> does not match the half it was recorded under, or if no step satisfied the
> dispositive-step condition. A gate refusal and a failed measurement are
> DIFFERENT outcomes and carry different exit codes**: a failed measurement
> spends one of the two attempts the floor allows, so a half that answered from
> the wrong tier must be reported as a refusal rather than consuming an
> attempt — carrying per tier: p95 retrieval latency, the
> retrieval error rate defined as `(AOSS or S3 Vectors 5xx + retrieval-path
> 429s from the search backend only) / retrieval calls issued to that tier` —
> **Bedrock throttles are excluded**, being an LLM-call property shared by both
> tiers and not caused by the search backend, and **Titan embedding throttles
> are Bedrock throttles for this purpose and are reported separately per step**
> — the **achieved** load per step (mean and max in-flight calls, beside the
> arrival rate driven), the vantage, the span status, **and — if the seat rules
> Part IIb D option 2 — the known client-transport asymmetry, named**, and the
> verdict.
>
> *That field is conditional and is written here rather than added later
> because option 2 is "record it as a stated limitation and run", and a
> limitation with no field behind it is a promise the report can pass every
> gate without keeping.* `pm-spec-reviewer`, third pass, blocker B9.
>
> **p95 retrieval latency** here is the `router.retrieve()` interval carried on
> the per-node retrieval span (Observability, above) — the same interval
> `milestones/M04/answer-parity-3966b47.json` measures, embedding call
> included, both tiers. It is **not** end-to-end `/query` latency, which is
> Bedrock-dominated and would read roughly equal across tiers, letting Tier B
> survive on noise.
>
> **The dispositive step** is the highest arrival rate at which both tiers
> completed the step, where *completed* means the achieved arrival rate stayed
> within 5% of the driven rate for the whole step, neither tier recorded a
> Titan throttle in it, **the driver accounted for every call it dispatched,
> at least one call returned a latency, and every call that answered came from
> the tier the step was pointed at** — with **any fallback counted in that
> tier's retrieval error rate rather than disqualifying the step**, and
> contributing no latency sample, since a fallen-back call's timing describes
> the tier that rescued it (Part IIb E, ruled 2026-08-21). The report carries
> all three populations per step — dispatched, returned, and the number
> carrying a latency — and, per step, the reasons any refusal was made. p95 is computed within that step, per tier; every other
> step is reported beside it and is not dispositive. **If no step qualifies the
> run is a failed measurement and not a retirement**, and the run is repeated
> once at the same schedule; a second failure is recorded and the clause is
> disposed of by the default outcome.
>
> **Tier B keeps its place only if** its p95 retrieval latency is at or below
> Tier A's — **and that comparison is made only when the two tiers' error rates
> at the dispositive step are within five percentage points of each other**,
> because a p95 over the calls that survived is not a comparison between the
> same populations, and the calls that fail are the slow ones (Part IIb B) —
> **or** its retrieval error rate is at least 5 percentage points lower than
> Tier A's. If neither holds, Tier B is retired: the
> `regdelta-search` stack, the AOSS client, the reindex Lambda and the routing
> branch are removed, and `/regdelta/search/endpoint` stops being a tier
> selector. **Retirement is the default outcome**; keeping Tier B requires the
> recorded measurement above. M06 cannot close without disposing of this clause
> either way. **A difference inside the recorded run-to-run spread is not an
> advantage; ties retire.**
>
> *Out of scope for this clause:* leg 1's availability contract is not
> re-litigated here; **neither the 100-user nor the 500-user `/query` profile
> carries any disposition**; **corpus scale is not varied, and this disposition
> is taken at whatever corpus size the recorded fingerprint names** —
> ADR-0012 named the untested regime as scale *and* concurrency and this
> supplies only the second; and **an in-region re-measurement of M04's
> *sequential* number is welcome but is not this bar, though this profile's
> vantage is the in-region one M04 lacked.**

And `SPEC/06:10-14`, the Load test section, gains:

> Both `/query` profiles are **Bedrock-bound** — retrieval is 2.6–5.8% of an
> uncached request (derived from `milestones/M04/answer-parity-3966b47.json`;
> the two medians are over different question populations) and cached requests
> retrieve not at all — and **both are DEFERRED (Change 7), the non-adjustable
> Opus 4.6 daily token cap being the stated reason.** Neither carried Tier B's
> disposition, so nothing is decided by their absence. If a later milestone
> runs them, each report states its verdict model and its token consumption
> against that model's daily cap.

---

## What this proposal does NOT change

- **The keep-or-retire condition**, verbatim, including "ties retire" and "M06
  cannot close without disposing of this clause either way".
- **What p95 retrieval latency means** — the `router.retrieve()` interval,
  embedding call included, carried on the per-node retrieval span, both tiers.
  Change 3 selects which samples it is taken over; the interval is unchanged.
- **One sha, one `make up`/`make down` cycle, identical corpus fingerprints,
  three runs per tier with the first discarded**, and the percentile-method-and-`n`
  reporting discipline.
- **The report path** `loadtest/reports/tier-disposition-<sha>.json`.
- ~~**SPEC/06's Observability section**~~ — **STRUCK AT v4. This is now false:
  Change 8 rewrites `SPEC/06:6-8` and deletes a branch of it.** The reviewer's
  blocker B2, and it raises a question only the seat can settle: this document
  is titled an amendment to the *Tier B disposition clause*, and Change 8
  amends the *Observability* contract. **Either retitle this "amendment to
  SPEC/06", or split Change 8 into its own one-page amendment against
  `SPEC/06:6-8`.** `pm-spec-reviewer` recommends the split; engineering has no
  preference and notes only that Change 8 is already built, so whichever
  document carries it needs a ruling before M06 closes.
- **ADR-0012 Rulings 1 and 2**; **leg 1 of ADR-0001**;
  **`evals/scenarios.json`** and what the three demo scenarios assert; **no
  golden question in the disposition or in the nightly**.

## Alternatives considered

- **Run the `/query` profile anyway, shorter.** One 30-second Tier A hold is
  `30 × 189,981 = 5,699,430` Opus tokens — **2.2× the day's non-adjustable cap
  for one of six required runs**. *v1 quoted 1.29 M and named no tier.*
  Findings 2 and 3 survive any shortening unchanged.
- **Swap `MODEL_VERDICT` to Haiku 4.5 for the disposition too.** Rejected: it
  addresses only Finding 1, and the profile would still deliver 11–26 concurrent
  retrievals with load set by the result. (It IS recommended for the `/query`
  profiles, which carry no disposition — see Part II.)
- **Raise the quota.** Both daily caps and the Titan RPM ceiling report
  `Adjustable: false`.
- **Retire Tier B without measuring.** Reaches the same default disposition, but
  ADR-0012 rejected retiring on the M04 number as over-reading it, and arriving
  at the same place by declining to measure honours that rejection in form only.

## Cost

| item | basis | cost |
|---|---|---|
| Titan embeddings | 6 runs × 15,000 calls × ~10 tokens (**assumed, not measured**) at $0.0199/M | $0.018 |
| Lambda, in-region driver | 6 × 300 s at 2048 MB | $0.060 |
| AOSS OCU | one `make up`/`make down`; the window includes the ~20-minute reindex hydration ADR-0012 records, so ~50 min at the $0.242/hr measured at M05 | $0.202 |
| **disposition total** | | **$0.28** |

**Re-derived from the implementation, and it is lower: $0.23.** `make
tier-disposition-price` computes all three components before invoking anything
(`loadtest/retrieval_load.py:price`), and the run refuses if the total crosses
`config.LOADTEST_BUDGET_USD`:

| item | basis | cost |
|---|---|---|
| Titan embeddings | 90,000 calls at 16 tokens — an UPPER BOUND from the longest question at four characters per token, replacing v3's "~10, assumed" | $0.029 |
| Lambda | 1,800 s at 2048 MB = 3,600 GB-s | $0.060 |
| AOSS OCU | 20 min hydration + 15 min of AOSS runs = 35 min at $0.242/hr | $0.141 |
| **total** | | **$0.230** |

*v3's $0.28 assumed ~50 minutes of OCU; the schedule needs 35. The ceiling is
applied to the WHOLE run, not to its Bedrock half: `loadtest/budget.py` can only
price a model call, so the infrastructure cost is subtracted from the ceiling
handed to it. Feeding it Bedrock alone would have enforced $20 against three
cents.*

*v2 twice described this as "about two cents" against its own $0.28 table — a
factor of fourteen, in the figure used to close the argument. **$0.28 all in, of
which under two cents is Bedrock.*** No Opus, no Sonnet, no LLM call of any kind
on the disposition path.

## Corrections to v1, v2 and v3, recorded rather than edited away

**v1 → v2.** (1) The cache model applied 80/20 to tokens and 100% to response
time. (2) 73.0 M, $591 and "1.29 M for a 30-second hold" did not re-derive.
(3) "ADR-0012 spent three revisions" — it says "Revised twice". (4) The 429 rule
filed under "does NOT change". (5) Claiming the open loop removes the load
disparity. (6) Arguing a strictness change away with "retirement is the
default". (7) A ceiling with no floor. (8) No command. (9) `SPEC/06:25-26` and
`:52-54` left stale. (10) Asserting the Titan throttle reaches "the real
handler".

**v2 → v3.** (11) Change 4 re-asserted the removal Finding 3 had just
retracted, and the two effects run in opposite directions. (12) The vantage
change was unnamed. (13) The failed-measurement floor was unnamed and
unbounded. (14) `SPEC/06:16-17` left unexecutable after being proved so.
(15) The error-rate disjunct became self-contradictory and effectively dead
under the new vehicle — a strictness change against Tier B. (16) `n` meant two
things; "15,000" was the wrong population and "~2,000" the wrong baseline.
(17) Tier B's tok/s was 170,795, not 170,784, with two totals built on it.
(18) "About two cents" against a $0.28 table. (19) $20.6 for the chaos test with
no basis. (20) An unfinished formula left in the text. (21) Three of four
`make tier-disposition` exit conditions never entered the clause, and the chaos
text had no address. (22) "Completed the step" was undefined — coordinated
omission. (23) Tier order, account quiet-time and which run is the record were
all left to run time.

**v3 → v4.** (24) `n_dispositive` was one scored run's arithmetic — 600 to
5,400 — against a clause that scores two. Pooled, it is 1,200 to 10,800.
(25) The cost table said $0.28 on a 50-minute OCU window; the schedule needs 35,
and the implementation prices it at $0.230 with a measured token upper bound
instead of an assumed one. (26) "Completed the step" still permitted a step that
answered from the OTHER tier, and one that could not account for the calls it
dispatched — both found by security review, both measured, both able to retire
Tier B on a misconfiguration. (27) The keep condition permitted a p95 over
survivors. (28) The `/query` deferral and the nightly-set reading were decided
at M06 open and were in the code but not in this document, so a ruling on v3
would not have covered them.

**Both reviews and this draft got `ADR-0012`'s corpus-size citation wrong** —
v2 said `:110-112`, the second review said `:113-114`; it is **`:111-112`**.
Recorded because this document's own argument is that citations must be checked.
