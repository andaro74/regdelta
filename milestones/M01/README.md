# M01 — Ingestion + amendment graph

- Git tag: `m01`   Branch: `m01-ingestion`   Commits: `2a5c915`
  (implement), `bc07280` (review fixes), `7f012b8` (region/model alignment)
- Spec: SPEC/01-data-ingestion.md   ADRs touched: none new
- Sessions: 2 Claude Code sessions

## Done-when verification (SPEC/01)
All four criteria verified against the deployed stack in **us-west-2**:

| criterion | result |
|-----------|--------|
| Both FR docs + CFR sections under `corpus/` | ✅ 8 documents — 3 FR + 5 eCFR section snapshots, each with `raw/`, `parsed/`, `chunks/` |
| Every chunk JSONL line contains a 1024-dim embedding | ✅ 452/452 chunks, 0 malformed |
| S3 Vectors index count == chunk count | ✅ 452 == 452 |
| Registry shows SUPERSEDES edge with `scope=effective_date` | ✅ `DOC#2025-03118 / SUPERSEDES#2024-29957`, `scope=effective_date`, `target_raw="89 FR 106064"` |
| `make test` green | ✅ 20 passed (37 after M00b) |

Corpus: healthy final rule `2024-29957` (389 chunks), delay rule
`2025-03118`, Red No. 3 order `2025-00830` (29), plus 21 CFR 101.65
(2024-12-01 and current), 101.13, and 74.303 (2025-01-01 and current).
DLQ empty at completion.

## Scorecard
No eval row for M01. The golden set requires an answering endpoint, and
`src/api/api.py` is SPEC/04. M01's exit criterion is the Done-when table
above; the first scorecard in this repo is M00b's, which runs against the
corpus this milestone produced.

## What you can demo at this point (2-3 min)
1. `make ingest-backfill` → 8 messages enqueued; watch the DLQ stay empty.
2. Show the amendment edge in DynamoDB: `DOC#2025-03118` SUPERSEDES
   `DOC#2024-29957` with `scope=effective_date`. This is the demo's whole
   thesis in one row — the delay moved the *effective* date and left the
   2028-02-25 compliance deadline untouched, and the graph records which.
3. Show a chunk's `citation_path` (`21 CFR 101.65(d)(2)`) and the DATES
   chunk carrying both "February 25, 2025" and "February 25, 2028".

## Evidence artifacts
- Corpus bucket `regdelta-core-corpusbucket36de2aaa-lsw14vnseyri` (us-west-2)
- Vector index `regdelta-vectors-581208540944/chunks` — 452 vectors
- Registry table `regdelta-core-RegistryTableF2430F90-2FKHSM738R7Y`
- `tests/fixtures/` — real FR/eCFR XML, verbatim from the live APIs
- eng-code-reviewer: 11 findings, all fixed in `bc07280`

## What broke / what I'd redo

> ⚠️ Written from the engineering seat. Not yet reviewed by the human PM/SME.

**1. The idempotency marker was written before the writes it guarded.**
`DOC#/META` was written first, so a crash or timeout partway through would
mark the document ingested and the SQS retry would skip it — permanently
losing the SUPERSEDES edge the entire demo depends on. Markers (`META`,
`VERSION#`) now go last, so a partial ingest retries in full. Caught by
eng-code-reviewer.

**2. The nutrient tables were being silently dropped.** The parsers walked
`<P>` elements only, but the saturated-fat/sodium limits and food-group
equivalents — the substance of "does it apply to us" — live in `GPOTABLE`
(FR) and HTML table divs (eCFR). Verified the loss: no "saturated fat"
threshold text reached any chunk. Both are now flattened into the paragraph
stream in document order. The original test could not have caught this,
which was itself a review finding.

**3. Ingestion order is a race, and failing loudly was the right call.**
SQS standard queues do not preserve order, so the delay rule was processed
before the healthy rule it supersedes and could not resolve "89 FR 106064"
to a document number. An earlier version swallowed that and fell back to
using the raw citation string as the edge key, producing a nondeterministic
graph. It now raises and lets SQS retry. Observed in production exactly
once: the delay rule failed, retried after the healthy rule landed,
resolved via the registry, DLQ never received a message. **The design was
validated by the failure, not by the success.**

**4. eCFR snapshot dates were being published as `effective_date`.** An
eCFR snapshot date is when a text was retrieved, not when a rule takes
legal effect — conflating them violates the one domain rule this product
exists to respect. Renamed to `version_date` with `effective_date=None`.

**5. The stack deployed to a different region than the code assumed.**
`infra/app.py` reads `CDK_DEFAULT_REGION`, which resolved from the local
profile to us-west-2, while the Makefile and `config.py` hardcoded
us-east-1. Every CLI target would have silently missed the stack. Aligned
the code to the deployed reality rather than redeploying. **Worth an env
assertion at boot rather than discovering it from an empty query result.**

**6. Bedrock model access was not what the account listing implied.**
`list-foundation-models` advertises the Claude 5 family and Opus 4.7/4.8 in
us-west-2, but all of them return `AccessDeniedException` on invoke
(`agreementAvailability: NOT_AVAILABLE`). The first backfill failed every FR
document on the metadata-extraction call. Listing is not entitlement —
probe with an actual Converse call before pinning a model.

**7. Windows portability.** `make ingest-backfill` wrote the Lambda response
to `/dev/stdout`, which does not exist here; and reading UTF-8 FR/eCFR XML
under the cp1252 default raised decode errors. Both fixed, but they cost
real time during an otherwise clean deploy.

**What I'd redo:** verify table extraction against the *fixture* before
writing the chunker, not after. Finding 2 was invisible until someone
grepped the output for text that should obviously have been there — and the
tests I wrote first would have stayed green forever.
