# M02 — Knowledge base: two retrieval tiers, one contract

- Branch: `m02-knowledge-base`   Tag: _(pending)_   PR: _(pending)_
- Commits: `f7ca738` (probe set) · `dc3748a` (ADR-0005 SME-seat extension) ·
  `ebf8a7e` (both tiers, harness, parity gate) · `7d65a07` (index `kind`;
  the structural lane becomes a query) · `11489e5` (AOSS index-visibility
  propagation)
- Spec: SPEC/02 (amended, 4 deviations)   ADRs: **ADR-0008**, **ADR-0009** (new)
- Status: **All gating criteria pass at `b16f596`.** Both tiers 9/9, recall
  1.000, and `make retrieval-parity` holds. Getting there took three PM-seat
  rulings (ADR-0009) and two rejected remedies, both rejected against
  pre-registered bars: reranking was measured and did not clear SPEC/02's
  adoption bar, and Tier B's lexical lane was retired under Ruling 3(a) because
  hybrid measured **worse** than vector-only (7/9 against 9/9). Consequence
  worth reading before the table: the two tiers now run the same algorithm, so
  **criterion 3 passes but means much less than it did** — see the caveat under
  the table.
  > **Earlier status, superseded:** "Tier A meets criterion 1; Tier B does not,
  > and criterion 3's Jaccard floor fails on the tail divergence the criterion
  > itself calls legitimate." True when written, and it contradicted the table
  > below it for one commit after the confirming measurement landed — caught by
  > engineering review, not by a reader. Kept because the arc from there to here
  > is the substance of this milestone.

## Done-when status (SPEC/02)

| criterion | status |
|-----------|--------|
| 5. Date attribution, all 3 stores (gating preflight) | ✅ green against the live corpus |
| 1. Recall@8 = 1.0, **S3 Vectors** | ✅ **9/9 probes, recall 1.0** (`e596166-retrieval-s3vectors.json`) |
| 1. Recall@8 = 1.0, **AOSS** | ✅ **9/9, recall 1.0** with the lexical lane off (`b16f596-retrieval-aoss.json`). Hybrid measured 7/9 at the same sha (`-lex1`), both misses one chunk; RERANK reached 8/9 and broke Tier A, bar not cleared. ADR-0009 Ruling 3(a) and its confirming measurement — see "Ruling 3 resolved as (a)". |
| 2. Resolved-tier assertion | ✅ **both halves met.** Two cards at `e596166`, resolved tiers distinct (`s3vectors` / `aoss`), assertion held on both runs |
| 3. ~~Cross-tier Jaccard ≥ 0.60~~ → **anti-collapse floor** (ADR-0009 Ruling 2) | ✅ **holds on all nine at `b16f596`**, minimum margin **6**. ⚠️ **and it is now close to vacuous** — see the caveat below. Previously (hybrid): failed r01/r03 for the same reason criterion 1 did, minimum margin 2. The old 0.60 floor failed r01/r03/r04/r05 — *not* r06, which passed at exactly 0.60. |
| 4. MRR reported, not gating | ✅ **0.796 on both tiers, identical to the last digit**, recorded with `mrr_is_gating: false`. Hybrid was 0.648 on Tier B |
| B. Hydration count-parity fails the deploy | ✅ **real failed deploy captured** — `cdk deploy -c faultDrop=3` → `UPDATE_FAILED` on 982 vs 985, stack rolled back. Evidence: `faultdrop-deploy.md` + `faultdrop-deploy-events.json` |
| C. `/evals/` in CODEOWNERS | ✅ landed with ADR-0005 |
| Probe set floor (≥8 probes, ≥2 distractors) | ✅ 9 probes, 2 distractor probes, 4 filtered |

**Nothing here is a trap score.** Recall@8 and MRR are retrieval metrics.
SPEC/00b bars any trap score until the q03 tightening closes; it has not.

> ⚠️ **Criterion 3 passing is now weak evidence, and this is a cost of Ruling
> 3(a) that ADR-0009 did not anticipate.** With the lexical lane off, both tiers
> run the same algorithm over the same embeddings, so cross-tier agreement is
> close to tautological: minimum margin went 2 → **6**, eight of nine probes score
> Jaccard **1.00**, the minimum is 0.78, and Tier A and Tier B report MRR
> identical to the last digit. The 0.60 floor Ruling 2 removed as unmeetable would
> now pass with room to spare — which is *not* the floor being vindicated. It is
> the two tiers no longer being different enough for a cross-tier gate to measure
> anything. Criterion 3 was written to catch drift between a hybrid tier and a
> vector tier; (a) removed the drift by removing the difference.
>
> ADR-0009's Consequences already recorded that cross-tier protection would be
> weaker after Ruling 2. It is weaker again, for a second and different reason.
> **Whether criterion 3 still earns its place is a PM-seat question**, and it is
> owed alongside the other two SPEC items — a gate that passes 9/9 at margin 6 is
> testing that one algorithm agrees with itself.

## What the first live measurement found

Tier A scored **recall@8 = 0.50** on its first run — 4 of 9 probes. The five
misses were unanimous in a way that made the cause legible:

> Every missing chunk was the **DATES** or **amendatory-instructions**
> paragraph of a document the vector lane had already ranked **first**.

Ranks of the missing chunks in a top-50 vector query: 12, 23, 28, 46, and one
absent from 50 entirely. Those paragraphs are short formulaic legalese —
*"DATES: This order is effective January 15, 2027, except for amendatory
instruction 4, which is effective January 18, 2028"* — and they embed far from
a plain-English question, while six adjacent preamble paragraphs of the same
389-chunk rule embed close to almost anything about it. For this product they
are also the highest-value chunks in the corpus: they carry the dates and the
CFR edits. A pure-vector tier systematically buries exactly what the product
exists to retrieve.

Four changes took it to 1.0. Each was made because of a measurement, and each
is a mechanism rather than a threshold:

1. **Structural expansion.** The `citations` GSI already files an FR
   document's DATES, summary and amdpar chunks under its bare citation
   (`90 FR 4628`), while preamble chunks carry a heading suffix. So the
   structural chunks of any document are one query away. This is the lexical
   lane Tier A was missing — Tier B gets the same effect from BM25 matching
   "effective" and "compliance date" as terms.
2. **The expansion is gated to documents already good enough for the page.**
   The first version expanded "the top 3 distinct documents", which in a
   24-long candidate list reaches rank 20. It lifted the **Red No. 3 order's
   DATES paragraph to rank 4 of a question entirely about the "healthy"
   rule** — a confident, correctly-cited answer about the wrong regulation.
   The gate is `k//3`, which is the page size by construction of the router.
3. **Per-document page cap**, so one rule cannot take six of eight slots.
4. **Deterministic tie-breaking**, so cross-tier Jaccard measures retrieval
   and not dict iteration order.

## Tier B did not meet criterion 1 — how that was resolved

