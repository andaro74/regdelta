# SPEC/02 — Knowledge Base (two retrieval tiers, one contract)

## Goal
One retrieval interface, two engines behind it. Both must satisfy the same
retrieval contract, verified at M02 against `evals/retrieval_truth.json`
and re-verified end-to-end through the API at M04 (SPEC/04).

## Contract (src/retrieval/router.py)
retrieve(query: str, filters: Filters, k: int) -> list[Chunk]
- Filters: cfr_title/part, date ranges (pub/effective/compliance/version),
  doc_type, fr_doc_number, **kind**.
- Router: SSM /regdelta/search/endpoint present+reachable → AOSS tier;
  else → S3 Vectors tier. Cache SSM lookup across warm invocations (60s TTL).

### Date-filter semantics (ADR-0006)
A date filter selects documents that **establish** that date, never documents
that merely mention it. Concretely: a `compliance_date` range covering 2028
returns the "healthy" final rule's chunks (2024-29957, which sets 2028-02-25)
and **not** the delay notice's (2025-03118, which sets no compliance date at
all).

This is not a recall loss — a user asking what is due in 2028 still gets the
final rule. Returning the notice as well would assert that *the delay* is what
makes 2028 operative, which is the effective-vs-compliance conflation q01
exists to trap; the filter would manufacture the error the trap tests for.
The claim is pinned by the probe pair under "Probe set floor", not left as an
assertion.

This section states observable retrieval behaviour only. The stored field
shape that produces it belongs to SPEC/01 and ADR-0006; the corpus
precondition is Done-when criterion 5.

## Tier A — S3 Vectors (always-on)
- QueryVectors on index `chunks` with metadata pre-filter, topK=k*3.
- Exact-citation assist: if query contains a citation pattern (§ x.y, "FR",
  "Red No. 3"), also fetch exact matches via the DynamoDB citation GSI,
  then merge with vector results via RRF (src/retrieval/fusion.py).

## Tier B — AOSS (ephemeral hot tier)
- Index `chunks` (mapping lives in src/retrieval/aoss_client.py): BM25 on
  chunk_text + citation_path, kNN on embedding, filters as bool/filter
  clauses; client-side RRF. Sent as one `_msearch` — see the amendment note.
