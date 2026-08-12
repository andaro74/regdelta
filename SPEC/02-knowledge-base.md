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
- Index `chunks` (mapping lives in src/retrieval/aoss_client.py): kNN on
  embedding, filters as bool/filter clauses. **BM25 on chunk_text +
  citation_path is available but OFF by default** — see "The lexical lane" —
  and when on, the two lanes fuse by client-side RRF and go out as one
  `_msearch` (see the amendment note).

### The lexical lane, and what Tier B now claims
**Amended by ADR-0009 Ruling 3, resolved as (a), after measurement.**
`config.RETRIEVAL_LEXICAL_LANE=1` restores BM25; the default is off, and with
it off Tier B's relevance lane is the raw kNN list.

Measured at `b16f596`, one sha, both configurations: lane-off **9/9, recall
1.000, MRR 0.796**; lane-on **7/9, recall 0.833, MRR 0.648**. Both lane-on
misses are the same chunk, `2025-03118#0003` — the paragraph stating *"the
compliance date remains unchanged at this time"* — which BM25 ranks 14th on r03
and does not return at all on r01, preferring a shorter chunk that repeats the
query's terms without answering it. The only BM25 weight satisfying criterion 1
is 0.05, at which the lane has stopped affecting the outcome.

**Consequently the two tiers now run the same algorithm on different
infrastructure**, and their scorecards agree to sixteen digits of MRR.

Tier B's remaining **candidate** justification is **latency**, and it is
**unmeasured**. Say "same algorithm, different infrastructure"; do not say
"hybrid" and do not say "faster". The criterion is owed to SPEC/04's "Done when",
not invented here after the fact.

> **The only proxy currently in the repo runs the other way.** `wall_s` has AOSS
> slower in every recorded pair — 11.6 vs 6.7 at `b16f596`, 13.3 vs 6.5 at
> `9e47ce7`, 7.9 vs 5.8 at `e596166`. That is whole-run wall clock over nine
> sequential probes including embedding calls, **not** per-query
> `router.retrieve()` latency, so it does not establish that Tier B is slower
> either. It establishes only that nothing here supports the claim, which is why
> the claim is hedged rather than asserted. An earlier draft of this section, and
> of `CLAUDE.md`, stated it as settled architecture with a "say that" instruction
> attached — committing in the repo's highest-traffic document the exact defect
> ADR-0009 named as "the same defect in new clothes". `pm-spec-reviewer` caught
> it (B1).
>
> **"Concurrent load" is struck**, not hedged. It was asserted alongside latency
> and is homed in no milestone: SPEC/04's criterion times nine sequential probes
> in a single stream, which cannot become concurrency evidence. Throughput and
> load are M06's (SPEC/00 "load test & observability"). Claiming half a
> justification that no criterion anywhere will ever check is worse than claiming
> none (B3).
>
> **ADR-0001 already asked for this number at THIS milestone.** Its Evidence line
> requires "retrieval p50 per tier" recorded in `milestones/M02/`. That is
> **deliberately deferred to SPEC/04's criterion and recorded as deferred, not
> met** — M02 closes with Tier B's rationale unverified, and saying so is the
> point. Deferring silently, which an earlier draft did by presenting latency as
> newly owed, is how an obligation disappears (B4).

**Reversal condition.** A probe the lexical lane *wins* — an
`expected_chunk_ids` member BM25 places in the top-8 and the vector lane does
not. Nine probes can witness a counterexample; they cannot establish that BM25
never helps, and (a) claims only the former. Re-enabling the lane to make a
failing probe pass is the move CLAUDE.md routes to a stop, in code rather than in
JSON.

- **Executed by** `make retrieval-evals LEXICAL_LANE={0,1}` on Tier B at one sha,
  then `make retrieval-parity ARGS="--lex {0,1}"`. Cards:
  `<sha>-retrieval-aoss[-lex1].json`.
- **Checked** whenever a probe is added to `evals/retrieval_truth.json`, and at
  any milestone that already runs `make up` — it costs a hot-tier cycle, so it is
  attached to one rather than scheduling its own.
- **A candidate probe goes through the SME carve-out below before admission.** It
  encodes a retrieval-quality judgement, not a corpus fact, and it is authored
  *because* the current default fails it — which is the shape CLAUDE.md routes to
  a stop.
