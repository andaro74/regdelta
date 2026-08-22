# ADR-0014: Tier B's disposition — kept, and bounded to the concurrency it was measured at

- Status: **proposed** — drafted at M06 close, awaiting the human seat.
- Date: 2026-08-21
- Milestone: M06
- Closes: ADR-0001's open question, on the bar ADR-0012 Ruling 3 set before any
  M06 number existed.
- **Drafted in the engineering seat.** The same weakness ADR-0012 records about
  itself applies: engineering measured this and engineering is writing it up.
  Read it as a proposal. What makes it checkable is that every figure below is
  in `milestones/M06/tier-disposition-f651aea.json`, which was written by the
  gate rather than by me, and the tag `m06-disposition` preserves the commit it
  was judged at.

## Context

ADR-0001 chose two tiers. ADR-0012 then retired the *reason* — Tier B's latency
leg — after M04 measured 889.3 ms against Tier A's 354.1 ms, and left Tier B
with one remaining case, concurrency, and a deadline: SPEC/06 would carry a bar
that keeps or retires it, with **retirement as the default outcome**.

That bar was written into SPEC/06 before M06 produced any number to fit it to.
It was also, as written, **unrunnable** — found in M06 session one, before
anything was spent — and was amended by a ruling with sources
(`milestones/M06/spec06-disposition-amendment.md`) that changed what the
measurement *is*, not what would count as passing it.

## Decision

**Tier B is kept.** At the dispositive step of the retrieval-concurrency
profile, AOSS p95 retrieval latency was **185.9 ms** against S3 Vectors'
**281.4 ms**, so the latency disjunct holds and the default outcome does not
apply.

**And the verdict is recorded as bounded, not general.** It says Tier B is
faster at 10–50 calls/s on this corpus from this vantage. It does not say Tier B
is faster, and it does not say anything about OpenSearch Serverless — the clause
disposes of a stack, a client, a reindex Lambda and a routing branch in *this*
repo.

## Alternatives considered

- **Retire Tier B anyway, on the grounds that the win is outside the band that
  matters.** The KEEP was measured at 7.4-way (AOSS) and 10.7-way (S3 Vectors)
  in-flight, below the 11.4–25.8 the real workload applies. Rejected because the
  clause names its own condition and the condition was met; moving the bar after
  seeing the number is the failure ADR-0012 was careful to avoid by fixing the
  figures in advance. The right response to an unmeasured band is to measure it
  (M07), not to rule on it by assumption.
- **Declare the win general.** Rejected: three recorded limitations bound it,
  and one of them — the driver saturating at 75 and 90 calls/s — means the
  profile never reached the rates the schedule specified.
- **Re-run with a larger driver before ruling.** Rejected for M06: the spec says
  the first run completed at this schedule is the record, and a re-run to obtain
  a better number is exactly what that sentence exists to prevent. M07 raises
  the driver as new work, with its own report.

## Consequences

- `regdelta-search`, the AOSS client, the reindex Lambda and the
  `/regdelta/search/endpoint` routing branch all stay. So does the operational
  cost of the ephemeral tier: `make up` starts OCU billing, and the janitor at
  01:00 UTC plus `make down` remain the only brakes.
- **Both tiers keep running the same algorithm on different infrastructure**
  (ADR-0009 Ruling 3(a)). Nothing here re-opens the lexical lane.
- **What would revisit this:** M07's 10240 MB driver reaching the 11.4–25.8
  band. If Tier B loses there, this ADR is superseded rather than amended — the
  band it was silent about is the band that decides.
- **A pooled AOSS client would strengthen the KEEP, not weaken it.** The current
  client opens a TCP+TLS connection per call while S3 Vectors pools through
  botocore, so the handicap runs against the tier that won.

## Evidence

`milestones/M06/tier-disposition-f651aea.json`, judged at `f651aea`
(tag `m06-disposition`), written by `make tier-disposition`, which exits
non-zero on a dirty sha, disagreeing corpus fingerprints, a half answered from
the wrong tier, or no qualifying step.

Dispositive step **50 calls/s**:

| | AOSS | S3 Vectors |
|---|---|---|
| p95 retrieval | **185.9 ms** | 281.4 ms |
| p50 retrieval | 139.4 ms | 199.8 ms |
| n (pooled, 2 scored runs) | 5996 | 6000 |
| error rate | 0.000667 | 0.0 |
| in-flight mean | 7.43 / 7.36 | 10.67 / 10.88 |

One attempt per tier across a single `make up`/`make down` cycle at one sha;
`corpus_agree: true` (`35a293e17117`); `config_agree: true`; `failures: []`;
`prior_failed_measurements_per_tier: 0/0`; percentiles nearest-rank; the Tier A
half taken with the collection destroyed.

**The comparability condition was checked before the comparison was made.** The
two error rates are within the clause's own 5-percentage-point materiality, so
the p95s describe comparable surviving populations. The error-rate disjunct does
**not** hold and is recorded as not holding — the verdict rests on latency
alone.

**Three recorded limitations**, two of which run against Tier B:

1. `aoss-client-opens-a-connection-per-call` — unmeasured; direction against
   Tier B.
2. `aoss-per-call-credential-cost-was-fixed-not-controlled-for` — 6.430 ms
   median of GIL-bound CPU inside the measured interval, AOSS path only,
   memoised at M06. **ADR-0012's 889.3 ms rests on a measurement taken with this
   present**, so M04's number and this one are not a before/after of the same
   instrument.
3. The 2048 MB driver could not reach 75 or 90 calls/s (achieved 66–79/s with
   dispatch refusals at the thread ceiling). The instrument's ceiling, not
   either tier's; now recorded in SPEC/06 so it is not re-bought.