- Hydration: reindex Lambda streams corpus/chunks/*.jsonl, bulk 500/batch;
  asserts index count == source count (raise → deploy fails).

> **Amended during implementation (M02), two deviations, both recorded here
> rather than left as a spec that does not describe the code:**
>
> 1. **The reindex handler moved** from `infra/lambdas/reindex/handler.py` to
>    `src/retrieval/reindex.py`, and the index mapping with it. The Lambda now
>    ships `../src` like every core function. Keeping it in its own asset
>    directory meant a second copy of the mapping and of the SigV4 client, with
>    the query tier holding the first — and the two must agree on field names
>    or criterion 3's Jaccard measures the disagreement instead of retrieval
>    drift. This repo has already had that exact bug: `_EDGE_PREDICATE` was two
>    hand-synced copies in M01c and they drifted.
> 2. **"Single hybrid query ... client-side RRF" is served by one `_msearch`.**
>    The two halves of that sentence pull against each other — one query yields
>    one ranked list, and RRF needs two. One `_msearch` is a single round trip
>    carrying both, which honours the intent (no extra latency, fusion here
>    rather than in a search pipeline). Written down because "single query" is
>    the kind of phrase a later reader would take literally.
> 3. **`kind` joins the Filters contract, and both indexes now store it.** The
>    chunker has labelled every chunk `dates | summary | amdpar | preamble |
>    regtext` since M01 and it has been in `corpus/chunks/**/*.jsonl` all
>    along; neither index writer copied it. "Which paragraph states what this
>    document does" — the single most load-bearing distinction in this corpus,
>    since those paragraphs carry the deadlines and the CFR edits — was
>    therefore reconstructed at query time out of the DynamoDB citations GSI.
>    Indexing the field it already had is the fix; `src/retrieval/expansion.py`
>    is the workaround it replaces.
> 4. **Tier A gains a rebuild path** (`src/retrieval/rebuild_s3v.py`). The
>    architecture rule says search indexes are pure functions of the corpus
>    bucket, but only AOSS had a rebuild — Tier A's index was written solely as
>    a side effect of ingestion, so changing its metadata meant re-running the
>    extraction model over unchanged documents. The rebuild reuses the
>    embeddings stored at ingest, never calls Bedrock, and never changes a
>    chunk id, which is what makes it safe against a live index.

## Optional
Claude rerank of top-20 → top-k behind flag RERANK=1. If implemented,
measure the delta in **recall@8 and MRR on the probe set** (not the golden
set — that is M04's instrument) and record both RERANK=0 and RERANK=1 runs.
Unmeasured, it stays off and out of scope.

### The RERANK adoption bar
Added by **ADR-0009 Ruling 3**, which defers the non-hybrid-Tier-B question
pending this measurement. The clause above fixed the instrument and the
default; it never defined what "earns the measured clause" means, so that is
fixed here — **before the measurement runs**, because a bar written after the
numbers arrive is fitted to them.

Reranking is adopted only if **all** of the following hold:

1. **Recall@8 = 1.0 on BOTH tiers at RERANK=1**, satisfying criterion 1 as
   written. A partial improvement does not qualify: "one probe flipped" is the
   pattern this milestone already rejected twice (the `minimum_should_match`
   sweep, and two ranking changes that traded one probe for another), and a bar
   looser than the one used to reject those would be incoherent.
2. **No probe regresses on either tier** — no `expected_chunk_ids` member
   present at RERANK=0 and absent at RERANK=1, and no new `must_not_return`
   violation.
3. **The anti-collapse floor of criterion 3(a) still holds** on both tiers.
4. **Both runs are recorded per tier** — four scorecards, `RERANK=0` and
   `RERANK=1` × two tiers, at one sha — and the reranker is on the fused
   candidate set *before* per-document diversification. Placed after it, the
   cap has already evicted the chunk reranking exists to recover, so a null
   result there measures the ordering rather than the reranker.

Commands: `make retrieval-evals` per tier per flag value, then
`make retrieval-parity`. **If any condition fails, reranking stays off**,
SPEC/02 is unchanged, and ADR-0009 Ruling 3 returns live as a choice between
dropping BM25 and not closing M02.

## Files
src/retrieval/{router.py, s3vectors_tier.py, aoss_tier.py, fusion.py}
src/retrieval/aoss_client.py (new — SigV4 + the index mapping, one copy
  shared by the query tier and hydration)
src/retrieval/reindex.py (new — the AOSS hydration Lambda; see the
  amendment note under Tier B for why it is not under infra/lambdas/)
src/retrieval/rebuild_s3v.py (new — Tier A's counterpart: rebuild the
  vector index from the corpus bucket, reusing the stored embeddings)
src/retrieval/expansion.py (new — the shared structural/lexical lane)
tests/test_reindex_parity.py (new — the partial-index failure test)
evals/retrieval_truth.json (new — see Done when)
evals/run_retrieval.py (new — harness, calls router.retrieve() in-process;
  also hosts the criterion-5 date-attribution preflight)
evals/run_parity.py (new — the cross-run gate for criteria 2 and 3, which
  neither tier run can evaluate from inside itself)
Makefile (new targets `retrieval-evals` and `retrieval-parity`; `up`
  decoupled from the golden set)

## Out of scope
Answer synthesis and every prose assertion (M04) · trap scoring of any
kind (see "No trap score" below) · agent graph, HITL, and timeline /
amendment-graph reasoning (M03) · reranking unless it clears **the RERANK
adoption bar** under "Optional" above · index tuning beyond what the probe set
requires · **the extractor fix and re-ingestion that ADR-0006 requires** —
M02 *gates on* the corpus being correct (criterion 5) but does not produce
the correction; the producer is SPEC/01's · **the amendment-graph traversal
that reaches 2028-02-25 from the delay notice** (M03).

## Done when
Measured at the retrieval contract, not through an answering endpoint.

**(A) `make retrieval-evals` passes on BOTH tiers** — once with the search
stack down (S3 Vectors), once with it deployed (AOSS) — asserting:

Criteria 1 and 4 are per-run. Criteria 2 and 3 are **cross-run** and cannot
be evaluated inside either invocation, since neither run can see the
other's output: each tier run writes its scorecard to `evals/history/`,
then a third step (`make retrieval-parity`) reads both and is what exits
non-zero on 2 and 3. **All three steps must run for (A) to be satisfied.**

1. **Recall (gating).** For every probe in `evals/retrieval_truth.json`,
   **all** chunk_ids in `expected_chunk_ids` appear in
   `router.retrieve(...)` top-8. Partial coverage is a failure, reported
   as `missing: [chunk_id…]`. Any `must_not_return` chunk_id appearing in
   top-8 is also a failure. Recall@8 must be 1.0 on **both** tiers.
   Recall is computed only over probes with a non-empty
   `expected_chunk_ids`; a pure-negative probe contributes no recall term,
   and its `must_not_return` violations fail regardless.
2. **Resolved-tier assertion (gating).** The harness takes
   `--tier {s3vectors,aoss}`, records the tier the router actually
   resolved, and **exits non-zero if resolved ≠ requested**. The two
   recorded runs must show distinct resolved tiers. Without this, an
   unreachable AOSS silently falls back (see Router, above) and two
   S3-Vectors runs would score green as "both tiers".
3. **Cross-tier drift — anti-collapse floor (gating) plus reported
   similarity.** Amended by **ADR-0009 Ruling 2** after first measurement;
   the original 0.60 similarity floor and the reasoning that replaced it are
   both recorded there. Two parts:

   **(a) Gating: the anti-collapse floor.** Per probe, the two tiers must
   share **every chunk criterion 1 requires, plus at least one further
   slot** of the top-8. Aggregation is the minimum across probes, unchanged
   and for the original reason — one collapsed probe cannot hide behind
   seven healthy ones. This is not a similarity threshold and is not derived
   from any observed value; it asserts only that the tiers have not become
   effectively disjoint. It is deliberately weak, and **the honest reading is
   that cross-tier protection is weaker than the original criterion
   promised**: it catches collapse, not drift. Restoring real similarity
   gating needs a probe set large enough to calibrate a threshold, which is
   not this milestone's.

   **(b) Reported, not gating: per-probe Jaccard of the full top-8**
   chunk_id sets across the two tiers, printed by `make retrieval-parity`
   and recorded in every scorecard. It may **never** be cited as a
   criterion, the same bar criterion 4 sets for MRR.

   > **Why the 0.60 floor went.** It required agreement on six of eight
   > slots — `Jaccard = c/(16−c)`, so 0.60 ⇒ `c = 6` — while this same
   > criterion concedes that "BM25 hybrid and vector+GSI fusion legitimately
   > differ in the tail". A criterion cannot both license tail divergence and
   > permit two slots of it, and that is derivable here without measuring
   > anything. Measurement then showed the verdict is a window artifact: at a
   > 0.60 floor the failing set changes almost completely between full top-8,
   > top-3, top-4 and top-5 (r03 scores 1.00 at top-3 and 0.45 at top-8; r06
   > passes at top-8 and fails at top-4). Full-set identity is still *not*
   > required, and **criterion 1 remains the thing that must hold on both
   > tiers** — per tier and independently, which is what that has always
   > meant.

   **Filtered probes: Jaccard is computed over the in-filter result set
   only** — and **the in-filter set is defined by the filter predicate**,
   i.e. the returned chunks satisfying `Filters.matches`. It may **not** be
   approximated by the probe's own `expected_chunk_ids ∪ must_not_return`:
   that degenerates to a single chunk id whenever `must_not_return` is empty,
   making Jaccard 1.0 by construction and exempting the probe instead of
   measuring it. The carve-out itself is sound and is **kept** — measured at
   `e596166`, r07's full top-8 Jaccard is 0.23 while both tiers return its
   one expected chunk, which is exactly the "fail M02 for a reason unrelated
   to correctness" this paragraph was written to prevent. Pure-negative
   probes (empty `expected_chunk_ids`) contribute no Jaccard term and are
   exempt from (a), mirroring their carve-out in criterion 1.
4. **MRR: reported, not gating.** Instrumentation for M03 to compare
   against. It is not a criterion and may never be cited as one.
5. **Date attribution (gating, preflight).** Before any probe runs, the
   harness asserts that document `2025-03118`'s compliance dates are
   **empty** in all three stores that hold it: `compliance_dates == []` in
   its DynamoDB `META`, `compliance_date` absent or null on every line of
   `corpus/chunks/101/2025-03118.jsonl`, and absent from its S3 Vectors
   metadata. Any of the three non-empty → exit non-zero with
   `date_attribution_failed`, before recall is computed. Runs on both tiers.
   A corpus that fails this fails M02 regardless of recall. The harness
   additionally asserts META and the chunks agree on `effective_date`, since
   those two diverged once already. Ruling and rationale: ADR-0006.

   > Two corrections are baked into that wording. It says **empty**, not
   > "non-null" — ADR-0006 prescribes `[]`, which *is* non-null, so an earlier
   > draft would have failed on the exact value the SME approved. And the third
   > store is **S3 Vectors**, not `corpus/parsed/`: the parsed object holds the
   > structure extracted from the XML and has never carried `compliance_dates`,
   > so the criterion was checking a field in a store that does not hold it.

**(B) Hydration count-parity — AOSS only, separate from (A).** Hydration
exists on one tier and is a deploy-time property, so it is not part of the
`retrieval-evals` run. A deliberate partial-index run of the reindex
Lambda must **fail the deploy** (index count != source count → raise).
Evidence: the failing CloudFormation event / Lambda error captured in
`milestones/M02/`. Test lives in `tests/test_reindex_parity.py`.

**(C) `.github/CODEOWNERS` gains `/evals/ @regdelta-eng @regdelta-sme`**
before M02 closes — M00b finding 5, still open. Today only
`golden_questions.json` is gated, so both new files below would be
engineering-self-approvable, and `run_evals.py` — the code that decides
whether ground truth was met — has no owner at all. Note the directory
rule makes `retrieval_truth.json` eng+SME co-gated (it has no more
specific rule); that is intended — see "Ground truth ownership". Note also
that `.github/CODEOWNERS` is itself gated to `@regdelta-lead
@regdelta-security`, so (C) needs a lead + security approval.

### Probe set floor
≥ 8 probes covering both demo rules, including **≥ 2 `must_not_return`
distractor probes** — e.g. the drugs-only § 74.1303 regtext chunks must NOT
appear in top-8 for a food-scoped query. Without distractors a precision
collapse is invisible, and a 3-probe set that engineering authored, selected
k for, and needs 100% on is self-certifying.

> The earlier wording here named "the drugs-only Red No. 3 **compliance**
> chunk (2028-01-18)". No such chunk exists, on two counts. Both dates live in
> ONE chunk (`2025-00830#0000`, the DATES paragraph), so retrieval cannot
> separate them — disambiguation is the answer layer's job at M04. And per the
> SME ruling recorded in SPEC/00, they are **effective** dates; that order sets
> no compliance date. The genuinely drugs-only chunks are `#0027`/`#0028`.
> Corrected after reading the live corpus.

