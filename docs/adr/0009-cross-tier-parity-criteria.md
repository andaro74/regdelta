# ADR-0009: Criterion 1 stands, criterion 3's similarity floor does not, and the hybrid question is deferred

- Status: accepted — Rulings 1 and 2 settled; **Ruling 3 deferred pending the
  `RERANK` measurement** (bounded experiment, see that section)
- Date: 2026-08-10
- Milestone: M02
- Basis: PM-seat ruling; basis is the measured scorecards and SPEC/02's own
  text, both in git; no second approver exists (ADR-0005)
- Relates to: SPEC/02 "Done when" criteria 1 and 3; ADR-0001 (two-tier
  retrieval); ADR-0008 (the SME-seat precedent for ruling shape)
- Revised after `pm-spec-reviewer` returned REQUEST CHANGES on the first version;
  the corrections it forced are marked inline as "an earlier draft" rather than
  edited away, in fact 4, Ruling 2, the anti-fitting test, and Ruling 3 ground 1.
- Venue note: this record sits in `docs/adr/**`, which ROLES.md assigns to
  `@regdelta-lead`, while its rulings are PM-seat and its drafting was
  engineering's. An ADR was chosen because the decision spans SPEC/02, ADR-0001
  and ADR-0008 and no single owned artifact contains it; the SPEC/02 amendment it
  licenses is the PM-owned half and lands separately.

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

**2. No other lever reaches 9/9.** The per-document cap is non-monotonic on the
live Tier B measurement: cap 3 → 7/9, 4 → 8/9, 5 → 7/9. A value that fails
between two passing values means nine probes cannot determine the constant.

> **The Tier A cap row is stale and is not relied on here.**
> `milestones/M02/README.md` records it: "The Tier A row was measured before
> `7d65a07` and has not been re-swept." `7d65a07` deleted the
> top-N-distinct-documents heuristic, its window bound, its per-document chunk
> cap and the grouped-vs-interleaved ordering question — so that row describes a
> retrieval path that no longer exists. An earlier draft of this ADR quoted both
> rows uncaveated and claimed "the tiers disagree about which values pass";
> that comparison is not currently established, and the sweep recorded at
> `src/shared/config.py:27` carries the same stale row. The argument above needs
> only Tier B's live row and is restated on it alone. Re-sweeping Tier A costs
> nothing and would settle it.

Separately,
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

**4. The in-filter carve-out's premise was CONFIRMED, and its implementation is
a tautology.** SPEC/02 computes Jaccard over the in-filter result set only,
reasoning that "a filtered probe returns few in-filter hits and a long arbitrary
tail … so one filter probe could drag the per-probe minimum under 0.60 and fail
M02 for a reason unrelated to correctness." Every filtered probe scores 1.00 and
all four failures are unfiltered — which looks like the carve-out guarding
against something that does not happen, and an earlier draft of this ADR read it
that way. **That reading was wrong on both halves.**

`evals/run_parity.py:117` approximates the in-filter set as
`expected_chunk_ids ∪ must_not_return` — "the only ids whose membership the probe
actually asserts", in its own comment. r07, r08 and r09 each carry one expected
chunk and an empty `must_not_return`, so the scope is a **single chunk id**, both
tiers return it (criterion 1 passed), and Jaccard is 1/1 *by construction*. Those
three 1.00s carry no information about tail agreement at all. r02's scope is one
expected plus six forbidden, and its 1.00 restates criterion 1 and
`must_not_return` and nothing else.

Removing the carve-out and computing full top-8 on the same two scorecards gives
the opposite of the earlier reading:

| filtered probe | in-filter (reported) | full top-8 |
|---|---|---|
| r02 | 1.00 (scope = 1 id + 6 forbidden) | 0.78 |
| **r07** | 1.00 (scope = 1 id) | **0.23** |
| r08 | 1.00 (scope = 1 id) | 0.78 |
| r09 | 1.00 (scope = 1 id) | 0.60 |