- **If one is admitted, criterion 1 goes RED on Tier A.** By construction: a
  probe whose expected chunk the vector lane does not return is a probe the
  vector-only tier fails, and Tier A has no lexical lane to restore. So
  satisfying this condition is **a PM-seat finding about both tiers, not a licence
  to flip Tier B's flag** — flipping it would leave criterion 1 failing on Tier A,
  and Ruling 1 forbids moving criterion 1. The verdict that follows is a fresh
  ruling, not an automatic reversal.

> An earlier draft said only that such a probe "flips the default back and voids
> the ruling", with no command, no trigger, no owner, and no verdict — and the
> criterion-1 collision above means the stated consequence was not even coherent.
> `pm-spec-reviewer` (B8): the risk was never accidental satisfaction, it was that
> nobody would ever evaluate it, "which makes 3(a) a deletion wearing a flag".
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
>
>    **Superseded in effect by ADR-0009 Ruling 3(a):** with the lexical lane off
>    there is only one query, so the tension this note resolves no longer
>    arises. Kept because it describes the flag-on path, which the reversal
>    condition can restore — and because deleting the record of a resolved
>    tension leaves the next reader to rediscover it.
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
Added by **ADR-0009 Ruling 3**, which *deferred* the non-hybrid-Tier-B question
pending this measurement. The measurement ran, the bar was not cleared, and
Ruling 3 then **resolved as (a)** — see "The lexical lane" above and "Result"
below. The bar is preserved as written; the outcome is recorded beneath it.

The clause above fixed the instrument and the default; it never defined what
"earns the measured clause" means, so that is fixed here — **before the
measurement runs**, because a bar written after the numbers arrive is fitted to
them.

**The bar is reachable, which is what distinguishes it from an impossible
one.** `2025-03118#0003` sits at **fused rank 13 on r01 and 12 on r03** — both
inside the top-20 the reranker scores — so condition 1 is attainable without
any change to the lanes, provided condition 4's placement holds. If a future
measurement moves it outside 20, this bar becomes unreachable and must be
revisited rather than quietly failed.

Reranking is adopted only if **all** of the following hold:

1. **Recall@8 = 1.0 on BOTH tiers at RERANK=1**, satisfying criterion 1 as
   written. A partial improvement does not qualify: "one probe flipped" is the
   pattern this milestone already rejected twice (the `minimum_should_match`
   sweep, and two ranking changes that traded one probe for another), and a bar
   looser than the one used to reject those would be incoherent.
2. **No probe regresses on either tier** — no `expected_chunk_ids` member
   present at RERANK=0 and absent at RERANK=1, and no new `must_not_return`
   violation.
3. **The anti-collapse floor of criterion 3(a) still holds at RERANK=1.** (It
   is a cross-run condition computed *between* tiers, so it holds of a run
   pair, not "on a tier".)
4. **Four scorecards at one sha**, named
   `<sha>-retrieval-<tier>-rerank{0,1}.json` — the base
   `<sha>-retrieval-<tier>.json` namespace cannot express four cards at one sha
   and the second pair would overwrite the first. Each card **records the
   candidate set the reranker scored: its size, and whether it was taken
   before or after per-document diversification.** A null result over a
   post-diversification candidate set does not satisfy this bar, because the
   per-document cap has already evicted the chunk reranking exists to recover —
   such a run measures the ordering, not the reranker.

**MRR is recorded for both runs and is not an adoption condition** (criterion
4 bars citing it as one).

#### Result: measured at `9e47ce7`, bar NOT cleared — reranking stays off
**The bar above is unchanged. That is the point of having written it first**, and
it is recorded here rather than edited, so a reader can check the conditions
against the outcome instead of taking this sentence on trust.

| | Tier A RERANK=0 | Tier A RERANK=1 | Tier B RERANK=0 | Tier B RERANK=1 |
|---|---|---|---|---|
| probes | **9/9** | 8/9 | 7/9 | 8/9 |
| recall@8 | **1.000** | 0.944 | 0.833 | 0.944 |
| MRR | 0.796 | 0.926 | 0.648 | 0.889 |

- **Condition 1 fails** — recall 0.944, not 1.0, on both tiers.
- **Condition 2 fails** — r01 loses `2024-29957#0000` on *both* tiers.
- **Condition 3 fails** — anti-collapse clause (i) fails on r01 on that chunk;
  r07's margin falls to 1, exactly on the floor.
- **Condition 4 holds** — every probe on both `-rerank1` cards reads
  `reranked 20/20 before diversify`, so the failure is a finding about the
  reranker and not an artefact of measuring it after the per-document cap.