**The date-attribution probe PAIR (both count toward the ≥8 floor).** One
probe would pin only half of it:

- **(a) negative** — `filters` carrying a `compliance_date` range covering
  2028; `must_not_return` lists every `2025-03118` chunk id;
  `expected_chunk_ids` lists the `2024-29957` chunk(s) carrying 2028-02-25.
  Counts toward the ≥2 distractor floor.
- **(b) positive** — an **unfiltered** query asking whether the compliance
  date changed, with `expected_chunk_ids` including the delay notice's
  "compliance date is unchanged" chunk.

(b) is not optional garnish. ADR-0006 states the prose remains reachable by
BM25/semantic retrieval "which is how q01 should assemble it" — so (b) is what
turns "this is not a recall loss" from a claim into an assertion, and it is
q01's retrieval precondition at M04. Without it, retrieval could quietly
deprioritise the notice, M02 goes green, q01 fails at M04, and ADR-0006's own
escape hatch ("the fix belongs in amendment-graph traversal") gets reached for
under deadline.

### Note on `make up`
`make up` currently runs `make smoke` → `run_evals.py` → the SPEC/04 API,
so the AOSS run of (A) cannot execute while that coupling exists. M02
decouples them: `up` deploys and prints the endpoint, and `smoke` moves to
`demo` (which today only prints the URL — so `demo` gains the smoke run
rather than keeping it).