r07 at 0.23 would be the **new gating minimum, below r01's 0.33** — a filtered
probe dragging the gate under the floor while both tiers return its single
expected chunk, its divergence being Tier B filling slots with
`cfr-21-101.65` version variants where Tier A fills with `2024-29957` preamble.
That is verbatim the scenario SPEC/02 wrote the carve-out to prevent. **The
carve-out's reasoning was right and is vindicated; what is defective is the
approximation standing in for it**, which degenerates whenever
`must_not_return` is empty and `expected_chunk_ids` has one member — i.e. it
exempts filtered probes from the measurement rather than measuring them
in-filter. SPEC/02 says "computed over the in-filter result set" without
defining how to derive that set from a filter predicate, and the implementation
silently filled the gap.

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

> **The test applied to each amendment below**, in the form it survived review.
> An amendment must be one a reader can see would have been proposed **against a
> green measurement**. Two corollaries, because the first draft of this test could
> not fail the move Ruling 2 actually made:
>
> 1. *No fitted thresholds.* An amendment whose new threshold equals an observed
>    number is curve-fitting. Ruling 2 rejects a c=5 floor and a
>    minimum→mean switch on exactly this ground.
> 2. *A removal must clear a higher bar than a loosening,* because "changes the
>    principle" would otherwise license deletion outright — removal being the
>    maximal change to a principle — and a deleted gate passes any
>    threshold test trivially, having no threshold. **A ruling that removes a gate
>    must show which narrower gate was considered and why that also fails.**
>    Ruling 2's aggregation sweep exists to discharge this, and it is why that
>    ruling now replaces the floor rather than deleting it.

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

**The second counter-argument, which is the repo's own and is stronger.**
SPEC/02 says of the probe set: "a 3-probe set that engineering authored, selected
`k` for, and needs 100% on is self-certifying." Criterion 1 demands 100% on nine
self-authored probes with `k` chosen by the same seat, so a single probe is 11.1%
and there is no failure budget anywhere in the criterion. Declaring such a
criterion "sound" without engaging the property the repository itself flags as its
weakest would be a gap in a ruling whose whole job is to certify soundness.

It does not overturn the ruling, for two reasons. The mitigations SPEC/02 names
are real and were met — two distractor probes, `must_not_return` assertions on
both, and ADR-0008 recording the two judgment-bearing entries with primary
sources. More decisively, **the specific chunk Tier B misses is not justified by
the probe set at all.** `2025-03118#0003` is required by ADR-0008 Ruling 1, on
Federal Register text a reader can check, authored before any tier was measured.
So the failing assertion does not depend on the probe set being large enough to
certify itself; it depends on a sourced regulatory ruling. What the
self-certification objection does establish is that **recall 1.0 on nine probes
should never be quoted as a retrieval-quality claim** — SPEC/02 and the M02
evidence pack both already say so, and this ruling does not license reading it
that way.

**Scope of this ruling.** It settles that the *criterion* is sound. It does
**not** settle whether `2025-03118#0003` is the right expected chunk. Tier B
returns `2025-03118#0005` in its place, and whether `#0005` — *"the compliance
date, and not the effective date, controls when parties must comply … and the
compliance date in the final rule is not until 2028"* — is an acceptable
citation for "did the compliance date change?" is an **SME-seat question**
requiring a primary-source reading of both paragraphs. This ruling is compatible
with either SME outcome: if `#0005` is acceptable, the truth set changes and
criterion 1's *text* never moves — though its substance does, and Consequences
records that path as the one carrying the highest evidentiary burden, not the
easiest.

**One consequence of that SME path, recorded here so it is not discovered
later.** ADR-0008 Ruling 1 requires **two** chunks for r01 on the reasoning that
a context saying the date did not change, *without the date*, forces the model to
generate "February 25, 2028". `#0005` states "the compliance date in the final
rule is not until 2028" — the **year, not the full date**, so it does not simply
satisfy that reasoning. But it comes close enough that an SME ruling accepting
`#0005` would have to say why `2024-29957#0000` is still required, i.e. it
reopens ADR-0008 Ruling 1's two-chunk holding rather than only r01's expected
set. r01 is q01's retrieval precondition and q01 is the trap this product exists
to defeat.

This ruling also does not rule on what Tier B should do about the failure, and it
does not endorse any particular BM25 weight.

---

## Ruling 2 (criterion 3) — the 0.60 similarity floor is replaced by an anti-collapse floor; the carve-out stays and its implementation is defective