> **Resolved at close.** Tier B now measures **9/9, recall 1.0** with the lexical
> lane off (`b16f596`), and `make retrieval-parity` holds. This section is the
> record of the failure and the reasoning it forced, kept in the past tense
> rather than deleted: the route from here to green is the substance of M02, and
> two of the three remedies considered were **rejected against pre-registered
> bars**. See "The RERANK bar was measured and not cleared" and "Ruling 3
> resolved as (a)" below.

**As first measured — Tier A: 9/9, recall 1.0, MRR 0.796. Tier B (hybrid): 7/9,
recall 0.833, MRR 0.648.** SPEC/02 requires 1.0 on both. It was not met, and this
milestone did not close on that measurement.

Tier B's first live measurement was **3/9** — and it missed the same DATES and
amendatory-instruction chunks Tier A had. That falsified the assumption behind
the original design: I had built the structural-expansion lane into Tier A
only, on the theory that Tier B's BM25 would find those paragraphs by term
match. It does not. A plain-English question's terms ("compliance", "date",
"effective", "rule") appear throughout a 389-chunk preamble, so a short DATES
paragraph does not win on BM25 either. Sharing the lane took Tier B to 6/9, and
indexing `kind` (below) took it to **7/9**.

### The two remaining failures are one chunk, and BM25 is why

r01 and r03 both miss `2025-03118#0003` — the paragraph carrying *"We note that
the compliance date remains unchanged at this time."* Nothing else fails, and
no `must_not_return` chunk leaks on either tier.

It is a **preamble** chunk, so the structural lane cannot reach it; it competes
on relevance alone. Measured directly against the live hot tier:

| probe | BM25 rank | kNN rank | fused | fused rank of `#0005` |
|---|---|---|---|---|
| r01 | **not in top 24** | 6 | 13 | 8 |
| r03 | 14 | 7 | 12 | 6 |

kNN — the same signal Tier A uses — ranks it 6th and 7th. Equal-weight RRF with
a BM25 lane that ranks it 14th or not at all is what loses it. `#0003` is the
longest preamble chunk in that document (2341 chars) and states the fact once;
`#0005` is shorter and repeats "compliance date" and "effective date" more, so
BM25's length normalisation prefers it. `RETRIEVAL_PER_DOC_CAP = 3` then binds:
`2025-03118` fills its three slots with `#0001`, `#0005`, `#0000`, and `#0003`
is fourth in line.

### The obvious lever does not work, and the sweep is why

Down-weighting the BM25 lane is the intuitive fix. Swept against the live tier:

| BM25 lane weight | 1.0 | 0.5 | 0.3 | 0.25 | 0.1 | **0.05** | 0.0 |
|---|---|---|---|---|---|---|---|
| probes passed | 7/9 | 7/9 | 7/9 | 8/9 | 8/9 | **9/9** | 9/9 |

r03 flips between 0.3 and 0.25. **r01 only flips between 0.1 and 0.05** —
because BM25 never returns `#0003` at all, so no weight can promote it; the
weight only has to shrink until BM25's boost to `#0005` stops mattering. At
0.05 the tier scores recall 1.000 and MRR 0.796: *numerically identical to Tier
A*, because the lexical lane is no longer affecting the outcome.

So the only weight that satisfies criterion 1 is one that deletes BM25. That is
not a tuning result, it is a measurement of what hybrid fusion can do here, and
adopting 0.05 would mean shipping a "hybrid" tier whose lexical half is
decorative.

Raising the per-document cap does not work either, and is non-monotonic on this
tier the same way it is on Tier A: **3 → 7/9, 4 → 8/9, 5 → 7/9, 6 → 7/9,
8 → 7/9.** No value reaches 9/9.

### The open decision, which is not engineering's

Two seats own the remaining options, and neither ruling belongs in a commit I
write after seeing the failure:

- **SME seat — is the truth set under-specified?** `2025-03118#0005`, which
  Tier B returns in `#0003`'s place, says *"the compliance date, and not the
  effective date, controls when parties must comply with this rule, and the
  compliance date in the final rule is not until 2028."* That is a sourced
  answer to "did the compliance date change?", arguably as good as `#0003`'s.
  If it is acceptable, both probes pass on both tiers with no code change. But
  this is a ground-truth relaxation proposed *because* a tier failed, which is
  exactly the move CLAUDE.md routes to a stop.
- **PM/spec seat — is criterion 1 the right requirement?** SPEC/02 already
  concedes that "BM25 hybrid and vector+GSI fusion legitimately differ in the
  tail" and then requires criterion 1 to "hold identically". The measurement
  says a hybrid tier cannot hold it identically on this corpus while remaining
  hybrid. That is a finding about the criterion, not about the implementation.

  > **Overturned by ADR-0009 Ruling 1.** Criterion 1 never required the tiers to
  > agree — it requires each tier *independently* to place every expected chunk in
  > its own top-8, and criterion 3's "criterion 1 is what must hold identically"
  > means that recall *outcome* holds on both. So this is a finding about the
  > *implementation* after all: Tier B has a genuine retrieval deficiency, and
  > criterion 1 stands unamended. The "hold identically" gloss above is what
  > caused the confusion. Criterion 3's floor *was* mis-specified — see Ruling 2 —
  > which is a separate matter from criterion 1.

Recorded unresolved at the time. ADR-0009 carries the rulings; the failing
scorecard is still the evidence.

### The RERANK bar was measured and not cleared

ADR-0009 Ruling 3 deferred the non-hybrid question to one bounded experiment, and
SPEC/02's "Optional" section fixed the adoption bar as four executable conditions
**before the run**, precisely so the result could not be argued about afterwards.
It ran. Four cards at `9e47ce7`, committed in `ae18a42`:

| | Tier A lane n/a | Tier B hybrid |
|---|---|---|
| RERANK=0 | **9/9**, recall 1.000, MRR 0.796 | 7/9, recall 0.833, MRR 0.648 |
| RERANK=1 | 8/9, recall 0.944, MRR 0.926 | 8/9, recall 0.944, MRR 0.889 |

Conditions **1, 2 and 3 fail**; **4 holds**. Reproduce with
`make retrieval-parity ARGS="--sha 9e47ce7 --rerank 1"`.

**The reranker did the job it was built for, and that is what makes this a
measurement rather than a write-off.** `2025-03118#0003` — the chunk both failing
probes turn on — was recovered on r01 *and* r03, inside the top-20 window SPEC/02
argued in advance it would be reachable in (fused rank 13 and 12). Tier B went
7/9 → 8/9 and its MRR moved 0.648 → 0.889.

It paid with `2024-29957#0000` on r01, on **both** tiers. The mechanism is visible
in the pages: reranking put `#0301`, `#0300` and `#0303` above `#0000` — three
chunks of one document — saturating `RETRIEVAL_PER_DOC_CAP = 3` with the page
already full, so nothing back-filled. **Whether a cap of 4 recovers it is not
derivable from these cards**; the pre-diversification ordering is not recorded.
Left as a measurement rather than promoted to an inference, which is the mistake
the stale cap row in this pack already made once.

