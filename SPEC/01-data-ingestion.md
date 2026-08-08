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
   - DynamoDB registry: DOC#/META, CFR#/VERSION#, and predicate-typed
     amendment edges (the delay notice SUPERSEDES 89 FR 106064 scoped to
     effective_date only — NOT compliance_date).

### Amendment edges and stays (amended by ADR-0007)
Edges are `<PREDICATE>#<target_doc>#<scope>`, where predicate is one of
`SUPERSEDES` / `STAYS` / `LIFTS_STAY` / `CONFIRMS` and scope is one of
`effective_date` · `compliance_date` · `full` · `stay` · `stay_lifted` ·
`dates_confirmed`. Scope is in the key because a document can do two things to
the same target; `SUPERSEDES#<target>` alone lost one to last-write-wins.
An unrecognized scope raises rather than defaulting to `full`. A stay is
additionally recorded as a first-class interval `STAY_PERIOD#<start>#<asserting
doc>` on the **stayed** document, carrying `dates_changed`. Full vocabulary,
semantics and rationale: ADR-0007 and `.claude/skills/regulatory-domain`.

### Date attribution (amended by ADR-0006)
A document records only the dates it establishes. A date is rejected unless it
appears in the source at day precision — a bare year yields no date, never a
completed one. A delay notice therefore carries `compliance_dates: []`; the
deadline belongs to the rule that set it and is reached through the graph. Its
`effective_dates` DOES record the FR API's `effective_on`, which the publisher
assigns to that document — see ADR-0006 for why the two are not symmetric.

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

**Added by ADR-0006 / ADR-0007 (M01c).** The above closed at M01 but did not
cover what the corpus ASSERTS, only that it exists. Also required:
- `2025-03118`'s `compliance_dates` is `[]` in `corpus/parsed/`, in
  `corpus/chunks/`, and in its DynamoDB `META` — and META does not disagree
  with the chunks on any date field.
- No stored date has day precision absent from its source document.
- `2026-15920` records `LIFTS_STAY` and `CONFIRMS` edges against `2025-00830`
  and **no** `SUPERSEDES` edge, plus exactly one `STAY_PERIOD` interval on
  `DOC#2025-00830` carrying `dates_changed=false`.
- Re-ingesting a document removes amendment edges it no longer asserts.
