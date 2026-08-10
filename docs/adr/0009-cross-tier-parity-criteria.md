# ADR-0009: Criterion 1 stands, criterion 3 does not gate, and the hybrid question is deferred

- Status: accepted — Rulings 1 and 2 settled; **Ruling 3 deferred pending the
  `RERANK` measurement** (bounded experiment, see that section)
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

**SPEC/02 criterion 1 requires recall 1.0 on both tiers.** Per fact 1, enforcing
that on this corpus drives BM25 to a weight at which the lexical lane no longer
affects the outcome — i.e. it loses BM25/hybrid.

So criterion 1, enforced literally on the configuration measured, requires
Tier B to stop being the thing ADR-0001 says it exists to be. That tension was
present in the repository before M02 measured anything.

> **An earlier draft of this ADR read that tension as evidence criterion 1 was
> mis-specified. Ruling 1 concludes the opposite**, on the grounds that
> criterion 1 does not require the tiers to agree — it requires each tier
> independently to place every expected chunk in its own top-8 — so a tier
> failing it is a retrieval deficiency rather than a criterion defect. The
> tension is recorded here because it is real and a reader should weigh it; the
> direction it cuts is Ruling 1's subject, and Ruling 3's.

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

## How these rulings were produced, and why that is recorded

**The three rulings below were drafted in the engineering seat, at the PM seat's
request, and adopted by the PM seat.** That is the weakest thing about this
document and it is stated in the first line rather than buried, because
engineering drafting the criteria it was measured against is exactly the
conflict of interest ADR-0003's role separation exists to surface. ADR-0005
already established that no second signature is available here; it does not
follow that provenance stops mattering. A reader weighing these rulings should
discount them accordingly and lean on the falsifiable basis instead: every
number is re-derivable from the two scorecards named under Evidence, and every
textual claim is checkable against SPEC/02 and ADR-0001.

The mitigation actually applied is `pm-spec-reviewer` on this document and the
SPEC/02 diff that follows it — an independent read of acceptance quality, which
matters more here than it would for a ruling the PM seat had drafted unaided.

> **The test applied to each amendment below.** An amendment that changes a
> criterion's *principle* is defensible — it would have been arguable before the
> measurement. An amendment whose new threshold *equals the observed number* is
> curve-fitting and the ruling is worthless. No ruling below sets a new
> numeric threshold; Ruling 2 deliberately declines to propose a lower floor for
> this reason.

---

## Ruling 1 (criterion 1) — recall@8 = 1.0 on both tiers stands unamended

**The criterion, as written** (SPEC/02 "Done when" 1): for every probe, all
`expected_chunk_ids` appear in `router.retrieve(...)` top-8; "Recall@8 must be
1.0 on **both** tiers."

**Bearing evidence.** Facts 1 and 2 above; the ADR-0001 tension.

**RULING. Criterion 1 stands unamended.**

