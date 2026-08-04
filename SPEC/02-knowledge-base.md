# SPEC/02 — Knowledge Base (two retrieval tiers, one contract)

## Goal
One retrieval interface, two engines behind it. Both must pass the
retrieval subset of the golden set.

## Contract (src/retrieval/router.py)
retrieve(query: str, filters: Filters, k: int) -> list[Chunk]
- Filters: cfr_title/part, date ranges (pub/effective/compliance), doc_type.
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
Claude rerank of top-20 → top-k behind flag RERANK=1; measure eval delta.

## Files
src/retrieval/{router.py, s3vectors_tier.py, aoss_tier.py, fusion.py}
infra/lambdas/reindex/handler.py (implement its TODO)

## Done when
`python evals/run_evals.py --subset retrieval` passes on BOTH tiers:
once with the search stack down, once after `make up`. Hydration
count-parity assertion demonstrated by a deliberate partial-index test.
