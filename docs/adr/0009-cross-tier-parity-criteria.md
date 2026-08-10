# ADR-0009: Cross-tier parity criteria — PM-seat rulings on SPEC/02 criteria 1 and 3

- Status: **proposed — rulings not yet made** (see "What this document is waiting for")
- Date: 2026-08-10
- Milestone: M02
- Basis: PM-seat ruling; basis is the measured scorecards and SPEC/02's own
  text, both in git; no second approver exists (ADR-0005)
- Relates to: SPEC/02 "Done when" criteria 1 and 3; ADR-0001 (two-tier
  retrieval); ADR-0008 (the SME-seat precedent for ruling shape)

## Context

M02 measured both retrieval tiers live, at one commit, and ran the cross-run
parity gate. Two of SPEC/02's four gating criteria fail, and neither failure is
an unfinished implementation task. Both are findings about how the criteria were
specified, and SPEC/02 assigns the resulting decision to the PM seat in its own
words: the criterion-3 floor and aggregation "may not be changed to match
whatever is observed — changing either is a spec edit requiring PM approval."

### The measurement

Both scorecards were recorded at `e596166` and committed in `8b01fc9`. They are
the falsifiable basis for everything below; a reader can re-derive every number
here from those two files plus `evals/run_parity.py`.

| | Tier A (S3 Vectors) | Tier B (AOSS hybrid) |
|---|---|---|
| probes passed | **9/9** | **7/9** |
| recall@8 | **1.000** | **0.833** |
| MRR (reported, non-gating) | 0.796 | 0.648 |

Tier B's two failures are **one chunk**: `2025-03118#0003`, the paragraph
carrying *"the compliance date remains unchanged at this time"*, missing on r01
and r03. It is preamble, so the structural lane cannot reach it and it competes
on relevance alone. kNN ranks it 6th and 7th — the same signal Tier A uses.
BM25 ranks it 14th on r03 and does not return it at all on r01, preferring
`2025-03118#0005`, which is shorter and repeats the query terms more.
Equal-weight RRF loses it; the per-document cap of 3 then fills the document's
slots with `#0001`/`#0005`/`#0000`.

Criterion 3, per-probe Jaccard against a floor of 0.60:

| probe | Jaccard | filtered | note |
|---|---|---|---|
| r01 | **0.33** | | 4 of 8 slots shared — the gating minimum |
| r02 | 1.00 | ✔ | in-filter set only |
| r03 | **0.45** | | |
| r04 | **0.45** | | |
| r05 | **0.45** | | |
| r06 | 0.60 | | passes *exactly* at the floor — no slack |
| r07 | 1.00 | ✔ | in-filter set only |
| r08 | 1.00 | ✔ | in-filter set only |
| r09 | 1.00 | ✔ | in-filter set only |

**Criterion 2 passes** on both halves (resolved tiers distinct, assertion held
on both runs) and is not in scope here.

### Four facts the measurement established

**1. Criterion 1 as written is satisfiable only by deleting the lexical lane.**
Down-weighting BM25 is the intuitive fix. The sweep: r03 flips at weight 0.25,
r01 only at 0.05 — and at 0.05 Tier B scores recall 1.000 / MRR 0.796,
numerically identical to Tier A, because the lexical lane has stopped affecting
the outcome. The only weight that satisfies criterion 1 is the one at which
Tier B is no longer hybrid.

**2. No other lever reaches 9/9.** The per-document cap is non-monotonic on
both tiers and the tiers disagree about which values pass (Tier B: cap 3 → 7/9,
4 → 8/9, 5 → 7/9; Tier A: 9/9, 8/9, 9/9). A value that fails between two
passing values means nine probes cannot determine the constant. Separately,
BM25 `minimum_should_match: 70%` took Tier B from 6/9 to 8/9 and was **not
adopted**: at 70% BM25 stops matching *short* chunks — r09's amendatory-
instructions paragraph contains neither "Red", "No. 3", nor "sections" — so the
setting improves the aggregate by penalising exactly the short structural chunks
the mechanism exists to surface. Its mechanism runs backwards to its purpose.

**3. Criterion 3's floor licenses two slots of divergence, not "a tail."** For
two 8-element sets, Jaccard = `c / (16 - c)`, so 0.60 requires `c = 6` —
agreement on six of eight slots. The same criterion concedes in prose that
"BM25 hybrid and vector+GSI fusion legitimately differ in the tail." Observed
divergence is three slots on r03/r04/r05. On **r04, r05 and r06 the divergence
is entirely non-expected tail**: the expected chunk is present on both tiers and
all three pass criterion 1 on both. The gate is failing on precisely the
difference the criterion calls legitimate. On r01 and r03 the differing member
includes `2025-03118#0003`, which is fact 1's miss, not a separate defect.

**4. The in-filter carve-out protected the wrong probes.** SPEC/02 computes
Jaccard over the in-filter result set only, reasoning that "a filtered probe
returns few in-filter hits and a long arbitrary tail … so one filter probe could
drag the per-probe minimum under 0.60 and fail M02 for a reason unrelated to
correctness." That was settled before first measurement, correctly, on the
reasoning then available. Measured: every filtered probe scores **1.00**, and
all four failures are **unfiltered**. The instinct was right; the target was
wrong.

### The conflict that does not depend on the failing number

This is the part a reader should weigh most heavily, because it is arguable
from two documents alone, with no reference to any measurement.

**ADR-0001 states that Tier B exists to be hybrid.** Its Context: "the
production-standard hybrid (BM25+kNN) story matters to the audience." Its
rejected alternative: "S3 Vectors only — loses BM25/hybrid and the enterprise
scale story."