The reachability argument held: `2025-03118#0003` was recovered on r01 *and* r03,
from fused rank 13 and 12. Reranking then placed three chunks of one document
above `2024-29957#0000`, saturating `RETRIEVAL_PER_DOC_CAP` with the page full so
nothing back-filled. Whether a cap of 4 recovers it is **not derivable from these
cards** — the pre-diversification ordering is not recorded — and is left as a
measurement rather than promoted to an inference.

Net: Tier A went 9/9 → 8/9, so enabling the flag breaks the tier that passes.
That is the third "one probe traded for another" in this milestone, after the
`minimum_should_match` rejection and two reverted ranking changes, and condition
1 was written before the numbers arrived in order to refuse exactly it.

**Reranking stays off and out of scope. The flag and its tests remain in the
tree** so the measurement is reproducible — a deleted experiment is an
unfalsifiable claim about an experiment. Adoption would need a fresh run clearing
all four conditions, not a re-reading of these cards.

> **These cards measure a Tier B that no longer exists.** They predate the
> `lexical_lane` field entirely, and their `RERANK=0` Tier B column — 7/9 —
> **is the hybrid tier**, which Ruling 3(a) then retired. So condition 2's "no
> probe regresses" was evaluated against a 7/9 baseline that is now 9/9, and the
> reachability argument's "fused rank 13 on r01 and 12 on r03" describes a fused
> ordering that no longer exists — the lexical lane was half of that fusion. This
> is the same stale-row defect ADR-0009 caught in the Tier A cap sweep, and
> `pm-spec-reviewer` (N4) caught it here. **Any adoption run must re-derive the
> reachability argument and re-baseline conditions 1–3 against a lane-off Tier
> B.** The bar's text stands; its recorded result is historical.