Net, **Tier A went 9/9 → 8/9**: enabling the flag breaks the tier that passes.
That is the third "one probe traded for another" in M02, after the
`minimum_should_match` rejection and the two reverted ranking changes in the table
above — and condition 1 was written before the numbers arrived in order to refuse
exactly this. Applying it against the reranker this milestone itself wrote is the
only thing that made writing it first mean anything.

The flag stays, defaulted off, with its measurement recorded. Deleting the code
would leave an unfalsifiable claim about an experiment.

### Ruling 3 resolved as (a): Tier B drops the lexical lane

With path 1 closed, ADR-0009 Ruling 3 came back live and resolved as **(a)**,
reversible on a named condition. `config.RETRIEVAL_LEXICAL_LANE` defaults to
**off**: Tier B no longer issues a BM25 query, and its relevance lane is the raw
kNN list — the same shape as Tier A's, because that is the honest content of (a).
The query is not issued rather than issued-and-down-weighted, since a lane
weighted to nothing is cost with no effect on the page.

**What Tier B claims now.** Latency and concurrent load, not better relevance.
That claim is *also* currently unmeasured — nothing in SPEC/02 or SPEC/04 asserts
it — so retiring the hybrid claim in favour of it without a criterion would be the
same defect wearing new clothes. Recorded as owed to the PM seat.

**The reversal condition, in one sentence:** author a probe the lexical lane wins
— an `expected_chunk_ids` member BM25 places in the top-8 and the vector lane does
not — and the default flips back. Nine probes can witness a counterexample; they
cannot establish that BM25 never helps, and the ruling claims only the former.
This is the weakest part of (a) and it is written into `config.py` beside the flag
rather than left in a document nobody reads at the point of change.

### Why I stopped instead of closing the gap

Three further changes were tried. Each is defensible on its own terms and each
was measured:

| change | rationale | result |
|---|---|---|
| Three flat lanes instead of `[pre-fused relevance, assist]` | pre-fusing halves each relevance signal while the recall lane stays whole | **6/9 → 4/9**, reverted |
| Interleave the assist lane by chunk position | a DATES paragraph outranks another document's summary — the domain says so | **Tier A 9/9 → 8/9**, reverted; on both tiers it merely swapped r05 for r09 |
| BM25 `minimum_should_match: 70%` | BM25 over a verbose question in regulatory prose is noise; require most terms | Tier B **6/9 → 8/9**, *not adopted* |

The third is the interesting one, because it scores best and I rejected it. At
70%, BM25 stops matching **short** chunks — r09's amendatory-instructions
paragraph contains neither "Red", "No. 3", nor "sections", so it drops out of
the BM25 lane entirely. The setting improves the aggregate by suppressing
preamble noise while penalising exactly the short structural chunks this whole
mechanism exists to surface. Adopting a configuration whose mechanism runs
backwards to its purpose, because the number is higher, is fitting. So: not
adopted, and recorded here with its score so the choice is auditable rather
than invisible.

Two of the three changes traded one probe for another. That is the signal that
nine probes cannot distinguish these ranking policies, and continuing to change
policy until the number is green would produce a 1.0 that certifies nothing.
SPEC/02 anticipated this exact hazard for a probe set engineering authored,
chose `k` for, and needs 100% on.

### The real fix was to stop reconstructing structure and index it (`7d65a07`)

**The chunk `kind` was in the corpus all along.** The chunker has emitted
`kind` ∈ {dates, summary, amdpar, preamble, regtext} since M01 and it is in
every line of `corpus/chunks/**/*.jsonl` — `reindex._document()` did not copy
it into the AOSS document, and `processor._put_vectors` did not copy it into S3
Vectors metadata. So retrieval reconstructed "which paragraphs state what this
document does" out of a DynamoDB citations GSI.

With it indexed, the structural lane is a **query** rather than a
reconstruction: S3 Vectors runs a `$in` metadata filter, AOSS a `terms` clause
on a kNN, both ranking the same population by the same signal. That deleted the
top-N-distinct-documents heuristic, its window bound, its per-document chunk
cap, and the grouped-vs-interleaved ordering question that had measurably
traded r05 for r09 — roughly 80 lines, and every free parameter attached to
them.

| | before | after |
|---|---|---|
| Tier A | 6/9, recall 0.722, MRR 0.462 | **9/9, recall 1.000, MRR 0.796** |
| Tier B | 3/9 → 6/9 | **7/9, recall 0.833, MRR 0.648** |

Scoping took two attempts and the first was wrong. Searching structural chunks
corpus-wide ranks all 31 DATES paragraphs against each other and returns the
most query-similar ones **from rules the query never mentioned** — Tier A went
9/9 → 8/9, losing r03, whose answer is a preamble sentence crowded off the page
by other rules' deadlines. Scoping the lane to the FR documents already on the
relevance lane's page fixed it, with no tuned document count: `fr_doc_number`
identifies them completely, because structural chunks are FR-only (`dates` and
`amdpar` come from parsing a Federal Register document; an eCFR snapshot
produces `regtext`).

Tier A needed the same field in S3 Vectors metadata, which required a "rebuild
S3 Vectors from the corpus bucket" utility (`src/retrieval/rebuild_s3v.py`) —
reusing the stored embeddings, no Bedrock calls, no chunk-id changes. That was
owed anyway: the architecture rule says search indexes are pure functions of
the corpus bucket, and before this only AOSS had a rebuild path.

## Criterion 3 fails, and the carve-out is a tautology rather than a mistake

With both cards recorded at `e596166`, `make retrieval-parity` ran — the
cross-run gate that neither tier invocation can evaluate from inside itself.
**Criterion 2 passes on both halves.** Criterion 3 does not:

| probe | Jaccard | filtered | note |
|---|---|---|---|
| r01 | **0.33** | | 4 of 8 slots shared |
| r02 | 1.00 | ✔ | in-filter set only |
| r03 | **0.45** | | |
| r04 | **0.45** | | |
| r05 | **0.45** | | |
| r06 | 0.60 | | passes *exactly* at the floor — no slack |
| r07 | 1.00 | ✔ | in-filter set only |
| r08 | 1.00 | ✔ | in-filter set only |
| r09 | 1.00 | ✔ | in-filter set only |

Minimum 0.33 against a floor of 0.60. Two observations, both of which are
findings about the criterion rather than about the tiers:

**The carve-out's premise was confirmed; its implementation measures nothing.**
SPEC/02 computes Jaccard over the in-filter result set only, and says why: "a
filtered probe returns few in-filter hits and a long arbitrary tail … so one
filter probe could drag the per-probe minimum under 0.60 and fail M02 for a
reason unrelated to correctness."

