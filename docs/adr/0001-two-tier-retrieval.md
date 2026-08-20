# ADR-0001: Two-tier retrieval (S3 Vectors always-on, AOSS ephemeral)

- Status: accepted — **amended at M02 close**. The decision stands; **the reason
  given for it does not.** See "Amendment (M02)".
- Date: (project start); amended 2026-08-11
- Milestone: M02
- Amended by: lead seat (`docs/adr/**` → `@regdelta-lead`, ROLES.md), acting on
  ADR-0009 Ruling 3(a), which explicitly declined to rule here and scoped what
  this seat would face.
- **Drafted in the engineering seat at the lead seat's request.** Same weakness
  ADR-0009 records about itself, and it is worse here: this document is being
  amended because engineering's own measurement falsified it. Read the amendment
  as a proposal, not a signature.

## Context
The demo idles most of the time; OpenSearch bills continuously. But the
production-standard hybrid (BM25+kNN) story matters to the audience.

## Decision
S3 Vectors is the always-on tier (pay-per-request, <$2/mo idle). AOSS
vector search collection (dev mode, ~$0.24/hr) is an ephemeral hot tier,
hydrated from S3 on `make up`, destroyed after each session. Routing seam:
SSM /regdelta/search/endpoint. Both tiers must pass the same golden set.

## Alternatives considered
- Always-on AOSS — ~$175+/mo idle for a demo.
- S3 Vectors only — loses BM25/hybrid and the enterprise scale story.
- Managed OpenSearch domain up/down — 20-40 min spin-up, too slow per session.

## Consequences
+ Idle cost ≈ zero; live tier-switch is itself a demo moment.
- Two retrieval code paths to keep at eval parity (enforced by CI matrix).

## Evidence
Recorded per milestone in milestones/M02/scorecard (eval pass rate per tier,
retrieval p50 per tier).

---

## Amendment (M02) — the decision stands, its justification does not

Everything above is left as written. It is the record of why this was decided, and
it was reasonable when decided; the measurement that contradicts it did not exist
yet. Three specific claims are now false, and one obligation was not met.

### What the measurement did to this ADR

Tier B was justified by hybrid retrieval. Measured on the live hot tier at one
commit, **hybrid scored 7/9 probes against vector-only's 9/9** (`b16f596`
scorecards). The two failures were one chunk, `2025-03118#0003`, which BM25 ranks
14th or not at all while preferring a shorter chunk that repeats the query's terms
without answering it. The only BM25 weight satisfying SPEC/02 criterion 1 is 0.05,
where the lane has stopped affecting the outcome. A reranker was tried against a
bar pre-registered *before* the run; it recovered that chunk and broke Tier A
(9/9 → 8/9), and did not clear the bar. ADR-0009 Ruling 3(a) therefore turned the
lexical lane off by default.

**So the two tiers now run the same algorithm on different infrastructure.** Their
scorecards agree to sixteen digits of MRR.

### Three corrections

1. **Context: "the production-standard hybrid (BM25+kNN) story matters to the
   audience."** The story does not survive the measurement. It is not that hybrid
   was hard to tune — it is that on this corpus the lexical lane makes retrieval
   *worse*, for a reason specific to regulatory prose: preamble paragraphs that
   restate the question's terms outrank the short paragraph that answers it.
2. **Alternatives: "S3 Vectors only — loses BM25/hybrid and the enterprise scale
   story."** The BM25/hybrid leg is **gone**. The scale leg is **unmeasured** —
   and the only latency-adjacent number in the repo, whole-run `wall_s`, has AOSS
   *slower* in every recorded pair (11.6 vs 6.7 at `b16f596`). That is not
   per-query latency and does not establish Tier B is slower, but it plainly does
   not support the claim either. **The rejection of the simplest alternative now
   rests entirely on an unmeasured assertion.** That is the uncomfortable sentence
   in this amendment and it should not be softened.

   **Updated at M04.** The latency half of this leg is measured and gone; only
   concurrency and scale remain unmeasured, and SPEC/06 carries the bar that
   disposes of them (ADR-0012).
3. **Consequences: "Two retrieval code paths to keep at eval parity (enforced by
   CI matrix)."** There is no CI matrix. `.github/workflows/evals.yml` contains no
   tier matrix and never has. Cross-tier eval parity is enforced by
   `make retrieval-parity` run by hand, and at answer level it is homed in
   SPEC/04's "Done when" and **not yet met**.

### One obligation not met

The Evidence line above asks for **retrieval p50 per tier** at M02. It was not
recorded. It is deferred to SPEC/04's latency criterion and **recorded as
deferred, not met** — which matters more than usual, because it is the only
evidence that would substantiate what is left of Tier B's justification.

### RULING (proposed). Keep two tiers. Restate the justification. Attach a
reversal condition.

Tier B is kept, and what it earns its place with is restated as:

1. **The availability contract, which requires a second heterogeneous backend to
   be real.** When the hot tier is absent or unreachable, the always-on tier
   answers — `router.retrieve_traced` catches `AossError` and falls back, carrying
   the reason out on `Resolution` so a fallback cannot be silently reported as
   coverage (SPEC/02 criterion 2). That is a genuine production property, it is
   tested, and it cannot be demonstrated with one backend.
2. **Latency and scale — pending measurement**, per SPEC/04. Say "same algorithm,
   different infrastructure" until that number exists. Do not say "hybrid", and
   do not say "faster".

> **The circularity risk in leg 1, named rather than hidden.** "We keep the second
> tier because having two tiers let us build two-tier machinery" is not a
> justification. Leg 1 is non-circular only to the extent that the *fallback* is a
> real availability property rather than scaffolding — a deployed-but-broken hot
> tier not taking the API down is worth something on its own terms. That is a
> thinner claim than the hybrid story it replaces, and it should be read as
> thinner.

**Reversal condition.** If SPEC/04's latency measurement shows **no material
per-query advantage** for Tier B at this corpus size, then leg 2 is gone, leg 1
alone is a thin justification for ~$0.24/hr plus a second index, a hydration
Lambda, a data-access policy and a reindex path — and **this ADR should be
reopened to consider dropping Tier B entirely**, collapsing to S3 Vectors only.
That is the alternative this document rejected, and two of the three reasons it
gave for rejecting it have now weakened. Symmetric with Ruling 3(a)'s own
reversal condition: the decision is conditional on evidence that does not exist
yet, and saying so is what keeps it a decision rather than a preference.

**Fired at M04.** SPEC/04's latency measurement showed Tier B ~2.5x slower at the
median (`milestones/M04/answer-parity-3966b47.json`). Leg 2 is gone; this
reopening is disposed of by **ADR-0012**, which keeps leg 1, retires the latency
claim, and homes a keep-or-retire bar in SPEC/06.

**What this amendment does NOT do.** It does not reverse the decision, does not
touch the cost argument (always-on AOSS at ~$175+/mo idle, and the 20–40 minute
managed-domain spin-up, are both untouched and still correct), and does not amend
SPEC/00's demo narrative beyond the routing-seam line already corrected there. The
live tier-switch demo beat survives, with its meaning changed: it now demonstrates
**that the answer does not change when the infrastructure does** — which is the
contract, and is a better thing to show than a relevance claim the scorecards
contradict.