**The criterion, as written** (SPEC/02 "Done when" 3): Jaccard of the full top-8
chunk_id sets across tiers, "computed per probe; the gate is the minimum across
probes"; "Below 0.60 fails." Plus the in-filter carve-out for filtered probes.
SPEC/02 makes **both the floor and the aggregation** PM-approvable.

**Bearing evidence.** Facts 3 and 4 above, plus the aggregation sweep below.

**RULING, in three parts.**

**(i) The 0.60 similarity floor does not stand.** The criterion measures Jaccard
over the **full top-8** while stating, in the same paragraph, that "BM25 hybrid
and vector+GSI fusion legitimately differ in the tail." The arithmetic makes
those inconsistent on their face: for two 8-element sets, Jaccard = `c/(16−c)`,
so a 0.60 floor requires agreement on six of eight slots and licenses two. A
criterion cannot both concede tail divergence and permit two slots of it. That is
derivable from the spec text alone and required no measurement to find.

**(ii) The in-filter carve-out STAYS. Its implementation is defective and must be
replaced.** Per fact 4, the carve-out's reasoning is vindicated — r07's full
top-8 Jaccard is 0.23, which would gate M02 on a probe where both tiers return
the expected chunk. What is broken is `run_parity.py:117`, which approximates the
in-filter set as `expected ∪ must_not_return` and thereby exempts rather than
measures any probe with one expected chunk and no forbidden ones. SPEC/02 must
define the in-filter set from the **filter predicate** — the chunks that satisfy
`Filters.matches` — so the carve-out measures what it claims to.