> **Correction.** This section originally read those four 1.00s as evidence the
> carve-out "aimed at the wrong probes" — right instinct, wrong target. That was
> wrong on both halves, and `pm-spec-reviewer` caught it while reviewing
> ADR-0009. `evals/run_parity.py:117` approximates the in-filter set as
> `expected ∪ must_not_return`; r07, r08 and r09 each carry one expected chunk and
> no forbidden ones, so the scope is a **single chunk id** and Jaccard is 1/1 *by
> construction*. The 1.00s are the carve-out's own output, not a measurement of
> tail agreement.
>
> Computing full top-8 on the same two cards inverts the reading: r02 0.78,
> **r07 0.23**, r08 0.78, r09 0.60. r07 would be the new gating minimum, *below*
> r01's 0.33, while both tiers return its one expected chunk — precisely the
> scenario SPEC/02 wrote the carve-out to prevent. So the carve-out's reasoning
> was sound while Jaccard gated; what is defective is the approximation standing
> in for it, which exempts a filtered probe from measurement whenever
> `must_not_return` is empty.
>
> **Where it ended up:** ADR-0009 Ruling 2(ii) **removes** the carve-out, because
> once the similarity number stops gating there is nothing left for it to protect.
> An intermediate draft kept it and redefined the in-filter set as "the chunks
> satisfying `Filters.matches`" — a no-op, since `router._finish` applies exactly
> that predicate before returning, so "in-filter" equals the full top-8 and the
> 0.23 comes straight back. Both errors are recorded because the second was
> introduced *while fixing* the first, which is the more useful warning.

**The floor permits two slots of divergence, not "a tail".** For two 8-element
sets, Jaccard = `c / (16 - c)`, so 0.60 requires `c = 6` — agreement on six of
eight slots. The same criterion concedes in prose that "BM25 hybrid and
vector+GSI fusion legitimately differ in the tail." Observed divergence is three
slots on r03/r04/r05. On **r04, r05 and r06 the divergence is entirely
non-expected tail** — the expected chunk is present on both tiers and those
probes pass criterion 1 on both — so the gate is failing on exactly the
difference the criterion says is legitimate. On r01 and r03 the differing member
includes `2025-03118#0003`, which is the known criterion-1 miss, not a separate
defect.

**No floor change is proposed here.** SPEC/02: the floor and the aggregation
"may not be changed to match whatever is observed — changing either is a spec
edit requiring PM approval." I have now observed it, which is the condition that
disqualifies engineering from arguing the number. Recorded as measured.

> **Where this went.** ADR-0009 carries the rulings. Criterion 1 **stands
> unamended** — it never required the tiers to agree, only each tier
> independently to reach recall 1.0, so Tier B's miss is a retrieval deficiency
> and not a criterion defect. Criterion 3's 0.60 similarity floor is **replaced**
> by an anti-collapse floor, after an aggregation sweep showed which probes fail
> changes almost completely with the window (r03 scores 1.00 at top-3 and 0.45 at
> top-8; r06 passes at top-8 and fails at top-4). The non-hybrid question was
> **deferred** pending the `RERANK` measurement SPEC/02 pre-registered, and is
> now **resolved as (a): Tier B drops the lexical lane**, off by default and
> reversible on a named condition. The measurement ran at `9e47ce7` and did not
> clear the bar — see "The RERANK bar was measured and not cleared" below.
>
> Two claims in this section did not survive that ruling. "Criterion 1's
> 'identically on both tiers'" misreads the criterion — see ADR-0009 Ruling 1.
> And the gate did **not** fire on r06: it scored 0.60 and passed at the floor
> with zero slack. Of the four probes that did fire, two (r01, r03) tracked the
> genuine `2025-03118#0003` miss, so the gate ran at roughly 50% precision —
> weak, not empty.

## The number this milestone is least sure of

`RETRIEVAL_PER_DOC_CAP`. Swept against the probe set:

| cap | 3 | 4 | 5 | 6 | 8 |
|-----|---|---|---|---|---|
| Tier A probes passed | 9/9 | **8/9** | 9/9 | 7/9 | 7/9 |
| Tier B probes passed | 7/9 | **8/9** | 7/9 | 7/9 | 7/9 |

**It is not monotonic on the live Tier B row.** A value that fails between two
passing values means nine probes cannot determine this constant.

> **Correction (ADR-0009 fact 2).** This originally read "not monotonic, on
> either tier, and the two tiers disagree about which values pass." The
> disagreement claim is withdrawn: the Tier A row predates `7d65a07`, which
> deleted the top-N-distinct-documents heuristic, its window bound, its
> per-document chunk cap and the grouped-vs-interleaved ordering question — so it
> describes a retrieval path that no longer exists and cannot be compared against
> a live Tier B row. Non-monotonicity on Tier B alone (3→7/9, 4→8/9, 5→7/9) is
> what the argument needs and it survives. Re-sweeping Tier A costs nothing and
> would settle it. Removing the mechanism entirely costs two
probes, so the mechanism is load-bearing and demonstrable; the exact bound is a
judgement. The full sweep is recorded in `shared/config.py` next to the value.
First thing to re-examine if a probe regresses.

(The Tier A row was measured before `7d65a07` and has not been re-swept; the
Tier B row was measured against the live hot tier at `11489e5`. Re-sweeping
Tier A costs nothing but has no bearing on the open decision, which is about
Tier B.)

SPEC/02 said it plainly and it is worth repeating against this result: a probe
set that engineering authored, selected `k` for, and needs 100% on is
self-certifying. The mitigations are real but partial — two distractor probes,
`must_not_return` assertions, and ADR-0008 recording the two rulings with
primary sources. A reader should treat "recall@8 = 1.0" as "the nine things we
thought to check, pass", not as a retrieval quality claim.

## Defects found by running it (not by reading it)

