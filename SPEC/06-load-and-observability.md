# SPEC/06 — Load Test + Observability

## Observability
X-Ray (or Langfuse) span per graph node: retrieval ms, tokens, cache
hit/miss, tier, confidence. CloudWatch dashboard: p50/p95, cache hit rate,
Bedrock cost/query, HITL rate, current search-session cost. Nightly eval
Lambda: full set if hot tier up, else reduced graph-logic set; pass-rate
metric + regression alarm.

## Load test (loadtest/locustfile.py)
Profiles: 100 and 500 concurrent users, 80/20 repeated/unique questions.
Capture: p50/p95 by tier, cache hit-rate curve, Lambda concurrency,
throttle behavior — verify graceful degradation (honest message, not a
5xx storm) when Bedrock throttles.

## Done when
Both profiles produce report artifacts in loadtest/reports/; dashboard is
screenshot-ready; a Bedrock-throttle chaos test returns the
degraded-but-honest response.

**Tier B's disposition (owed by ADR-0001, homed here by ADR-0012).** At the
500-concurrent-user profile, **one run per tier, both taken across a single
`make up` / `make down` cycle at one sha, with the corpus fingerprint recorded
identical across both halves** — the discipline
`milestones/M04/answer-parity-3966b47.json` demonstrates. The 500-user profile is
run to completion **three times per tier, the first discarded as warmup**, with
`n` = retrieval calls counted across the scored runs; each report states its
percentile method and `n`, as that artifact does. ("Passes" is the probe set's
word and does not transfer to a load profile.)

Report to `loadtest/reports/tier-disposition-<sha>.json`, carrying per tier: p95
retrieval latency, the retrieval error rate defined as `(AOSS or S3 Vectors 5xx +
retrieval-path 429s) / retrieval calls issued to that tier` — **Bedrock throttles
are excluded**, being an LLM-call property shared by both tiers and not caused by
the search backend — and the verdict.

**p95 retrieval latency** here is the `router.retrieve()` interval carried on the
per-node retrieval span (Observability, above) — the same interval
`milestones/M04/answer-parity-3966b47.json` measures, embedding call included,
both tiers. It is **not** end-to-end `/query` latency, which is Bedrock-dominated
and would read roughly equal across tiers, letting Tier B survive on noise.

**Tier B keeps its place only if** its p95 retrieval latency is at or below Tier
A's, **or** its retrieval error rate is at least 5 percentage points lower than
Tier A's. If neither holds, Tier B is retired: the `regdelta-search` stack, the
AOSS client, the reindex Lambda and the routing branch are removed, and
`/regdelta/search/endpoint` stops being a tier selector. **Retirement is the
default outcome**; keeping Tier B requires the recorded measurement above. M06
cannot close without disposing of this clause either way. **A difference inside
the recorded run-to-run spread is not an advantage; ties retire.**

*Out of scope for this clause:* leg 1's availability contract is not re-litigated
here, the 100-user profile carries no disposition, and an in-region
re-measurement of M04's sequential number is welcome but is not this bar.
