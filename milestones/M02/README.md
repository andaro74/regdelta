# M02 — Knowledge base: two retrieval tiers, one contract

- Branch: `m02-knowledge-base`   Tag: _(pending)_   PR: _(pending)_
- Commits: `f7ca738` (probe set) · `dc3748a` (ADR-0005 SME-seat extension) ·
  `ebf8a7e` (both tiers, harness, parity gate)
- Spec: SPEC/02 (amended, 2 deviations)   ADRs: **ADR-0008** (new)
- Status: **Tier A complete and measured. Tier B implemented, not yet
  measured** — it needs the hot tier deployed.

## Done-when status (SPEC/02)

| criterion | status |
|-----------|--------|
| 5. Date attribution, all 3 stores (gating preflight) | ✅ green against the live corpus |
| 1. Recall@8 = 1.0, **S3 Vectors** | ✅ **9/9 probes, recall 1.0** (`ebf8a7e-retrieval-s3vectors.json`) |
| 1. Recall@8 = 1.0, **AOSS** | ❌ **6/9, recall 0.722** (`e89d5b5-retrieval-aoss.json`). See "Tier B does not meet criterion 1". |
| 2. Resolved-tier assertion | ✅ implemented + unit-tested; the cross-run half needs both scorecards |
| 3. Cross-tier Jaccard ≥ 0.60 (per-probe minimum) | ⏳ needs both scorecards |
| 4. MRR reported, not gating | ✅ 0.462 on Tier A, recorded with `mrr_is_gating: false` |
| B. Hydration count-parity fails the deploy | ⏳ code + 16 unit tests; the required evidence is a REAL failed deploy |
| C. `/evals/` in CODEOWNERS | ✅ landed with ADR-0005 |
| Probe set floor (≥8 probes, ≥2 distractors) | ✅ 9 probes, 2 distractor probes, 4 filtered |

**Nothing here is a trap score.** Recall@8 and MRR are retrieval metrics.
SPEC/00b bars any trap score until the q03 tightening closes; it has not.

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

## Tier B does not meet criterion 1, and M02 is therefore not done

**Tier A: 9/9, recall 1.0. Tier B: 6/9, recall 0.722.** SPEC/02 requires 1.0
on both. It is not met and this milestone does not close.

Tier B's first live measurement was **3/9** — and it missed the same DATES and
amendatory-instruction chunks Tier A had. That falsified the assumption behind
the original design: I had built the structural-expansion lane into Tier A
only, on the theory that Tier B's BM25 would find those paragraphs by term
match. It does not. A plain-English question's terms ("compliance", "date",
"effective", "rule") appear throughout a 389-chunk preamble, so a short DATES
paragraph does not win on BM25 either. Sharing the lane took Tier B to 6/9.

The remaining three are all ranking, not retrieval: every missing chunk IS
selected by the expansion lane and IS in the fused candidate list, at ranks
9–13 of 24. They lose the 8-slot page to chunks that scored slightly higher.

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

### What I believe the real fix is

**Index the chunk `kind`.** The chunker already emits `kind` ∈ {dates, summary,
amdpar, preamble, regtext} and it is already in every line of
`corpus/chunks/**/*.jsonl` — `reindex._document()` simply does not copy it into
the AOSS document, and `processor._put_vectors` does not copy it into S3
Vectors metadata. With it indexed, "the paragraph stating what this document
does" becomes a first-class filter/boost instead of something reconstructed
through a DynamoDB citations GSI and then fought for through fusion weights.
The whole `expansion.py` mechanism is a workaround for a field that exists in
the source and is dropped at index time.

Cost: one line in `reindex._document()` plus a mapping field (AOSS rebuilds
from the corpus bucket on every deploy, so no re-ingestion). Tier A needs the
same field in S3 Vectors metadata, which needs a small "rebuild S3 Vectors from
the corpus bucket" utility — reusing the stored embeddings, no Bedrock calls,
no chunk-id changes. That utility is arguably owed anyway: the architecture
rule says search indexes are pure functions of the corpus bucket, and today
only AOSS has a rebuild path.

That is a design change, not a tuning pass, so it is the user's call rather
than something to slip in at the end of a long session.

## The number this milestone is least sure of

`RETRIEVAL_PER_DOC_CAP`. Swept against the probe set:

| cap | 3 | 4 | 5 | 6 | 8 |
|-----|---|---|---|---|---|
| probes passed | 9/9 | **8/9** | 9/9 | 7/9 | 7/9 |

**It is not monotonic.** A value that fails between two passing values means
nine probes cannot determine this constant. Removing the mechanism entirely
costs two probes, so the mechanism is load-bearing and demonstrable; the exact
bound is a judgement. It is set equal to the structural-expansion depth for a
structural reason (a document's expanded set should fit on the page), and the
full sweep is recorded in `shared/config.py` next to the value. First thing to
re-examine if a probe regresses.

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

```bash
make up                 # deploys the hot tier; passes your STS ARN as devPrincipalArn
make retrieval-evals    # records ebf8a7e-retrieval-aoss.json
make retrieval-parity   # criteria 2 and 3 — the cross-run gate
make down               # stops OCU billing
```

Then (B): a deliberate partial-index deploy with `REINDEX_FAULT_DROP` set,
capturing the failed CloudFormation event here. The fault hook can only ever
*cause* a failing deploy — there is no switch in `reindex.py` that relaxes the
count assertion, and a test asserts that property by reading the source.

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