### No trap score
Recall@8 and MRR are retrieval metrics, **not trap scores**. M02 reports
no trap score — the M00b q03 tightening is still open, and SPEC/00b bars
any later milestone from reporting one until it closes. q01 appears here
as a recall probe only; the recorded artifact must say so. The ADR-0006
probe pair is likewise a recall/precision probe, not a trap score.

### Why not the golden set here
`run_evals.py` resolves an API URL unconditionally (`run_evals.py:124`,
before subset filtering), and the API is SPEC/04 — so `--subset retrieval`
cannot execute at M02 without inverting the milestone order. It is also
the wrong instrument: those questions assert on answer prose, so a failure
cannot distinguish "the chunk never came back" from "the model fumbled a
chunk it had". M02 owns retrieval. **The prose assertions are picked up by
SPEC/04's Done-when, amended in the same PR as this edit** — coverage is
relocated, not dropped, and SPEC/04 is where that becomes auditable.

### Ground truth ownership
`evals/retrieval_truth.json` is a NEW file: `{probe_id, question_id, query,
filters, expected_chunk_ids[], must_not_return[], corpus_snapshot, note}`.

`filters` is an object matching the Contract's `Filters` parameter, or `null`
for an unfiltered probe; the harness passes it to `router.retrieve()`
unmodified. It was missing from the first draft of this schema — no Done-when
criterion had exercised filters before criterion 5, which made the
date-attribution probe unauthorable against the stated shape. Two engineers
would have produced two defensible probe sets.