**SPEC/02 criterion 1 requires recall 1.0 "on both tiers", identically.** Per
fact 1, enforcing that on this corpus drives BM25 to a weight at which the
lexical lane no longer affects the outcome — i.e. it loses BM25/hybrid.

So criterion 1, enforced literally, requires Tier B to stop being the thing
ADR-0001 says it exists to be. That contradiction was present in the repository
before M02 measured anything, and it is the reason these rulings are a
specification question rather than a request to lower a bar that was missed.

### Why engineering did not settle this

Two of three ranking changes tried during M02 traded one probe for another,
which is the signal that nine probes cannot distinguish these ranking policies.
Continuing to change policy until the number went green would have produced a
1.0 certifying nothing — the exact hazard SPEC/02 named for a probe set
engineering authored, chose `k` for, and needs 100% on. The alternative
available to engineering was to relax `evals/retrieval_truth.json`, which is a
ground-truth relaxation proposed *because a tier failed*, and CLAUDE.md routes
that to a stop. Both roads led out of the engineering seat, so the work stopped
and recorded the failing scorecards as evidence.

## What this document is waiting for

Three rulings. The sections below are deliberately unfilled. Each states the
question, the evidence bearing on it, and the option space as measured — not a
recommendation, because a recommendation from the seat that built the tier is
the thing the governance model exists to prevent.

> **The test to apply to any amendment written below.** An amendment that
> changes a criterion's *principle* is defensible — it would have been arguable
> before the measurement. An amendment whose new threshold *equals the observed
> number* is curve-fitting and the ruling is worthless. If a new floor comes out
> at 0.33, or a new Tier B recall bar at 0.833, the ruling has been written by
> the measurement rather than about it.

---

## Ruling 1 (criterion 1) — does "recall@8 = 1.0 on both tiers" stand?

**The criterion, as written** (SPEC/02 "Done when" 1): for every probe, all
`expected_chunk_ids` appear in `router.retrieve(...)` top-8; "Recall@8 must be
1.0 on **both** tiers."

**Bearing evidence.** Facts 1 and 2 above; the ADR-0001 conflict.

**The option space, as measured.**

- *Stands as written.* Tier B must reach 9/9. Per facts 1–2 the only
  configuration that does so is BM25 weight 0.05, which makes Tier B
  numerically identical to Tier A — so this option resolves into Ruling 3.
  Alternatively the truth set relaxes, which is an SME-seat question (below,
  and it is the one CLAUDE.md routes to a stop).
- *Amended in principle.* Some formulation other than full identity across
  tiers. What formulation, and why it would have been arguable in advance, is
  the substance of the ruling.

**RULING:** _(unfilled)_

**The counter-argument, and why it loses:** _(unfilled — required; see ADR-0008,
which carries one per ruling. A ruling without this section is not finished.)_

**Scope of this ruling:** _(unfilled — state what it does NOT cover, so a later
reader cannot over-read it.)_

---

## Ruling 2 (criterion 3) — does the 0.60 floor, and the per-probe-minimum
aggregation, stand?

**The criterion, as written** (SPEC/02 "Done when" 3): Jaccard of the full top-8
chunk_id sets across tiers, "computed per probe; the gate is the minimum across
probes"; "Below 0.60 fails." Plus the in-filter carve-out for filtered probes.

**Bearing evidence.** Facts 3 and 4 above.

**The option space, as measured.** Three distinguishable things could move, and
the ruling should say which:

- the **floor** (0.60),
- the **aggregation** (per-probe minimum vs some other statistic),
- **what the set is computed over** (full top-8 vs expected chunks vs the
  in-filter carve-out, whose premise fact 4 falsified).

**RULING:** _(unfilled)_

**The counter-argument, and why it loses:** _(unfilled — required.)_

**Scope of this ruling:** _(unfilled.)_

---

## Ruling 3 — if criterion 1 stands, is a non-hybrid Tier B acceptable?

This question is currently unnamed anywhere in the repo, and Ruling 1's first
option resolves into it. Per fact 1, satisfying criterion 1 literally means
running Tier B at BM25 weight 0.05, where it scores identically to Tier A.
ADR-0001's stated purpose for Tier B, and its stated reason for rejecting
S3-Vectors-only, are both the hybrid story.

If the answer is yes, ADR-0001 needs amending and the demo's "production-
standard hybrid" claim needs re-wording — a non-hybrid AOSS tier is an
expensive way to reproduce Tier A's results. If no, criterion 1 cannot stand as
written and Ruling 1 follows.

**RULING:** _(unfilled)_

**Consequences for ADR-0001:** _(unfilled — ADR-0001 is lead-seat owned
(`docs/adr/**` → `@regdelta-lead` per ROLES.md); this ruling scopes what the
lead seat then has to change, if anything.)_

---

## Consequences

_(unfilled until the rulings are made. Should state, at minimum: whether Tier B
requires re-measurement — which costs a `make up` cycle — and whether
`evals/retrieval_truth.json` is touched, which would route to the SME seat.)_

## Evidence

- `evals/history/e596166-retrieval-s3vectors.json` — Tier A, 9/9, recall 1.000
- `evals/history/e596166-retrieval-aoss.json` — Tier B, 7/9, recall 0.833
- Both committed in `8b01fc9`; parity output reproduced by `make retrieval-parity`
- Weight and cap sweeps: `milestones/M02/README.md`, sections "The obvious lever
  does not work, and the sweep is why" and "The number this milestone is least
  sure of"; full cap sweep recorded in `src/shared/config.py:27` beside the value
- A reader who doubts any number above should re-run `make retrieval-parity` at
  `e596166` rather than trust this document