| what | how it would have failed |
|------|--------------------------|
| **S3 Vectors rejects `$gte`/`$lte` on string metadata** | The date-range pushdown returned `ValidationException: Invalid filter`. Reproducible via `tests/probe_s3v_filter.py`; `$eq`, `$and`, `$exists` all work on the same field. Now only `$exists` is pushed — which *is* ADR-0006's rule — and the bounds apply client-side. |
| **META stores `compliance_dates` as a JSON string** | The preflight read the raw attribute, and `"[]"` is **truthy**. The check would have reported a failure on exactly the value ADR-0006 requires. Reads naturally, passes review, wrong. |
| **The first scorecard was filed under the previous commit's sha** | `git_sha()` reports HEAD whether or not the tree matches it. Evidence labelled with a commit that cannot reproduce it is worse than no evidence — it survives into `milestones/` and reads as verified. `--record` now refuses a dirty tree. |
| **The AOSS data-access policy locked out the operator** | Access is granted *only* by that policy; `aoss:APIAccessAll` alone still 403s. It named the two Lambda roles, and the harness runs **in-process** by design — as the operator's principal. The AOSS half of criterion 1 was not executable by the person the spec asks to execute it. Now an opt-in `devPrincipalArn`, empty by default, pinned by 4 tests. |
| **The harness crashed while printing a PASSING result** | Windows console is cp1252 and cannot encode ✅. A green run exiting non-zero from the reporting layer. |
| **`make up` failed: `PUT chunks -> 403`** | **aoss requires an `x-amz-content-sha256` header, and botocore's generic `SigV4Auth` never emits it** — only `S3SigV4Auth` does. So the signature was correct and the request was rejected anyway. See below: I got the diagnosis wrong first. |
| **The Trigger's invoke timeout is 2 minutes, not the function's 15** | Found while sizing the retry for that 403. `Timeout: "120000"` on the custom resource, separate from the Lambda's own 900s. Hydration legitimately needs longer — AOSS exposes no refresh API, so count-parity polls up to 5 minutes. A healthy deploy would have failed on the invoker's clock and reported it as a hydration failure. Latent before M02; it would have fired on the first full hydration regardless. |
| **`make up` failed: `POST chunks/_count -> 404 index_not_found`** | AOSS decouples ingest compute from search compute and index metadata reaches them separately, so `_bulk` was **accepted** against `chunks` while `chunks/_count` had never heard of it — 11s into a fresh collection. `_await_count` already waited out a low count for exactly this reason and treated a 404 as fatal. `_count` now returns `None` (not `0` — they are different claims) and the poll waits it out, with the same safety property as the 403 retry: it can only delay a failure, never convert one into a success. The next deploy saw the index in 0.2s, so the window is intermittent — and that same run took **62 seconds** for the count to settle, which is what makes the polling load-bearing rather than defensive. |
| **Tolerating that 404 opened a hole, so it is closed in the same commit** | If a create ever silently no-ops, `_bulk` auto-creates `chunks` with a **dynamic mapping**: every document lands, the count assertion passes, and `embedding` is a float array instead of a `knn_vector`. That deploy reports success and every kNN query fails afterwards — the same looks-healthy failure the count check exists for. `_assert_knn_mapping` checks the field type, failing only on a *positive* observation so an unverified guess about the AOSS response shape cannot fail a healthy deploy at the end of a full hydration. (The shape is now verified: the first successful run did not log `knn_mapping_unverified`.) |

### The 403, and the wrong diagnosis I shipped first

Worth writing down in full, because the mistake is the same shape as the one
ADR-0005 already records: a plausible mechanism, asserted before anything had
been run that could distinguish it from the alternatives.

`make up` failed with `PUT chunks -> 403` and an OpenSearch-shaped body. I
reasoned that the `DELETE` had returned 404 while only the `PUT` was denied,
concluded that a blanket authorization failure was therefore ruled out, and
shipped a **bounded retry for data-access-policy propagation**. The reasoning
was sound and the conclusion was wrong: DELETE on a nonexistent index is
answered before the body-bearing path that actually needs the header.

The second deploy failed identically — but the retry's diagnostic made it
decisive in one read instead of another guess:

```
attempts=37   (183 seconds)
caller=arn:aws:sts::…:assumed-role/regdelta-search-ReindexFnServiceRole…/…
```

37 attempts over three minutes is not eventual consistency. CloudTrail's
`CreateAccessPolicy` event then showed the policy submitted 55 seconds before
the Lambda started, naming that exact role, with `aoss:*` on
`index/regdelta/*`. Policy right, principal right, timing right.

That left the signer. **aoss requires `x-amz-content-sha256`, and botocore's
generic `SigV4Auth` folds the payload hash into the canonical request but
never emits it as a header** — only `S3SigV4Auth` does. It is precisely what
`opensearch-py`'s `AWSV4SignerAuth` special-cases for the `aoss` service, and
the cost of not using that library (see "no new dependencies" below). aoss
reports the omission as a bare `403 Forbidden`, identical to an authorization
denial.

Three things kept from this:

- The header is now set **before** signing, so it is covered by
  `SignedHeaders`, and a test mutation-checks it — removing the header fails
  the test.
- The failure message no longer asserts a cause. It lists all three (missing
  header / principal absent / propagation), says which the retry has already
  ruled out, and points at the CloudTrail event that settles the second.
- **The retry stays**, even though propagation was not the cause here. It is
  bounded, it cannot mask a permissions bug, and its attempt counter is what
  converted the second failure from a guess into a measurement.

`run_evals.py` has the same latent cp1252 and dirty-sha issues. Not fixed
here — it is the golden-set instrument and out of M02's scope — but recorded
so it is a decision rather than an oversight.

## Deviations from SPEC/02 (amended in the spec, same PR)

1. **The reindex handler moved** to `src/retrieval/reindex.py`; the Lambda
   ships `../src` like every core function. Its own asset directory meant a
   second copy of the index mapping and the SigV4 client. This repo has had
   that bug: `_EDGE_PREDICATE` was two hand-synced copies at M01c and they
   drifted.
2. **"Single hybrid query … client-side RRF"** is served by one `_msearch`.
   One query yields one ranked list; RRF needs two. One `_msearch` is a single
   round trip carrying both.

Also: **no new dependencies.** `opensearch-py` + `requests-aws4auth` (what the
reindex TODO named) would need a layer or a bundling step for two things
botocore already does. `src/retrieval/aoss_client.py` is ~60 lines instead.

## Remaining to close M02

1. ~~**One PM-seat ruling covering criterion 1 and criterion 3.**~~ **Done —
   ADR-0009**, with the SPEC/02 diff it licenses. Criterion 1 stands unamended;
   criterion 3's similarity floor is replaced by an anti-collapse floor; the
   non-hybrid question was deferred pending the RERANK bar and is now resolved.
   Two `pm-spec-reviewer` passes were needed — the first caught a falsified
   finding this pack had asserted, the second caught a replacement gate whose
   stated wording contradicted the ADR's claim about it. **ADR-0009 named three
   closure paths, and they were not equivalent:**

   1. **The RERANK measurement clearing the adoption bar** (SPEC/02 "Optional",
      four conditions written before the run) — no ground-truth change, and the
      only path whose instrument was pre-registered. **CLOSED: measured at
      `9e47ce7`, conditions 1, 2 and 3 failed.** Cost one `make up` cycle, not
      two — Tier A needs no hot tier, so three of the four cards came from one
      window.
   2. **Dropping BM25** — no ground-truth change, but it costs ADR-0001's hybrid
      claim and the tier-switch demo beat, and reaches a lead-owned ADR. **This
      is the path taken**, conditional on a lane-off Tier B actually measuring
      9/9: the sweep behind it tested BM25 at weight 0.05, and weighting a lane
      to almost nothing is not the same code path as not issuing its query.
   3. **The SME seat accepting `2025-03118#0005`** — a post-failure ground-truth
      change, the move CLAUDE.md routes to a stop, carrying the **highest**
      evidentiary burden of the three rather than the lowest. It also reopens
      ADR-0008 Ruling 1's two-chunk holding, not just r01's expected set. **Still
      unexercised; Ruling 3's resolution does not license it.**

   No path runs through relaxing criterion 1.

   > **What remains before M02 can be tagged.** One `make up` cycle recording
   > Tier B lane-off (the new default), Tier B lane-on (reproducing 7/9 at the
   > same sha), and Tier A (hot tier down, unaffected by the flag — it has no
   > lexical lane). M02 closes only if lane-off Tier B reads **9/9** and
   > `make retrieval-parity` passes on the new pair. If it reads below 9/9,
   > Ruling 3 returns live and (a) has bought nothing.