Commands: `make retrieval-evals` per tier per flag value, then
`make retrieval-parity --rerank {0,1}` on the matching pair. Producing four
cards at one sha costs **two `make up`/`make down` cycles**, because the router
takes its tier from SSM-param presence with deliberately no override — that is
the price the deferral is being bought with. **If any condition fails,
reranking stays off**, SPEC/02 is unchanged, and ADR-0009 Ruling 3 returns live
as a choice between dropping BM25 and not closing M02.

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

   > **This criterion is per-tier and independent — it does not require the
   > two tiers to return the same results.** Cross-tier agreement is
   > criterion 3's subject. Ruled unamended by ADR-0009 Ruling 1, which is
   > also where the reading is argued; an earlier gloss of "identically on
   > both tiers" caused real confusion. **Reranking is a licensed route to
   > satisfying this criterion** if and only if it clears the RERANK adoption
   > bar under "Optional" — see ADR-0009 Ruling 3.
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

   **(a) Gating: the anti-collapse floor.** Per probe, let `I` be the
   intersection of the two tiers' top-8 chunk_id sets, computed over the
   **full top-8 on every probe** — there is no filtered-probe carve-out here.
   Both must hold:

   - **(i)** `I` contains every member of `expected_chunk_ids`; and
   - **(ii)** `I` contains at least one chunk_id **not** in
     `expected_chunk_ids`.

   Clause (i) is entailed by criterion 1 holding on both tiers, so **(a)'s
   independent content is clause (ii)**: the tiers must agree on at least one
   chunk beyond the ones the probe itself asserts. Where criterion 1 has
   failed on a tier, (a) fails with it and reports the same chunk — it is not
   independent evidence there, and must not be counted as a second failure.
   Aggregation is the minimum across probes, unchanged and for the original
   reason: one collapsed probe cannot hide behind seven healthy ones.
   Pure-negative probes (empty `expected_chunk_ids`) satisfy (i) trivially
   and are still bound by (ii).

   This is not a similarity threshold and is not derived from any observed
   value; it asserts only that the tiers have not become effectively
   disjoint. **The margin — `|I| − |expected_chunk_ids|`, the number of
   further shared slots — is printed per probe by `make retrieval-parity`**, so
   distance-to-firing is observable rather than asserted.

   > **Corrected.** This said "recorded per probe in the scorecard", and
   > engineering review found no scorecard carries it. It cannot: the margin is
   > a property of a *pair* of runs, and a scorecard is one tier's run, so
   > `run_retrieval.py` has nothing to compute it from. The same error applies to
   > the Jaccard claim in (b) below. Both are computed and printed by
   > `run_parity.py`. **Persisting them needs a parity artifact rather than a
   > scorecard field, and that is owed** — until it exists the numbers quoted in
   > `milestones/M02/` are transcribed from a console session, which is weaker
   > than "observable" and is exactly the gap this sentence claimed to have
   > closed. It is deliberately
   weak, and **the honest reading is that cross-tier protection is weaker
   than the original criterion promised**: it catches collapse, not drift.
   Restoring real similarity gating needs a probe set large enough to
   calibrate a threshold, which is not this milestone's.

   > **Ruling 3(a) drained most of the remaining information out of this
   > criterion.** At `b16f596` the two tiers return **identical** top-8 sets on
   > eight of nine probes and differ by exactly one slot on r05; minimum margin
   > is **6**, minimum Jaccard 0.78. So the 0.60 floor Ruling 2 removed as
   > unmeetable would now pass comfortably — which is **not** the floor being
   > vindicated, but the two tiers no longer differing enough for any cross-tier
   > comparison to carry signal. Clause (ii) can now only fire if Tier B
   > disagrees on roughly seven of eight slots.
   >
   > **Attribution, corrected.** An earlier draft said this criterion "is no
   > longer a ranking-drift gate", implying it was one until Ruling 3(a). It was
   > not: **Ruling 2 already stopped it gating drift**, and this criterion's own
   > text says so twenty lines above — "it catches collapse, not drift". Crediting
   > Ruling 3(a) with a cost Ruling 2 had already paid overstates what removing
   > the lane did (`pm-spec-reviewer` B7). What 3(a) changes is narrower: even the
   > *reported* Jaccard now carries almost no information.
   >
   > **The criterion is KEPT and its threshold untouched. Its claimed protective
   > value is stated as claimed, because it has never once fired.** The
   > hypothesis is that it catches *operational* divergence — a partially
   > hydrated index, a filter dialect matching everything or nothing, a stale
   > reindex against a moved corpus. **No divergence observed in this repo, of
   > any class, has failed this gate:**
   >
   > - r07 at `e596166` — Tier B filling with `cfr-21-101.65` version variants
   >   where Tier A filled with preamble, full top-8 Jaccard **0.23**, which is
   >   exactly the "stale reindex against a moved corpus" shape — **passed**, at
   >   margin 2.
   > - `milestones/M02/faultdrop-deploy.md` records that the Tier B cards were
   >   taken *before* the fault-drop deploy, and that a 982-of-985 index "would
   >   have looked entirely healthy" — a partially hydrated index is the *first*
   >   failure this hypothesis names, and our own artifact says the query-side
   >   cards do not see it.
   >
   > So an earlier draft's "this is defence in depth from the query side" was
   > unearned, and stood one paragraph above the concession that contradicts it
   > (B5). **Cheap way to settle it:** `REINDEX_FAULT_DROP` already exists. One
   > lane-off Tier B run against a fault-dropped index through
   > `make retrieval-parity` either fires clause (ii) or does not, and that answer
   > belongs here *before* the protective claim is made. **Owed, and until it
   > exists the sensitivity is claimed, not demonstrated.**
   >
   > **A margin of 6 licenses no health claim.** It should be read as "the two
   > tiers are not grossly divergent" and nothing more — an earlier draft said
   > "both tiers are healthy" four lines above conceding that a subtly wrong Tier
   > B index still passes, which cannot both be true (B6).
   >
   > **The narrower alternative, considered and why it is not taken.** ADR-0009's
   > anti-fitting corollary requires this of any change to a gate, and a
   > purpose-swap is a change to a gate. The alternative is to make criterion 3
   > **non-gating** — reported, like MRR and Jaccard — leaving criterion 1 and
   > Done-when (B) to carry the gating. It is genuinely close. It is not taken
   > because (B) fires only at deploy time, so nothing would gate a Tier B index
   > that degraded *after* a successful hydration, and clause (ii) at margin ≥1
   > costs nothing to keep. **But this reasoning is only as good as the
   > fault-drop measurement above**, and if that measurement shows clause (ii)
   > cannot see a partial index either, then non-gating is the correct answer and
   > this paragraph is the record of what would change it.
   >
   > If the lexical lane is ever restored under the reversal condition, this
   > criterion regains independent content, and its margins **must be re-derived
   > from the new pair** rather than assumed. Under hybrid at `e596166` the
   > minimum was 2 — the order of magnitude to expect, not a value to predict
   > (an earlier draft stated "the margin-2 reading returns with it" flatly,
   > which is a prediction about an unrun measurement at a different sha, cap and
   > corpus).

   **(b) Reported, not gating: per-probe Jaccard of the full top-8**
   chunk_id sets across the two tiers, on **every** probe including filtered
   ones, printed by `make retrieval-parity` (not recorded in a scorecard — see
   the correction under (a)).
   It may **never** be cited as a criterion, the same bar criterion 4 sets
   for MRR.

   > **Why the 0.60 floor went.** It required agreement on six of eight
   > slots — `Jaccard = c/(16−c)`, so 0.60 ⇒ `c = 6` — while this same
   > criterion concedes that "BM25 hybrid and vector+GSI fusion legitimately
   > differ in the tail". A criterion cannot both license tail divergence and
   > permit two slots of it, and that is derivable here without measuring
   > anything. Measurement then showed the verdict is a window artifact: at a
   > 0.60 floor the failing set changes almost completely between full top-8,
   > top-3, top-4 and top-5 (r03 scores 1.00 at top-3 and 0.45 at top-8; r06
   > passes at top-8 and fails at top-4) — though top-8 is the one window
   > with an independent justification, `k` being the served page, so that
   > instability is a reason to distrust *any* similarity floor here rather
   > than proof the specified window was arbitrary. The stronger leg is the
   > internal inconsistency above, which needs no measurement at all.
   > Full-set identity is still *not* required, and **criterion 1 remains the
   > thing that must hold on both tiers** — per tier and independently; see
   > ADR-0009 Ruling 1, which replaces this criterion's former "criterion 1 is
   > what must hold identically".

   **The filtered-probe carve-out is removed, because nothing it protected
   remains at risk.** Its purpose was to stop a filtered probe "fail[ing] M02
   for a reason unrelated to correctness" while Jaccard was the gate. Under
   (b) no Jaccard value can fail anything, and (a) is an identity condition
   over the full top-8 that a long divergent tail cannot break. A carve-out
   with nothing to protect is removed rather than redefined.

   > **Two wrong reasons this was nearly removed for, recorded so neither is
   > repeated.** First: *"the carve-out protected the wrong probes — every
   > filtered probe scores 1.00 and all four failures are unfiltered."* False.
   > Those 1.00s were the carve-out's own output: the implementation
   > approximated the in-filter set as
   > `expected_chunk_ids ∪ must_not_return`, which for a probe with one
   > expected chunk and no forbidden ones is a **single chunk id**, so Jaccard
   > was 1/1 by construction. Measured at `e596166`, r07's *full* top-8
   > Jaccard is **0.23** — it would have been the gating minimum, below r01's
   > 0.33, while both tiers return its one expected chunk. The carve-out's
   > reasoning was correct for as long as the number gated.
   >
   > Second: *"define the in-filter set from the filter predicate instead."*
   > A no-op. `router._finish` already applies `Filters.matches` to every
   > candidate before returning, so every returned chunk satisfies the
   > predicate and "in-filter" would equal the full top-8 — reinstating the
   > 0.23 the carve-out existed to prevent. Any future in-filter definition
   > must name a discriminator narrower than the predicate the router has
   > already applied.
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