The file is **engineering-authored, with SME-seat entries ruled on and
cited** — see ADR-0005 on why this is a routing rule, not a second
signature. The `/evals/` rule in (C) marks which entries need that
treatment; it cannot enforce it, because there is one human. Authoring norm: which chunk carries a string is a corpus fact,
verifiable by reading the chunk, so those entries should pass review on
inspection. The carve-outs below name where SME judgment is load-bearing
rather than confirmatory.

It is deliberately separate from `evals/golden_questions.json`, which stays
SME-gated and **untouched by this milestone**.

`probe_id` is `r01…rNN` and is the primary key. `question_id` links back to
a golden question where one exists (seed q01, q05, q06 from the retrieval
subset) and is `null` otherwise — the ≥8 floor means most probes have no
golden counterpart, so traceability is partial by construction.

Two carve-outs where the SME's signature is the substance, not a formality:
- **q01's `expected_chunk_ids` is an SME-seat ruling and must be settled
  as one before M02 closes, with its basis recorded.** It encodes the effective-vs-compliance distinction (SPEC/01:
  SUPERSEDES scoped to `effective_date` only), not a corpus fact. Returning
  only the delay notice IS the trap the product exists to defeat, so
  choosing that expected set is a regulatory ruling.
- **Any `expected_chunk_ids` or `must_not_return` entry that encodes a
  regulatory scope, date, or applicability distinction** — rather than
  which chunk contains a string — goes to the SME. The food/drug split in
  the distractor probes is such an entry: asserting the drugs-only
  2028-01-18 chunk must not surface for a food query is a scope ruling
  (SPEC/00), the same class as q01. So is any judgment about which source
  is *authoritative*.

A probe whose distinction is **already settled by an accepted ADR** cites
that ADR in `note` and inherits its ruling; the carve-out is satisfied by
the citation, which is the only thing that ever carried weight. The date-attribution pair is such a
case — ADR-0006 records the ruling and its sources. Without this rule the
SME seat is
either asked to re-approve a ruling they just signed, or engineering
self-approves on the theory that the ADR covers it.

`corpus_snapshot` records the corpus the file was authored against, and must
be **at or after the re-ingestion required by ADR-0006 and ADR-0007** —
re-ingestion changes chunk ids exactly as a chunker change does, so probes
authored against an earlier snapshot are not valid evidence for M02. An
expected chunk_id absent from `corpus/chunks/` is a **hard failure, never
a skip** — chunk ids change when the chunker changes.

### Scorecard namespace
Retrieval scorecards write to `evals/history/` with a distinct prefix
(`<sha>-retrieval-<tier>.json`) and an explicit
`"comparable_to_baseline": false` field. The M00b control
(`7f012b8-naive-full.json`) measures answer quality; a recall number is
not a delta against it and must not be read as one.