2. ~~**Criteria 2 and 3.**~~ **Done — both measured at `e596166`.** The pair was
   recorded across a `make down` (the router picks its tier from the presence of
   `/regdelta/search/endpoint`, with deliberately no override, so the two cards
   cannot exist at one sha any other way):

   ```bash
   make down               # stops OCU billing; the SSM param goes with it
   make retrieval-evals    # recorded e596166-retrieval-s3vectors.json
   make retrieval-parity   # criteria 2 and 3 — the cross-run gate
   ```

   HEAD did not move between the two runs; `--record`'s dirty-tree guard
   excludes `evals/history/` for exactly this workflow, and that is what made it
   possible. **Criterion 2 passes.** Criterion 3's 0.60 floor failed at 0.33 and
   has since been replaced (item 1); the amended criterion fails on r01/r03 with
   criterion 1.
3. **(B): a deliberate partial-index deploy** with `-c faultDrop=3`, capturing
   the failed CloudFormation event here. The hook can only ever *cause* a failing
   deploy — no switch in `reindex.py` relaxes the count assertion, and a test
   asserts that by reading the source.

   > **Run it, then `make down`, before anything queries the tier.** The
   > one-directional guarantee is scoped to CloudFormation, not to the
   > collection. On a stack *update* — which is what this is against an already-up
   > tier — rollback reverts the Lambda's environment but **not AOSS index
   > contents**, and `/regdelta/search/endpoint` from the earlier successful
   > deploy survives. `router.active_endpoint()` reads only that parameter, so
   > retrieval would route to a knowingly-short index and answer with citations,
   > and neither the resolved-tier assertion nor the date-attribution preflight
   > looks at index completeness — a scorecard could be recorded against it.
   > Found by `security-reviewer` (M2). The residue is not specific to the fault
   > hook: any Trigger failure on an update leaves it. Nothing in the retrieval
   > path checks hydration health, because the SSM parameter is written by the
   > stack rather than by a successful hydration — worth fixing properly at
   > SPEC/05, out of scope here.