**(D) The lexical lane is off by default, and the recorded Tier B card is the
lane-off one.** ADR-0009 Ruling 3(a) is a *default*, so a default silently
flipped is the ruling silently reversed — and flipping it is the cheapest way to
make a failing probe pass, which is why the reversal condition above requires an
SME carve-out and a fresh ruling instead. Evidence: `config.RETRIEVAL_LEXICAL_LANE
is False` asserted directly in
`tests/test_lexical_lane.py::test_the_default_is_off_in_config_not_only_in_this_test`,
and the gating card's `"lexical_lane": false` checked by
`make retrieval-parity` against `--lex 0`. Named here at `pm-spec-reviewer`'s
request (N2): the check existed, the spec did not point at it, while (B) named its
test.

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
(`<sha>-retrieval-<tier>.json`, or
`<sha>-retrieval-<tier>-rerank{0,1}.json` when the RERANK adoption bar is
being measured — see "Optional") and an explicit

**Suffixes, in the order the harness appends them:** `-rerank1` then `-lex1`,
each emitted only for the flag's non-default value, so the base name is the
default configuration and cards predating either flag stay readable. Every card
records `rerank_enabled` and `lexical_lane`, and `make retrieval-parity` gates on
each matching the requested `--rerank` / `--lex` — the filename is not evidence
of what was measured. `-lex1` was omitted from this section when it was added
(`pm-spec-reviewer` N1), which is the exact gap RERANK condition 4 exists to
close for `-rerank{0,1}`.

Continuing the prefix rule: cards also carry an explicit
`"comparable_to_baseline": false` field. The M00b control
(`7f012b8-naive-full.json`) measures answer quality; a recall number is
not a delta against it and must not be read as one.