**(iii) The gate becomes an anti-collapse floor, stated as a principle:** the two
tiers must share, per probe, **every chunk criterion 1 requires plus at least one
further slot.** This is not a similarity threshold and is not derived from any
observed value. It encodes the one thing a cross-tier gate can assert on nine
probes — that the tiers have not become effectively disjoint — and it fires only
on collapse, which is what SPEC/02 said the aggregation was for ("so one
collapsed probe cannot hide behind seven healthy ones").

**Why not a narrower similarity gate? Measured, not asserted.** SPEC/02 put the
aggregation in scope, so the window and the statistic were swept on the same two
scorecards. At a 0.60 floor, the set of probes that fails changes almost
completely with the window:

| aggregation | probes that fail | count |
|---|---|---|
| full top-8 (as specified) | r01 .33, r03 .45, r04 .45, r05 .45 | 4 |
| top-3 prefix | r01 .50, r02 .50, r04 .20, r06 .50, r07 .50, r09 .20 | 6 |
| top-4 prefix | r04 .33, r06 .33, r09 .33 | 3 |
| top-5 prefix | r01 .43, r04 .25, r05 .43, r06 .43, r07 .43, r09 .25 | 6 |

r03 scores **1.00 at top-3 and 0.45 at top-8**. r06 **passes at top-8 and fails
at top-4 and top-5**. The head diverges *more* than the full set on r04 and r09.
So the gate's verdict is an artifact of the window rather than a property of the
tiers, and this is evidence about *this statistic on this probe set* — not
borrowed from the cap sweep. Two specific alternatives were also rejected on the
anti-fitting test: a floor at c=5 (Jaccard 0.4545) passes r03/r04/r05 exactly and
fails only r01, and switching the aggregation from minimum to mean yields 0.698
and a pass. Both reproduce the observation too precisely to be anything but
fitted, and the mean additionally discards the property SPEC/02 chose the minimum
for.

**The counter-argument, and why it loses.** The strongest case against: replacing
a similarity floor with an anti-collapse floor that **currently passes on all nine
probes** (minimum shared slots = 3, on r07) is a gate that gates nothing, and
ADR-0005's own closing warns that "asserting a control and never exercising it is
the exact failure mode this product exists to catch in regulatory text." Swapping
a gate that fires for one that does not, by the seat that failed the first one, is
relaxation with extra steps.

It loses, but only partly, and the remainder is conceded. The anti-collapse floor
*is* exercised — it runs on every parity invocation and evaluates a real
condition; it is not an unreachable requirement of the kind ADR-0005 found in the
CODEOWNERS ruleset. And the similarity floor it replaces cannot be defended at
this probe-set size, per the sweep above. But the honest accounting is that
**cross-tier protection is weaker after this ruling than before it**, and the
sound fix is a probe set large enough to calibrate a similarity threshold, which
is out of M02's scope. What is not defensible is keeping a floor whose verdict
flips with an arbitrary window choice.

**What this ruling does not claim.** It does **not** claim the failing gate was
pure noise. Of the four probes that fired, **two (r01, r03) tracked the genuine
criterion-1 miss** of `2025-03118#0003` and two (r04, r05) were tail churn — so
the gate ran at roughly 50% precision on nine probes, which is weak, not empty.
An earlier draft of this ruling said the gate "fired here on r04, r05 and r06"
and that a canary of this kind "is not protecting anything." **Both were wrong:**
r06 scored 0.60 and *passed* at the floor with zero slack, and the 50% figure is
in this document's own fact 3.

**Scope of this ruling.** Per-probe Jaccard over the full top-8 continues to be
computed and recorded in every scorecard and printed by `make retrieval-parity`,
as reported instrumentation — the *similarity* number stops gating; the
anti-collapse condition starts. It does **not** set a lower similarity floor;
proposing 0.33, 0.45, or c=5 would be curve-fitting, and the finding is that a
full-top-8 similarity floor is not calibratable at nine probes, not that it should
be looser. It does not touch criterion 2, which passed on both halves. It does
**not** authorise the `run_parity.py` change that (ii) requires — that is
implementation, and per ROLES.md flow 3 it follows PM approval of the spec diff
rather than accompanying it. And it is scoped to *this probe
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

1. **SPEC/02 pre-registered the mechanism and the instrument, before any
   measurement — but not an adoption bar.** The "Optional" section specifies
   "Claude rerank of top-20 → top-k behind flag `RERANK=1`", requires the delta be
   measured "in recall@8 and MRR on the probe set", and requires both `RERANK=0`
   and `RERANK=1` runs be recorded. "Out of scope" excludes reranking *"unless it
   earns the measured clause"* — and **"earns" is nowhere defined in SPEC/02**.
   So the pre-registration is narrower than an earlier draft of this ruling
   claimed: it fixes what to measure and that the default is off, not what result
   adopts. Writing that bar after the numbers arrive would be curve-fitting by the
   test above, so **it must go into SPEC/02 now, before the measurement runs**;
   Consequences records it as owed.
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

**The counter-argument, and why it loses.** The strongest case against deferring:
reranking is being reached for as the remedy to a criterion that just went red,
after the failure, by the seat that failed it. That is the same shape as relaxing
ground truth, implemented in code instead of JSON. SPEC/02's pre-registration
blunts this but grants less license than ground 1 originally claimed — what it
pre-registered is that *if* reranking is implemented its delta must be measured,
and "Out of scope" listing it means the default was **exclusion**. It did not
pre-register reranking as the remedy for a criterion-1 failure. Meanwhile the
deferral itself has a cost: it keeps M02 open on the strength of an experiment
nobody has run.

It loses on one distinction, and only that one. **A remedy that must pass a
pre-registered measurement to be adopted is not the same act as a relaxation that
takes effect by being written down.** Relaxing `retrieval_truth.json` would make
Tier B pass by redefining the target; reranking must actually retrieve
`2025-03118#0003` into the top-8, judged by the instrument SPEC/02 named before
the failure. If it does not, nothing is adopted and the question returns live.
That is why this deferral is conditional on the adoption bar reaching SPEC/02
first: without it, the objection stands and the deferral becomes exactly what the
objection says it is.

**What would make this deferral wrong.** If the `RERANK=1` runs do not clear the
adoption bar this ADR requires SPEC/02 to state, the clause is not earned,
reranking stays off per SPEC/02, and this question returns live as a straight
(a)-versus-(b) choice with one more piece of evidence and nothing lost but the
measurement. The bar must be stated as an executable condition — what command
produces the two scorecards, and what observable result adopts versus rejects —
and it must be strong enough that a single probe flipping does not clear it, since
"one probe traded for another" is the pattern this document cites (fact 2, and the
`minimum_should_match` rejection) as proof that nine probes cannot distinguish
ranking policies. A bar looser than the one used to discredit engineering's
earlier changes would be incoherent.

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

**Four SPEC/02 changes are owed, all in "Done when" or "Optional".** Criterion 3's
0.60 similarity floor is replaced by the anti-collapse floor of Ruling 2(iii);
the drift number stays as reported instrumentation; the in-filter carve-out is
**kept** and its definition changed to derive from the filter predicate rather
than from the probe's assertions; and the `RERANK` adoption bar Ruling 3 depends
on is added to "Optional" as an executable condition. Criterion 1 is untouched —
the ruling that mattered most left the spec text alone. Criterion 2 stays gating.

**Two implementation changes follow the spec diff, and do not accompany it**
(ROLES.md flow 3): `run_parity.py:117`'s in-filter approximation is replaced, and
its exit condition moves from the similarity floor to the anti-collapse floor.
Neither is authorised by this ADR.

**M02 does not close on this document.** Criterion 1 still fails on Tier B, and
Ruling 1 declined to move it. Three closure paths exist and they are **not
equivalent**:

1. The `RERANK` measurement clearing the adoption bar — no ground-truth change,
   and the only path whose instrument was pre-registered.
2. Ruling 3 returning live and resolving as (a), dropping BM25 — no ground-truth
   change, but it costs ADR-0001's hybrid claim and the tier-switch demo beat.
3. The SME seat accepting `#0005` — **this is a post-failure ground-truth change,
   the move CLAUDE.md routes to a stop, and it carries the highest evidentiary
   burden of the three, not the lowest.** It also reopens ADR-0008 Ruling 1's
   two-chunk holding (see Ruling 1's scope). Listing it first in an earlier draft
   understated it.

No path runs through relaxing criterion 1.

**Tier B needs re-measuring under any of those paths**, which costs a `make up`
cycle (≈$0.24/hr) and moves both scorecards to a new sha. `evals/retrieval_truth.json`
is untouched by this document; only path 3 would touch it, and that seat has not
ruled.

+ Criterion 3's inconsistency is settled on a basis derivable from the spec text
  alone, and criterion 1 — failing for a genuine retrieval reason — is left
  failing. That asymmetry is the point.
+ Ruling 3 is bounded by a named experiment, and the bar for that experiment is
  now owed to SPEC/02 *before* it runs rather than settled after.
− **Cross-tier protection is weaker after this ruling than before it.** The
  anti-collapse floor catches disjointness, not drift, and it currently passes on
  all nine probes (minimum shared slots = 3). Restoring real similarity gating
  requires a probe set large enough to calibrate a threshold, which is out of
  M02's scope.
− **Ruling 2 removes the only mechanical backing for two claims made elsewhere.**
  ADR-0001's Consequences promise "two retrieval code paths to keep at eval parity
  (enforced by CI matrix)", and its Decision calls the "live tier-switch … itself a
  demo moment". After this, nothing asserts that switching tiers mid-demo yields
  comparable output. SPEC/02:6 already promises re-verification at M04; SPEC/04's
  "Done when" is where that claim needs a home, and it does not have one yet.
− These rulings were drafted by the seat they judge (see "How these rulings were
  produced"). `pm-spec-reviewer` is the only independent check applied — and its
  first pass returned REQUEST CHANGES with four blockers, including a factually
  false leg of Ruling 2 that this document had asserted twice and that its own
  cited evidence refuted. That is the strongest available argument for not
  trusting a ruling because it reads carefully.

## Evidence

- `evals/history/e596166-retrieval-s3vectors.json` — Tier A, 9/9, recall 1.000
- `evals/history/e596166-retrieval-aoss.json` — Tier B, 7/9, recall 0.833
- Both committed in `8b01fc9`; parity output reproduced by `make retrieval-parity`
- Weight and cap sweeps: `milestones/M02/README.md`, sections "The obvious lever
  does not work, and the sweep is why" and "The number this milestone is least
  sure of"; full cap sweep recorded in `src/shared/config.py:27` beside the value.
  **Both carry a stale Tier A row — see the caveat under fact 2.**
- The in-filter tautology (fact 4) and the aggregation sweep (Ruling 2) are both
  derived from the two scorecards above plus `evals/retrieval_truth.json` and
  `evals/run_parity.py:117`. Neither required a new measurement, and both are
  reproducible without AWS access — which is why they could correct this document
  after the hot tier was already destroyed.
- A reader who doubts any number above should re-derive it from the two
  scorecards, or re-run `make retrieval-parity` at `e596166`, rather than trust
  this document. The first version of it asserted a falsified finding twice.