It does not require the tiers to agree. It requires each tier *independently* to
place every `expected_chunk_ids` member in its own top-8 — a requirement about
serving the answer layer, not about cross-tier consistency. (Criterion 3's
remark that "criterion 1 is what must hold identically" means the recall
*outcome* holds on both tiers, not that the result sets match; cross-tier
agreement is criterion 3's subject, and it is ruled on separately below.)

Read that way, the criterion encodes something real. ADR-0008 Ruling 1
established why r01 needs both chunks: a context containing "the compliance date
did not change" *without* the date itself forces the answer layer to generate
"February 25, 2028," which is the failure mode this product exists to prevent.
Tier B's miss of `2025-03118#0003` is therefore a genuine retrieval deficiency
on that tier. A criterion a tier fails is doing its job.

**The counter-argument, and why it loses.** The strongest case for amending: the
only BM25 weight satisfying criterion 1 is 0.05, at which Tier B scores
identically to Tier A. So the criterion, enforced literally, requires Tier B to
abandon the hybrid retrieval ADR-0001 says it exists to demonstrate — and a
criterion that forbids a tier's stated reason for existing is mis-specified.

This loses because it has the inference backwards. That the lexical lane must be
switched off before recall reaches 1.0 is a *measurement of BM25's value on this
corpus*, not evidence that the recall requirement is too strict. ADR-0001
justifies hybrid as a story that "matters to the audience"; a demo narrative is
precisely the kind of claim measurement is permitted to falsify, and preferring
the narrative over the measured recall would invert the project's own ordering.
What to do about the consequence is Ruling 3's subject, not a reason to move
this bar.

**Scope of this ruling.** It settles that the *criterion* is sound. It does
**not** settle whether `2025-03118#0003` is the right expected chunk. Tier B
returns `2025-03118#0005` in its place, and whether `#0005` — *"the compliance
date, and not the effective date, controls when parties must comply … and the
compliance date in the final rule is not until 2028"* — is an acceptable
citation for "did the compliance date change?" is an **SME-seat question**
requiring a primary-source reading of both paragraphs. This ruling is compatible
with either SME outcome: if `#0005` is acceptable, the truth set changes and
Tier B passes a criterion that never moved. It also does not rule on what Tier B
should do about the failure, and it does not endorse any particular BM25 weight.

---

## Ruling 2 (criterion 3) — the 0.60 floor does not stand as a gate

**The criterion, as written** (SPEC/02 "Done when" 3): Jaccard of the full top-8
chunk_id sets across tiers, "computed per probe; the gate is the minimum across
probes"; "Below 0.60 fails." Plus the in-filter carve-out for filtered probes.

**Bearing evidence.** Facts 3 and 4 above.

**RULING. Criterion 3 does not stand as a gate. Cross-tier drift becomes
reported, not gating — the same standing as criterion 4's MRR — and the
in-filter carve-out is deleted.**

The criterion measures Jaccard over the **full top-8** while stating, in the
same paragraph, that "BM25 hybrid and vector+GSI fusion legitimately differ in
the tail." The arithmetic makes those two statements inconsistent on their face:
for two 8-element sets, Jaccard = `c/(16−c)`, so a 0.60 floor requires agreement
on six of eight slots and licenses two. A criterion cannot both concede tail
divergence and permit two slots of it. That inconsistency is derivable from the
spec text alone and required no measurement to find.

The in-filter carve-out goes with it: its premise was that filtered probes'
"long arbitrary tail" would drag the minimum down, and fact 4 falsified that
directly — every filtered probe scored 1.00 while all four failures were
unfiltered. A carve-out protecting against something that does not happen, while
the thing that does happen goes unprotected, is not worth keeping in the spec.

The gating content criterion 3 was reaching for is per-tier expected-chunk
coverage, and criterion 1 already enforces exactly that, per tier and directly.

**The counter-argument, and why it loses.** The strongest case against:
criterion 3 is a canary for a tier broken in a way nine probes do not happen to
test; demoting it removes the only mechanical cross-tier check in the milestone;
and doing so immediately after it went red is textbook relaxation-under-
pressure, by the same seat that built the tier. The demotion is real, and the
timing is genuinely bad. This is the ruling in this document most likely to be
wrong, and the one a reviewer should attack first.

It loses on calibration. Nine probes cannot determine a full-top-8 similarity
threshold, and this milestone proved that point independently on a different
constant: the `RETRIEVAL_PER_DOC_CAP` sweep is non-monotonic on both tiers and
the tiers disagree about which values pass, so nine probes cannot separate
ranking policies at all. A threshold nine probes cannot calibrate is not a gate —
it fires or does not fire according to which tail chunks happened to land. And
it fired here on r04, r05 and r06, where the expected chunk was present on
**both** tiers and both passed criterion 1. A canary that cannot distinguish
collapse from tail churn is not protecting anything, and would not have been
protecting anything had it come back green.

**Scope of this ruling.** It removes the *gate*, not the *measurement*.
Per-probe Jaccard continues to be computed and recorded in every scorecard, and
`make retrieval-parity` continues to run and report — it simply no longer exits
non-zero on drift. It does **not** license ignoring drift: a probe whose Jaccard
collapses toward zero remains a signal an engineer must explain. It does **not**
set a lower floor — proposing 0.33, or any number derived from what was
observed, would be curve-fitting, and the ruling is that a full-top-8 floor is
uncalibratable at this probe-set size, not that it should be looser. It does not
touch criterion 2, which passed on both halves. And it is scoped to *this probe
set*: a probe set large enough to calibrate a similarity threshold could justify
restoring the gate, and that is the correct way to get it back.

---

## Ruling 3 — is a non-hybrid Tier B acceptable? Deferred, pending measurement

The question was unnamed anywhere in the repo before this document, and Ruling 1
is what makes it live: criterion 1 stands, Tier B fails it, and per fact 1 the
only measured configuration satisfying it runs Tier B at BM25 weight 0.05, where
it scores identically to Tier A. ADR-0001's stated purpose for Tier B, and its
stated reason for rejecting S3-Vectors-only, are both the hybrid story.

**RULING. Deferred, pending the `RERANK` measurement — and deliberately so,
because it is not yet established that this question has to be answered.**

The option space is (a) drop BM25, keeping AOSS for the ephemeral-hot-tier and
scale story while removing the hybrid claim from the demo; (b) keep hybrid and
accept Tier B at 7/9, which conflicts with CLAUDE.md's "never mark done until it
passes" and therefore means M02 does not close; or (c) fix the retrieval.

(c) is deferred-to rather than chosen, on three grounds:

1. **SPEC/02 already pre-registered it, before any measurement.** The "Optional"
   section specifies "Claude rerank of top-20 → top-k behind flag `RERANK=1`",
   requires the delta be measured "in recall@8 and MRR on the probe set", and
   requires both `RERANK=0` and `RERANK=1` runs be recorded. "Out of scope"
   excludes reranking *"unless it earns the measured clause"*. So pursuing it is
   executing a clause that predates the failure — the one available option whose
   legitimacy does not depend on any ruling in this document.
2. **The failure signature is the canonical case for reranking.**
   `2025-03118#0003` is ranked 6th–7th by kNN and 14th by BM25 — mediocre on
   both lanes, so RRF has no signal to promote it with. A reranker reads the text
   and asks whether it answers the question, and the chunk states *"the
   compliance date remains unchanged at this time"* against a query asking
   whether the compliance date changed.
3. **It is the only option that resolves the ADR-0001 tension rather than
   choosing a side.** (a) sacrifices the hybrid claim; (b) sacrifices the
   milestone. If reranking earns its clause, criterion 1 is met unamended, Tier B
   stays hybrid, and this ruling never needs an answer.

**What would make this deferral wrong.** If the `RERANK=1` runs show no recall
delta on the probe set, the clause is not earned, reranking stays off per
SPEC/02, and this question returns live as a straight (a)-versus-(b) choice with
one more piece of evidence and nothing lost but the measurement. The deferral is
therefore bounded by a specific experiment, not open-ended — a deferral without
a terminating condition would be this document declining to do its job.

**Two risks the deferral carries, recorded now rather than discovered later.**

- **Ordering decides whether reranking can work at all.** `router._finish`
  applies filters, then `diversify` (the per-document cap), then truncates. The
  cap is what evicts `#0003`. Reranking must run over the top-20 *fused
  candidates, before diversification*; placed after the cap it cannot recover a
  chunk the cap already removed. This is a design decision, not a detail.
- **It puts new code and a Bedrock call on the hot path inside M02**, costs
  latency and money per query, and changes Tier A as well — so both tiers need
  re-measuring and both scorecards move again.

**Scope of this ruling.** It defers the non-hybrid question; it does **not**
pre-approve reranking. Reranking is adopted only if it earns SPEC/02's measured
clause on its own terms, and this document does not relax that clause or
substitute for it. Nor does it rule on ADR-0001, which is lead-seat owned
(`docs/adr/**` → `@regdelta-lead` per ROLES.md): if (a) is eventually chosen,
amending ADR-0001 and the demo's "production-standard hybrid" wording is the
lead seat's to do, and this ruling only scopes what that seat would face.

---

## Consequences

**SPEC/02 changes in one place only.** Criterion 3 is rewritten from a gate to
reported instrumentation, and its in-filter carve-out paragraph is deleted.
Criterion 1 is untouched — the ruling that mattered most left the spec text
alone. `evals/run_parity.py` stops exiting non-zero on drift while continuing to
compute and print it, and criterion 2's resolved-tier assertion stays gating.

**M02 does not close on this document.** Criterion 1 still fails on Tier B, and
Ruling 1 declined to move it. Closure now requires one of: the SME-seat ruling on
`#0005` going in favour of the truth set changing, or the `RERANK` measurement
earning its clause, or Ruling 3 returning live and resolving as (a). No path to
closure runs through relaxing criterion 1.

**Tier B needs re-measuring under any of those paths**, which costs a `make up`
cycle (≈$0.24/hr) and moves both scorecards to a new sha. `evals/retrieval_truth.json`
is untouched by this document; only the SME path would touch it, and that seat
has not ruled.

+ The two criteria that were failing for specification reasons are settled with a
  basis a reader can check, and the one failing for a retrieval reason is left
  failing, which is the correct asymmetry.
+ Ruling 3 is bounded by a named experiment rather than left open.
− The cross-tier gate is gone. Criterion 2 and per-tier criterion 1 remain, but
  nothing mechanically compares the tiers' output after this, and restoring that
  protection properly requires a larger probe set. Recorded as a real loss rather
  than as a tidy simplification.
− These rulings were drafted by the seat they judge (see "How these rulings were
  produced"). `pm-spec-reviewer` is the only independent check applied.
− Ruling 2 is the most likely of the three to be wrong. If the calibration
  argument does not hold, it is relaxation-under-pressure wearing an argument.

## Evidence

- `evals/history/e596166-retrieval-s3vectors.json` — Tier A, 9/9, recall 1.000
- `evals/history/e596166-retrieval-aoss.json` — Tier B, 7/9, recall 0.833
- Both committed in `8b01fc9`; parity output reproduced by `make retrieval-parity`
- Weight and cap sweeps: `milestones/M02/README.md`, sections "The obvious lever
  does not work, and the sweep is why" and "The number this milestone is least
  sure of"; full cap sweep recorded in `src/shared/config.py:27` beside the value
- A reader who doubts any number above should re-run `make retrieval-parity` at
  `e596166` rather than trust this document
