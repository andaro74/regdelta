# SPEC/01 — Data Ingestion

## Goal
Daily pipeline that pulls the two demo rules (and their CFR context) from
public APIs and lands them, parsed and embedded, in the corpus bucket +
S3 Vectors index + DynamoDB registry.

## Sources
- Federal Register API (FDA agency, type=RULE/PRORULE/NOTICE): full-text
  XML. Target docs incl. 89 FR 106064 ("healthy" final rule), the 2025
  effective-date delay notice, 90 FR 4628 (Red No. 3 order).
- eCFR versioner API: 21 CFR 101.65 (+referenced sections), 21 CFR 74.303
  — current + point-in-time versions.

## Flow
EventBridge (daily 12:00 UTC) → poller Lambda → SQS (DLQ, maxReceive=3) →
processor Lambda. Idempotency key: fr_doc_number / (cfr_section, version_date).

## Processor responsibilities
1. Parse XML. Chunk on CFR paragraph boundaries (§/(a)/(1)/(i)); never split
   mid-paragraph; each chunk carries full citation_path.
2. Metadata extraction with Claude (Bedrock): doc_type, pub_date,
   effective_date(s), compliance_date(s), affected CFR citations, amendatory
   instructions parsed to {action, target} structs.
3. Embed each chunk: Titan Text Embeddings v2, 1024-dim.
4. Write:
   - s3://corpus/raw/<doc_id>.xml and /parsed/<doc_id>.json
   - s3://corpus/chunks/<cfr_part>/<doc_id>.jsonl (chunk records WITH embedding)
   - S3 Vectors index `chunks` (embedding + filterable metadata)
   - DynamoDB registry: DOC#/META, CFR#/VERSION#, DOC#/SUPERSEDES# edges
     (the delay notice SUPERSEDES 89 FR 106064 scoped to effective_date
     only — NOT compliance_date).

## Files
src/ingestion/{poller.py, processor.py, chunker.py, metadata.py}
tests/test_chunker.py, tests/test_metadata.py (fixture XMLs in tests/fixtures)

## Out of scope
AOSS writes (02) · agents (03) · any UI.

## Done when
`make ingest-backfill` results in: both FR docs + CFR sections under
corpus/; every chunk JSONL line contains a 1024-dim embedding; S3 Vectors
index count == chunk count; registry shows the SUPERSEDES edge with
scope=effective_date. `make test` green.
