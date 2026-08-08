# SPEC/02 — Knowledge Base (two retrieval tiers, one contract)

## Goal
One retrieval interface, two engines behind it. Both must satisfy the same
retrieval contract, verified at M02 against `evals/retrieval_truth.json`
and re-verified end-to-end through the API at M04 (SPEC/04).

## Contract (src/retrieval/router.py)
retrieve(query: str, filters: Filters, k: int) -> list[Chunk]
- Filters: cfr_title/part, date ranges (pub/effective/compliance), doc_type.

### Date-filter semantics (ADR-0006)
A date filter selects documents that **establish** that date, never documents
that merely mention it. Concretely: a `compliance_date` range covering 2028
returns the "healthy" final rule's chunks (2024-29957, which sets 2028-02-25)
and **not** the delay notice's (2025-03118, which sets no compliance date at
all). The notice's chunks carry `compliance_date = null`.

This is not a recall loss — a user asking what is due in 2028 still gets the
final rule. Returning the notice as well would assert that *the delay* is what
makes 2028 operative, which is the effective-vs-compliance conflation q01
exists to trap; the filter would manufacture the error the trap tests for.

The probe set must include a probe that pins this, and a corpus whose stored
`compliance_date` for 2025-03118 is non-null fails M02 regardless of recall.
- Router: SSM /regdelta/search/endpoint present+reachable → AOSS tier;
  else → S3 Vectors tier. Cache SSM lookup across warm invocations (60s TTL).

## Tier A — S3 Vectors (always-on)
- QueryVectors on index `chunks` with metadata pre-filter, topK=k*3.
- Exact-citation assist: if query contains a citation pattern (§ x.y, "FR",
  "Red No. 3"), also fetch exact matches via the DynamoDB citation GSI,
  then merge with vector results via RRF (src/retrieval/fusion.py).

## Tier B — AOSS (ephemeral hot tier)
- Index `chunks` (mapping lives in infra/lambdas/reindex/handler.py):
  single hybrid query — BM25 on chunk_text + citation_path, kNN on
  embedding, filters as bool/filter clauses; client-side RRF.
- Hydration: reindex Lambda streams corpus/chunks/*.jsonl, bulk 500/batch;
  asserts index count == source count (raise → deploy fails).

## Optional
Claude rerank of top-20 → top-k behind flag RERANK=1. If implemented,
measure the delta in **recall@8 and MRR on the probe set** (not the golden
set — that is M04's instrument) and record both RERANK=0 and RERANK=1 runs.
Unmeasured, it stays off and out of scope.

## Files
src/retrieval/{router.py, s3vectors_tier.py, aoss_tier.py, fusion.py}
infra/lambdas/reindex/handler.py (implement its TODO)
tests/test_reindex_parity.py (new — the partial-index failure test)
evals/retrieval_truth.json (new — see Done when)
evals/run_retrieval.py (new — harness, calls router.retrieve() in-process)
Makefile (new targets `retrieval-evals` and `retrieval-parity`; `up`
  decoupled from the golden set)

## Out of scope
Answer synthesis and every prose assertion (M04) · trap scoring of any
kind (see "No trap score" below) · agent graph, HITL, and timeline /
amendment-graph reasoning (M03) · reranking unless it earns the measured
clause under "Optional" above · index tuning beyond what the probe set
requires.

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
3. **Cross-tier drift (gating, with a floor fixed now).** Report Jaccard
   of the full top-8 chunk_id sets across the two tiers, **computed per
   probe; the gate is the minimum across probes**, so one collapsed probe
   cannot hide behind seven healthy ones. **Below 0.60 fails.** The floor
   and the aggregation are written here, before first measurement, and may
   not be changed to match whatever is observed — changing either is a spec
   edit requiring PM approval. Full-set identity is *not* required: BM25
   hybrid and vector+GSI fusion legitimately differ in the tail. Criterion
   1 is what must hold identically.
4. **MRR: reported, not gating.** Instrumentation for M03 to compare
   against. It is not a criterion and may never be cited as one.

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
distractor probes** — e.g. the drugs-only Red No. 3 compliance chunk
(2028-01-18) must NOT appear in top-8 for a food-scoped query. Without
distractors a precision collapse is invisible, and a 3-probe set that
engineering authored, selected k for, and needs 100% on is self-certifying.

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
as a recall probe only; the recorded artifact must say so.

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
expected_chunk_ids[], must_not_return[], corpus_snapshot, note}`. It is
**engineering-authored and SME-countersigned** via the `/evals/` rule in
(C). Authoring norm: which chunk carries a string is a corpus fact,
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
- **q01's `expected_chunk_ids` requires explicit SME sign-off before M02
  closes.** It encodes the effective-vs-compliance distinction (SPEC/01:
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

`corpus_snapshot` records the corpus the file was authored against. An
expected chunk_id absent from `corpus/chunks/` is a **hard failure, never
a skip** — chunk ids change when the chunker changes.

### Scorecard namespace
Retrieval scorecards write to `evals/history/` with a distinct prefix
(`<sha>-retrieval-<tier>.json`) and an explicit
`"comparable_to_baseline": false` field. The M00b control
(`7f012b8-naive-full.json`) measures answer quality; a recall number is
not a delta against it and must not be read as one.