4. ~~**The remaining role gates.**~~ **`security-reviewer` and
   `eng-code-reviewer` have both run**; `pm-spec-reviewer` ran twice on ADR-0009
   and the SPEC/02 diff. Verdicts: security — nothing blocks merge, 3 medium /
   4 low; engineering — two blockers, both fixed (see "What the role gates
   found"). All owe a re-run only if the code or spec changes again.
5. **Two implementation changes the SPEC/02 diff now requires**, which per
   ROLES.md flow 3 follow PM approval rather than accompanying it:
   `run_parity.py`'s in-filter approximation is deleted with the carve-out, and
   its exit condition moves from the similarity floor to the anti-collapse floor,
   emitting the per-probe margin. Neither is authorised by ADR-0009.
6. **One change owed to SPEC/04:** answer-level cross-tier comparability. SPEC/04
   already homes ADR-0001's "eval parity" claim, but nothing anywhere asserts that
   switching tiers mid-demo yields *comparable answers*, which is what the demo
   beat sells.

## What the role gates found

`security-reviewer`: **nothing blocks merge.** The two highest-risk items held up
under reading rather than assumption — the hand-rolled SigV4 path (payload hash
set before signing so it lands in `SignedHeaders`, no query strings anywhere, every
URL path a module constant with no corpus-derived interpolation, credentials never
in a log or exception) and `reindex.py`'s "can only delay a failure, never convert
one into a success" claim. Three mediums and four lows, all fixed below.

`eng-code-reviewer`: **two blockers, both fixed.** Also flagged, correctly, that
**the Done-when does not currently pass** — the only recorded pair is `e596166`
and it exits 1.

### The blocker worth remembering

**The gate could be turned green by editing ground truth alone.** `run_parity.py`
re-derived `expected` from `retrieval_truth.json` at gate time and compared it to
`returned` lists recorded earlier, with nothing tying the two together. Measured
against the real cards — drop `2025-03118#0003` from r01/r03's expected sets, touch
no scorecard:

```
minimum margin 2 (floor 1) over 9 probes
s3vectors: 9/9 probes ... aoss: 7/9 probes, recall@8=0.833 (reported, not gating)
✅ parity holds        rc = 0
```

No re-run, no sha change, no dirty flag — and `7/9` printed one line above the
green verdict. CLAUDE.md routes editing golden data to make a failure pass to a
stop; a gate that cannot see the edit is not enforcing that. Three further holes
in the same class: zero probes returned ✅, a card probe absent from truth was
silently downgraded to pure-negative (making clause (i) vacuous), and `passed`
vs `total` was never gated — so a `must_not_return` leak could fail criterion 1
while the pair gate reported parity, since clause (i) only looks at
`expected_chunk_ids`.

Closed by four checks in `main()`: the cards and truth must agree on the probe
set, the set must be non-empty, each card's `corpus_snapshot` must equal truth's
(`run_retrieval.py` copies it at record time, so a mismatch means truth changed
after recording), and `passed != total` fails the pair. Three tests cover them.

### The other blocker, found independently by both gates

`aoss_client.request` converted only `urllib.error.HTTPError`. `URLError`
(DNS/NXDOMAIN, connection refused/reset), `TimeoutError` and a non-JSON 200
escaped unwrapped, and `router.retrieve_traced` catches `AossError` and nothing
else — so "a deployed-but-broken hot tier must not take the API down" did not
cover **unreachable**, which is the live state between `make down` deleting the
collection and the 60s endpoint cache expiring. SPEC/02's contract says "present +
*reachable*". Both reviews landed on it separately. `AossError` is now the tier's
entire failure contract, with the four modes tested.

### Fixed, non-blocking

- **Tier B did not push `kind` into the engine.** `_filter_clauses` hand-listed
  four keyword fields; `kind` joined `KEYWORD_FIELDS` later and the list never
  caught up, while Tier A iterates the shared lists. `Filters(kind=…)` meant Tier
  A filled its 24 candidate slots with matching chunks and Tier B filled them with
  anything, `router._finish` then discarding nearly all — a short page on one tier
  and a full one on the other, exactly the silent divergence this design exists to
  prevent. No probe filters on `kind`, so no recorded scorecard changes.
- `devPrincipalArn` took an unvalidated string into a policy granting `aoss:*` on a
  collection with `AllowFromPublic: True`; a mistyped account id was corpus data
  leaving the account. Now shape- and account-checked, with the SSO assumed-role
  form rejected explicitly and named — it is what `make up` passes and AOSS does
  not match on it. Six new synth tests, including the env-var widening path, which
  every prior test deleted before asserting.
- `faultDrop` accepted 0 and negatives, producing a *passing* deploy while the
  operator believed the fault fired.
- `Code.from_asset(SRC)` shipped `src/` with no exclusions.
- Exit code 3 now distinguishes "the harness crashed, nothing was measured" from
  exit 1's "a criterion failed" — a caller could not tell them apart, and only one
  is evidence.
- A dead `_client("registry")` branch in `s3vectors_tier`.
- Test quality: an `assert "0.14" in out or "0.1" in out` that also passed on 0.10,
  0.17 and 0.19; a row comparison coupled to print-format column widths; and a
  source-reading floor guard that inspected only `main()`, so a threshold added in
  `jaccard()` would have slipped through.

## Deferred: four findings that change ranking, and why they are not in this PR

Each of these is real and none is fixed, because **every one alters what retrieval
returns and therefore invalidates both scorecards** — re-measuring costs a `make
up` cycle. Fixing them alongside a closure-path change is one cycle; fixing them
now is two. Recorded here so the deferral is a decision rather than an omission.

- **`RETRIEVAL_PER_DOC_CAP = 3` is the value the live measurement likes least.**
  The comment defends it with a Tier A row it also marks stale; the only live row
  is Tier B's 3 → 7/9, 4 → 8/9, 5 → 7/9. And both recorded failures are
  cap-boundary artifacts: `2025-03118` gets exactly 3 slots on both tiers, and
  Tier B spends them on `#0000/#0001/#0005` where Tier A spends them on
  `#0000/#0003/#0001`. So the AOSS miss is `fusion.diversify` hitting the cap while
  Tier B ranks `#0005` above `#0003` *within* that document — not a retrieval
  failure in the lanes. Falsifiable for the price of one hot-tier run.
  **Note this does not by itself close criterion 1**: cap 4 measured 8/9, not 9/9.
- **The tie-break is also a ranking rule, and it favours older documents.**
  `sorted(scores, key=lambda cid: (-scores[cid], cid))` breaks ties by chunk_id
  ascending, and chunk ids are year-prefixed FR doc numbers — so ties resolve
  toward *older* rules, backwards for a product whose question is "what changed".
  Not rare on Tier B: it fuses two equal-length lanes where most chunks appear in
  exactly one, so a BM25 rank-*r* singleton and a kNN rank-*r* singleton score
  identically and the alphabetical order decides. Tier B applies the tie-break
  twice (inner and outer fusion) where Tier A applies it once — an asymmetry the
  anti-collapse floor cannot see. `(-score, min_rank_across_lanes, chunk_id)`
  stays deterministic without the corpus-order bias.
- **`rebuild_s3v` is upsert-only, so it is not the counterpart it claims to be.**
  `reindex._create_index` earns the "indexes are pure functions of the corpus"
  rule by deleting and recreating, with the reason stated: "a leftover document
  from a previous corpus is a citation to text that is no longer in the corpus."
  `rebuild_s3v` only calls `put_vectors`; re-chunk a document into fewer chunks and
  the orphaned vectors stay queryable and citable. It also has no post-write count
  assertion, where `reindex` fails the deploy on one.
- **Lane assembly is written twice, in two dialects** — the thing `fusion.py`'s
  own docstring says is avoided. Only the native structural query genuinely differs
  between the tiers; the page derivation, lane order and weights are duplicated, so
  changing one tier's rule silently diverges the pages, and the shipped gate will
  not fire on it.

### And one contract note, for M03 rather than M02

CLAUDE.md: "Timeline questions (effective vs compliance dates, supersession) are
answered from the DynamoDB amendment graph, not vector similarity." **r01 and r03
are timeline questions**, and `src/retrieval/` reaches DynamoDB only for the
citations GSI — never the amendment graph. The structural lane is explicitly a
similarity device for surfacing DATES paragraphs, and the per-document cap is being
tuned to make similarity surface a delay notice's DATES paragraph that the graph
would return deterministically. Nothing here emits a claim, so no citation rule is
broken at M02. But the two probes Tier B cannot pass are exactly the two the rule
says should not be answered this way, and M03 is about to build the timeline node
on top of a retrieval path tuned to substitute for the graph.

## Open, carried forward

- **`golden-set` must return to required checks at M04**, as context
  `golden-set`, probed rather than assumed (ADR-0005).
- **ADR-0008 ruling 2 is deliberately narrow.** Excluding the § 74.1303 drugs
  regtext from a food query is right for a probe whose query names a frosting.
  A product-ambiguous asker makes 2028-01-18 relevant, and that is an
  applicability question for SPEC/03's verdict layer, not retrieval.
- **`_resolve_fr_citation` uses FR *term* search**, which cannot resolve a
  citation to its document (`2026-15671` is permanently DLQ'd on this).
  Recorded at M01c, still open, not M02's.

## Demo script for this stage

M02 has no API and no UI — those are SPEC/04. So this is a terminal demo, and
what it demonstrates is the **contract**, not an answer. Three steps, ~4 minutes,
about $0.02 of hot tier.

**1. The always-on tier answers, with nothing running.**

```bash
make status                 # → "Hot tier: DOWN → retrieval on S3 Vectors"
make retrieval-evals        # → 9/9 probes, recall@8=1.0, MRR=0.796
```

Idle cost of the thing that just answered: under $2/month. No cluster.

**2. Bring the hot tier up and ask the same nine questions.**

```bash
make up                     # ~3-4 min: collection, index, hydration
make retrieval-evals        # → "→ hot tier aoss" · 9/9, recall@8=1.0, MRR=0.796
```

Nothing in the command changed. The router picked the other backend from an SSM
parameter, and **the numbers are identical to the last digit** — 0.7962962962962963
both times.

**3. Prove it is the same answer, not just the same score.**

```bash
make retrieval-parity       # → ✅ parity holds · minimum margin 6
make down                   # → OCU billing stopped
```

Eight of the nine probes return **byte-identical top-8 chunk sets** across two
different search engines.

### What to say while it runs, and what not to

**Say:** the retrieval contract is one seam (`router.retrieve`), the tier is chosen
by infrastructure state rather than by the caller, and a deployed-but-broken hot
tier falls back to the always-on one rather than taking the API down — with the
reason carried out on the response, so a fallback can never be silently reported
as two-tier coverage. That last property is what SPEC/02 criterion 2 gates.

**Do not say "hybrid".** Tier B was specified as BM25+kNN hybrid. Measured, hybrid
scored 7/9 against vector-only's 9/9, so the lexical lane is off (ADR-0009 Ruling
3(a)). **Do not say "faster" either** — that is unmeasured, and the only proxy in
the repo has AOSS slower. Say "same algorithm, different infrastructure".

**The honest headline is better than the one it replaced:** *the answer does not
change when the infrastructure does.* That is the contract, it is demonstrable in
four minutes, and it is a stronger claim than a relevance story the scorecards
contradict.

### If you have another two minutes, show the failure

```bash
cdk deploy regdelta-search -c faultDrop=3   # → UPDATE_FAILED, stack rolls back
```

982 of 985 chunks indexed — 0.3% missing — and the deploy refuses. Every probe
would still have returned eight results with real citations; a smoke test would
pass. That is the point: see `faultdrop-deploy.md`.

## `make evals` is not applicable at M02, and that is pre-registered

`close-milestone` step 1 calls for the full golden set. It **cannot run here**:
`run_evals.py:124` resolves an API URL unconditionally, before subset filtering,
and the API is SPEC/04. Attempted at close: `No API URL. Use --api-url,
$REGDELTA_API_URL, or deploy regdelta-core.`

This is not a waiver written to get past a red gate. SPEC/02's "Why not the golden
set here" recorded it **before** any measurement, on two grounds: executing it at
M02 would invert the milestone order, and it is the wrong instrument — those
questions assert on answer prose, so a failure could not distinguish "the chunk
never came back" from "the model fumbled a chunk it had". The coverage is
**relocated, not dropped**: SPEC/04's "Done when" requires
`run_evals.py --subset retrieval` against the deployed API on both tiers, and
SPEC/02 states that its own deferral "is only honest if this clause holds".

**M02's evidence is the retrieval scorecards**, and the delta-vs-M00b that
`close-milestone` step 3 asks for is deliberately not computed: recall@8 is not
answer quality, every card carries `"comparable_to_baseline": false`, and SPEC/02's
"No trap score" rule bars it until the q03 tightening closes. A recall number
presented as a delta against the naive baseline would be the most flattering
available misreading of this milestone.

## What broke

> Two halves, kept separate on purpose. Everything down to "Operator notes" is
> **what the record can prove** — git history, scorecards, reviewer output.
> "Operator notes" is the operator's own account, collected by asking rather than
> inferred, per `close-milestone` step 3. The split matters because the two are
> not equally reliable: the first half is falsifiable from the repo, the second is
> testimony.

**Found by running it, not by reading it** (detail in "Defects found by running
it"): the AOSS 403 that was a data-access-policy gap rather than propagation
delay; `MSYS_NO_PATHCONV` — Git Bash rewriting `--name /regdelta/search/endpoint`
into a Windows path, so the tier probe returned ParameterNotFound while the hot
tier was **up**, and the harness then measured AOSS under the S3 Vectors label;
the first scorecard filed under the previous commit's sha, since `git_sha()`
reports HEAD whether or not the tree matches.

**Four ranking experiments that could not be adjudicated.** Three flat lanes 6/9 →
4/9. Interleaving the assist lane traded r05 for r09. `minimum_should_match: 70%`
scored *best* (6/9 → 8/9) and was **rejected** because its mechanism ran backwards
to its purpose — it suppresses preamble noise by killing the short structural
chunks the lane exists to surface. Then reranking recovered the target chunk and
broke Tier A. Two of four traded one probe for another, which is the signal that
**nine probes cannot distinguish ranking policies**.

**Defects in this milestone's own work, caught by the role gates and not by me.**
The parity gate could not load a `-lex1` card at all, so `make retrieval-parity`
silently gated the *default* pair and printed "parity holds" over a header that
never mentioned the lane — while the operator's most recent measurement sat unread
in `evals/history/`; and the `lexical_lane` check written to prevent exactly that
was **unreachable**. A branch claiming `rrf([knn])` differed from slicing, written
into three places including a test docstring that said it existed to rule out the
other implementation — the reviewer disproved it by mutating the line and watching
all 386 tests stay green. The `kind` pushdown, the drift this milestone existed to
close, had **no test**: skipping it in either tier left the suite green. SPEC/04's
answer-comparability criterion was **green by construction** via the response
cache — the same tautology class as ADR-0009 fact 4, reproduced in a criterion
written after that finding was recorded. A dev principal granted `aoss:*` —
DeleteIndex and WriteDocument — to run a read-only harness. And a latency claim
committed to `CLAUDE.md` as an architecture rule, with a "say that" instruction,
that no measurement supported and whose only available proxy contradicted.

**A ruling that was factually wrong twice.** ADR-0009's first draft asserted the
in-filter carve-out "protected the wrong probes"; `pm-spec-reviewer` refuted it
from the ADR's own cited evidence, and the proposed fix was itself a no-op because
`router._finish` already applies that predicate. Both corrections are marked inline
rather than edited away.

### Operator notes

The two that actually cost time at the keyboard. Mechanisms are documented above;
these are the operator-facing versions — what the terminal showed, what it looked
like it meant, and what to do differently next time.

**1. The AOSS 403 — three plausible wrong answers before the right one.**
`make up` failed with `PUT chunks -> 403` and an OpenSearch-shaped body, and the
signal pointed away from the cause at every step. The `DELETE` succeeding while the
`PUT` was denied looked like it ruled out a blanket authorization failure (it does
not — DELETE on a nonexistent index is answered before the body-bearing path that
needs the header). "403 on a freshly created data-access policy" reads as
eventual consistency, so the first fix shipped was a propagation retry. It took
CloudTrail plus a 37-attempt/183-second retry log to rule that out, and the actual
cause was the signer: aoss requires `x-amz-content-sha256`, which botocore's
generic `SigV4Auth` folds into the canonical request without emitting as a header.

*What to do differently:* on an AOSS 403, check the **signed headers** before the
policy and before timing. The policy and the principal are visible in CloudTrail in
under a minute; the header is not visible anywhere except by reading the signer. The
retry that was shipped first was not wasted — its diagnostic is what made the second
failure decisive — but it was built on a diagnosis nothing had yet distinguished
from the alternatives. That is the same shape as the mistake ADR-0005 records.

**2. A deliberate failure is indistinguishable from a real one at the terminal.**
`cdk deploy regdelta-search -c faultDrop=3` is *supposed* to fail — that failing
deploy is the evidence Done-when (B) requires. It still arrives as
`UPDATE_FAILED · Received response status [FAILED] from custom resource`, in the
middle of a CloudFormation rollback, indistinguishable from a broken deploy until
you read the message body. The first reaction was to treat it as something to fix.

*What to do differently:* say out loud which command is expected to fail before
running it, and check `git status` first. The scorecards recorded before that
deploy were still uncommitted at the time; had the rollback not re-hydrated the
index to 985 (it did, verified by count), the next measurement would have run
against a 982-chunk index that — by this pack's own argument — would have looked
entirely healthy. The fault injection being non-sticky was luck of the mechanism,
not a designed safeguard.

*Also worth knowing:* `make up` is ~3–4 minutes end to end, and hydration alone
took 100 seconds in the captured events. That is too slow to do live in front of an
audience — see the demo script's note about pre-warming.
