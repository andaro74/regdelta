# ADR-0012: ADR-0001's reversal condition has fired — Tier B's latency leg is retired, and its remaining case gets a bar before M06 runs

- Status: **accepted 2026-08-18 by the human seat, with all eleven diffs landed
  in the same commit** — the form ADR-0009 used ("Five SPEC/02 changes land with
  this ADR"). The SPEC/06 figures in Ruling 3 were confirmed as written at
  acceptance, before M06 supplied any number to fit them to. *An earlier draft exempted
  Ruling 1 as "a finding about an artifact already in git". Struck for
  incoherence: Ruling 1 carries seven of the eleven diffs below, and its own
  argument is that a ruling whose spec edit is deferred is a ruling lost. The
  count in that draft — "five of eight" — was itself wrong, in the sentence
  condemning imprecision.*

  **The eleven diffs:** Ruling 1 (a)-(g) — `SPEC/04:133-141`, `SPEC/02:62-65`,
  `CLAUDE.md:31-36`, `SPEC/04:170-172`, `SPEC/04:175-176`, `SPEC/04:161-163`,
  `SPEC/02:67-77`. Ruling 2 — `SPEC/04:21-23`, `SPEC/04:4-7`, and an addition to
  `SPEC/04:25-29`'s Done when. Ruling 3 — an addition to `SPEC/06`'s Done when.
  Separately, two insertions into `ADR-0001` proposed for `@regdelta-lead`.
- Date: 2026-08-18
- Milestone: M04
- Basis: PM-seat ruling. The basis is the measured artifact
  `milestones/M04/answer-parity-3966b47.json` and the specs' own text, both in
  git; no second approver exists (ADR-0005). What makes this sound is a number a
  reader can re-derive, not a signature.
- Relates to: **ADR-0001 (two-tier retrieval) — this ADR is the disposition of
  the reopening its reversal condition demands**; ADR-0009 Ruling 3(a) (retired
  the relevance justification and left the performance claim *unmeasured and
  owed to the PM seat*); SPEC/04 "Tier B's latency claim", its UI section and
  two of its Out-of-scope bullets; SPEC/02's Tier B paragraph and Done-when
  criteria 2, 3, (B) and (D); SPEC/06's load test; CLAUDE.md's retrieval rules
- Venue note: `docs/adr/**` is `@regdelta-lead`'s under ROLES.md, while the
  ruling is PM-seat and the drafting was engineering's. Ruling 3 disposes of a
  condition written in ADR-0001; **adopting that disposition into ADR-0001 is
  the lead seat's act**, so this ADR proposes the text and names the trigger
  rather than performing the edit.
- Revised twice after `pm-spec-reviewer` returned REQUEST CHANGES, with eight
  blockers on the first version and seven on the second. The corrections are
  marked inline as "an earlier draft" rather than edited away. **Three of them
  were factual errors about what other documents say** — that this ADR's own
  Relates-to line miscredited ADR-0009, that it claimed SPEC/00 carried the demo
  beat, and that it presented ADR-0001's M02 ruling as new. They are the reason
  this version quotes every document it disposes of.

## Context

Tier B (OpenSearch Serverless, the ephemeral hot tier) rests on two legs in
ADR-0001, and one of them has now failed a measurement it was explicitly
conditional on.

**Leg 1 — the availability contract.** When the hot tier is absent or
unreachable, the always-on tier answers; `router.retrieve_traced` catches
`AossError` and carries the reason out on `Resolution` so a fallback cannot be
silently reported as coverage. ADR-0001 calls this "a genuine production
property, it is tested, and it cannot be demonstrated with one backend", while
naming its own circularity risk and telling the reader to treat it as thin.
**This ADR does not touch leg 1.**

**Leg 2 — "latency and scale, pending measurement."** ADR-0001's Evidence line
asked for "retrieval p50 per tier" at M02. M02 closed without it, recorded as
deferred rather than met, "which matters more than usual, because it is the only
evidence that would substantiate what is left of Tier B's justification."

*An earlier draft of this ADR credited ADR-0009 Ruling 3(a) with naming latency
as the remaining candidate. It did the opposite:* it recorded that a demo
selling Tier B "on latency and concurrent load instead of relevance" would be
resting on a claim that "is *also* currently unmeasured", that trading one for
the other "would be the same defect in new clothes", and left it **owed to the
PM seat**. It was `SPEC/02:62-65` and `SPEC/04:132-141` that narrowed the
candidate to latency. Getting this backwards mattered: it made the ADR read as
completing ADR-0009's work rather than as answering a question ADR-0009
deliberately declined to answer.

**ADR-0001 attached a reversal condition to exactly this measurement:**

> If SPEC/04's latency measurement shows **no material per-query advantage** for
> Tier B at this corpus size, then leg 2 is gone, leg 1 alone is a thin
> justification for ~$0.24/hr plus a second index, a hydration Lambda, a
> data-access policy and a reindex path — and **this ADR should be reopened to
> consider dropping Tier B entirely**.

M04 Phase 4 took the measurement. **The condition has fired.** This ADR is the
disposition of the reopening it demands.

## The measurement

`milestones/M04/answer-parity-3966b47.json`, both halves recorded at one commit
across a `make up` / `make down`, median and p95 `router.retrieve()` over the
nine-probe set, three passes each:

| tier | median | p95 | min | max | n |
|---|---|---|---|---|---|
| A — S3 Vectors | **354.1 ms** | 621.2 ms | 320.8 ms | 630.4 ms | 27 |
| B — AOSS | **889.3 ms** | 1300.7 ms | 788.8 ms | 1328.5 ms | 27 |

Nearest-rank p95; the warmup sample is excluded and recorded separately, because
it carries boto3 client construction and the SSM lookup and would otherwise
dominate a small-n p95 it is not evidence about.

Tier B is **~2.5× slower at the median and ~2.1× at p95**. There is no material
per-query advantage; there is a material per-query *disadvantage*. It agrees in
direction with the only other number in the repo: whole-run `wall_s` had AOSS
slower in every recorded pair (11.6 vs 6.7 at `b16f596`).

### What this number does not say

- **Vantage is the dev laptop, in-process.** That is the instrument SPEC/04
  names for the artifact — the deployed round trip is what the UI readout shows,
  "different instruments" by that criterion's own wording — but Lambda-to-AOSS
  in-region has not been measured and could move the ratio.
- **Sequential, single stream.** Concurrent load is M06's, so nothing here is a
  throughput result.
- **Corpus size is 49 documents.** The regime where a search cluster typically
  wins is scale and concurrency, and this measurement sees neither.

## Decision

### Ruling 1 — leg 2 is retired, and every document asserting it is amended

The claim was conditional on this measurement since M02, the measurement exists,
and it points the other way.

*An earlier draft stated this and proposed no edits, on the reasoning that the
live problem was documents saying "faster". It is not: the live problem is three
documents saying **unmeasured**, which this ruling makes false. Ruling 2's whole
argument is that a ruling whose spec edit is deferred is a ruling lost — and
applying that at one address while leaving it at three others is the same defect
with better paperwork.* The diffs below land with this ADR.

**(a) `SPEC/04:133-141`** (the heading at `:132` stands) — replace the
paragraph beginning "Ruling 3(a) retired Tier B's relevance justification" with:

> Ruling 3(a) retired Tier B's relevance justification: with the lexical lane
> off it runs the same algorithm as Tier A. Its remaining candidate
> justification was **latency**, and M04 measured it: Tier A 354.1 ms median /
> 621.2 ms p95 against Tier B's 889.3 ms / 1300.7 ms, n=27 each
> (`milestones/M04/answer-parity-3966b47.json`). **Tier B is slower, so the
> latency justification is retired** (ADR-0012). What remains is the
> availability contract (ADR-0001 leg 1) and an untested concurrency case whose
> keep-or-retire bar is now written into SPEC/06. The UI readout displays a
> number; displaying one is not asserting one.

**(b) `SPEC/02:62-65`** — replace **all four lines**. Replacing only as far as
"**unmeasured**" strands a second copy of the say/do-not-say instruction and
leaves "The criterion is owed to SPEC/04's 'Done when', not invented here after
the fact", which is now false — it was met there.

> Tier B's candidate latency justification was **measured at M04 and retired**:
> it is ~2.5× slower at the median and ~2.1× at p95
> (`milestones/M04/answer-parity-3966b47.json`, ADR-0012). Say "same algorithm,
> different infrastructure"; do not say "hybrid" and do not say "faster". The
> `wall_s` proxy noted below now agrees with a per-query measurement rather than
> standing alone.

**(c) `CLAUDE.md:31-36`, Architecture rules** — replace from "Tier B's
remaining *candidate* justification" (mid-line 31, leaving "Consequently both
tiers now run the same algorithm on different infrastructure." standing) through
'do **not** say "hybrid", and do not say "faster".' at line 36, with:

> Tier B's latency justification was measured at M04 and **retired**: 889.3 ms
> median against Tier A's 354.1 ms (`milestones/M04/answer-parity-3966b47.json`,
> ADR-0012). Say "same algorithm, different infrastructure" — do **not** say
> "hybrid", and do **not** say "faster". Its remaining case is concurrency, and
> SPEC/06 carries the bar that keeps or retires it.

**(d) `SPEC/04:170-172`**, the Out-of-scope bullet excluding a latency target —
its rationale ("Setting one is a PM call once the number exists") is now spent.
Replace with:

> - **Any latency *target*.** The criterion above gates that a real number
>   exists and is recorded, not that it beats a threshold. The number now exists
>   and the PM call was made: the claim was **retired**, not given a target
>   (ADR-0012). The only threshold in play is SPEC/06's keep-or-retire bar for
>   Tier B, which is a disposition condition and not a figure the system is
>   tuned against.

**(e) `SPEC/04:175-176`**, from "— so" to the end of the bullet — "**until
M06, Tier B's claim is latency only**, never 'handles load'" asserts a retired
claim as the live one. Replacing from :174 would delete "The latency criterion
times sequential probes in a single stream and cannot become concurrency
evidence", which the bullet still needs. Replace only the trailing clause with:

> — so **until M06, Tier B has no performance claim at all**: latency was
>   measured and retired (ADR-0012), and concurrency is M06's to measure.

**(f) `SPEC/04:161-163`** — "The only latency-adjacent number in the repo is
whole-run `wall_s` … it is the reason this claim must not be narrated before it
is measured." Both halves are now false. Replace from "The only latency-adjacent
number" to the end of the paragraph with:

> M04 supplied it (`milestones/M04/answer-parity-3966b47.json`) and the claim
> was **retired, not narrated** (ADR-0012); the whole-run `wall_s` proxy, which
> had AOSS slower in every recorded pair, agrees in direction.

**(g) `SPEC/02:67-77`**, the blockquote — its heading "**The only proxy currently
in the repo runs the other way.**" and its closing "It establishes only that
nothing here supports the claim, **which is why the claim is hedged rather than
asserted**" both go false. Retitle to "**The wall-clock proxy, recorded before
the per-query measurement existed.**" and replace the closing sentence with:

> M04's per-query measurement now settles it directly (ADR-0012), so the claim
> above is retired rather than hedged.

*The census in an earlier draft said "three documents". It is five: this one
missed `SPEC/04:161-163` and `SPEC/02:67-77`, and the ADR-0001 pointer below
missed `ADR-0001:68-75`. Recorded rather than quietly corrected, because a
document whose argument is "find every address" got the count wrong twice.*

*An earlier draft also added a prohibition on "any document, comment, README,
demo script or commit message" describing Tier B as faster. Struck: it
duplicates CLAUDE.md and has no verifier, and a rule with no check is
decoration. The artifact is the enforcement — any such claim is now falsifiable
against a file in git.*

### Ruling 2 — the demo beat's replacement is ADR-0001's, and its spec edit lands here

*Correction, and the reason this is written as an edit rather than a decision:
**ADR-0001 already made this ruling at M02.*** It says the beat "survives, with
its meaning changed: it now demonstrates **that the answer does not change when
the infrastructure does**". The spec edit was deferred and never landed, so
`SPEC/04:21-23` still describes a latency demo. An earlier draft presented that
meaning-change as new and deferred the same edit a second time.

*An earlier draft also claimed the beat is "written into SPEC/00's narrative".
It is not:* `tier-switch` and `demo moment` appear in SPEC/04 and the ADRs and
nowhere in SPEC/00, and ADR-0001 says in terms that it does not amend SPEC/00's
demo narrative. SPEC/00 is struck from this ADR's subject.

**The staging problem, which an earlier draft missed.** Ask a canned scenario,
flip the tier, ask it again — and the second ask is an exact-match cache hit
inside the 1h TTL, so citations and dates agree because the cache agreed with
itself. That is verbatim the failure SPEC/04's control 1 was written to kill for
the artifact, reappearing on stage where no artifact catches it, and it is
sharper because `SPEC/04:29` *deliberately* exercises the cache ("a cached repeat
query returns < 500ms"). The bypass is therefore part of the beat, not a detail.

**Replaces `SPEC/04:21-23`** (three lines, not one — an earlier draft mislabelled
the range and would have duplicated the citation-links clause):

> citation links (federalregister.gov / ecfr.gov); confidence badges;
> "needs human review" state; an active-tier indicator that visibly flips across
> `make up` / `make down`; a per-response cache-state label reading exactly one
> of `hit | miss | bypass | disabled`, and a cache-bypass control; a retrieval
> latency readout (reported, not a claim — ADR-0012); and a cross-tier
> comparison panel retaining the previous tier's `citations[]` and every
> `real_deadline` beside the current tier's, stating an explicit **equal /
> differs** verdict computed on `citations[]` **as sets** and `real_deadline`
> **exactly** — the live tier-switch demo moment, which demonstrates that the
> answer does not change when the infrastructure does.

The vocabulary, the "visibly flips", and "as sets / exactly" are load-bearing and
were dropped by an earlier draft's replacement text: without the `hit`/`bypass`
distinction a viewer cannot see that the beat was cached, and without the
comparison being named a viewer sees two tables that look alike.

**Adds to `SPEC/04:25-29`'s Done when**, so the panel is gated by a command
rather than by rehearsal:

> The tier-switch panel is exercised end to end: with the bypass control on, the
> `healthy-claim` scenario is answered on each tier across a `make up`, every
> response labelled `bypass`, and the panel reports **equal**. This is the UI
> counterpart of `make demo-parity`; the artifact gates, the panel is what a
> viewer sees. Evidence is a screenshot of the panel recorded in
> `milestones/M04/`.

*An earlier draft claimed this gates "by a command rather than by rehearsal"
while describing a browser procedure that left no record. A procedure with no
artifact is rehearsal; naming the screenshot is what makes it a criterion.*

### Ruling 3 — Tier B's remaining case is concurrency, and its bar is written before M06 runs

Leg 1 survives on its own terms. What ADR-0001's reopening asks is whether leg 1
alone justifies the cost, and the evidence that would settle it — concurrency and
scale — has not been taken. Retiring Tier B on this measurement would over-read
it: 49 documents, one stream, one vantage.

*An earlier draft left the bar as "an advantage Tier A cannot match" and
defended the absence on SPEC/04's anti-fitting grounds. That defence has
expired:* SPEC/04 refused a target because **no measurement existed**; one now
does, and by this repo's own RERANK precedent a bar written after M06's numbers
land is the fitted one.

**Adds to `SPEC/06`'s "Done when"**:

> **Tier B's disposition (owed by ADR-0001, homed here by ADR-0012).** At the
> 500-concurrent-user profile, **one run per tier, both taken across a single
> `make up` / `make down` cycle at one sha, with the corpus fingerprint recorded
> identical across both halves** — the discipline
> `milestones/M04/answer-parity-3966b47.json` demonstrates. The 500-user profile
> is run to completion **three times per tier, the first discarded as warmup**,
> with `n` = retrieval calls counted across the scored runs; each report states
> its percentile method and `n`, as that artifact does. ("Passes" is the probe
> set's word and does not transfer to a load profile.)
>
> Report to `loadtest/reports/tier-disposition-<sha>.json`, carrying per tier:
> p95 retrieval latency, the retrieval error rate defined as
> `(AOSS or S3 Vectors 5xx + retrieval-path 429s) / retrieval calls issued to
> that tier` — **Bedrock throttles are excluded**, being an LLM-call property
> shared by both tiers and not caused by the search backend — and the verdict.
>
> **p95 retrieval latency** here is the `router.retrieve()` interval carried on
> the per-node retrieval span (SPEC/06 Observability) — the same interval
> `milestones/M04/answer-parity-3966b47.json` measures, embedding call included,
> both tiers. It is **not** end-to-end `/query` latency, which is
> Bedrock-dominated and would read roughly equal across tiers, letting Tier B
> survive on noise — the attribution objection the error-rate definition above
> makes, pointed at the latency disjunct.
>
> **Tier B keeps its place only if** its p95 retrieval latency is at or below
> Tier A's, **or** its retrieval error rate is at least 5 percentage points
> lower than Tier A's. If neither holds, Tier B is retired: the
> `regdelta-search` stack, the AOSS client, the reindex Lambda and the routing
> branch are removed, and `/regdelta/search/endpoint` stops being a tier
> selector. **Retirement is the default outcome**; keeping Tier B requires the
> recorded measurement above. M06 cannot close without disposing of this clause
> either way. **A difference inside the recorded run-to-run spread is not an
> advantage; ties retire.**
>
> *Out of scope for this clause:* leg 1's availability contract is not
> re-litigated here, the 100-user profile carries no disposition, and an
> in-region re-measurement of M04's sequential number is welcome but is not
> this bar.

That bar is a real climb: sequentially Tier B is 2.1× worse at p95 today, so "at
or below" requires concurrency to reverse a large gap rather than narrow it. The
error-rate disjunct is defined against the search backend specifically, because
a rate dominated by Bedrock 429s would read roughly equal across tiers and would
measure something Tier B does not control — the attribution objection SPEC/04's
control 2 makes about run-to-run variance, pointed at this clause.

**The numbers above are the human seat's to confirm before this ADR is
accepted.** An unconfirmed number is not yet a bar, and by this ADR's own
anti-fitting argument it must be settled **before this ADR is accepted**, not
after M06 supplies numbers to fit.

### Proposed pointer into ADR-0001, for the lead seat

`docs/adr/0001-two-tier-retrieval.md` currently reads `Status: accepted —
amended at M02 close` above a reversal condition with nothing recording that it
fired. Proposed insertion after that condition, performed by `@regdelta-lead` at
M04 close:

> **Fired at M04.** SPEC/04's latency measurement showed Tier B ~2.5× slower at
> the median (`milestones/M04/answer-parity-3966b47.json`). Leg 2 is gone; this
> reopening is disposed of by **ADR-0012**, which keeps leg 1, retires the
> latency claim, and homes a keep-or-retire bar in SPEC/06.

And at `0001:68-75`, where correction 2 says "The scale leg is **unmeasured** —
and the only latency-adjacent number in the repo, whole-run `wall_s`…", append:

> **Updated at M04.** The latency half of this leg is measured and gone; only
> concurrency and scale remain unmeasured, and SPEC/06 carries the bar that
> disposes of them.

## Alternatives considered

- **Retire Tier B now.** Rejected as over-reading the evidence, not as
  unthinkable — and Ruling 3 makes it the *default* outcome at M06. The
  measurement disclaims the regime where a search cluster would win, so retiring
  on it is the mirror image of keeping the tier on a number that never existed.
  *An earlier draft also defended keeping it because retirement "costs the demo
  its cost-control story". Struck: that is a fourth justification — relevance,
  latency, concurrency, now cost — smuggled into a document whose argument is
  that justifications must not migrate.*
- **Keep the beat and re-caption it "no slower".** Rejected: false at this
  measurement, and a beat that needs a hedge is not a beat.
- **Keep leg 2, blame the vantage, re-measure from Lambda.** Rejected as
  motivated re-measurement. An in-region number is worth having and is welcome
  at M06; it is not a route to reinstating a retired claim.
- **Defer the spec edits again.** Rejected — that is what happened at M02, and
  it is why SPEC/04 still describes a beat nobody performs.

## What this ADR does NOT amend

Named explicitly, following ADR-0001's own "What this amendment does NOT do",
because the first two versions of this document each left a document asserting
something the ruling had falsified:

- **ADR-0001 itself.** Proposed text above; the edit is `@regdelta-lead`'s at
  M04 close.
- **SPEC/00.** It carries no tier-switch beat and no latency claim; verified.
- **SPEC/02's Done-when criteria 2, 3, (B) and (D)**, and **SPEC/04:32-33's
  "BOTH tiers"** clause. All survive unchanged *while two tiers exist*. See the
  retirement cost below — they are what M06's default outcome would cost, and
  amending them then is the PM seat's.
- **`evals/scenarios.json`** and the three demo scenarios' business meaning.
  Ruling 2 changes how the tier switch is narrated, not what `healthy-claim`,
  `red-no-3` or `needs-review` assert.
- **The retrieval implementation.** No routing, ranking or configuration change
  follows from this ADR while Tier B exists.

## Consequences

**Easier.** The demo gains a beat falsifiable from an artifact in git, and
SPEC/04's UI section finally states what the UI must show for it to land.

**Harder, deliberately.** Phase 3's build **grows** by the comparison panel, the
cache-state labels and the bypass control. *An earlier draft claimed "Phase 3's
build does not shrink", which was true and beside the point.* M06 gains an
obligation whose default resolves against Tier B.

**What retiring Tier B would cost — the full list, because Ruling 3 makes it the
default.** *An earlier draft named only SPEC/02 criteria 2 and 3.*

| what breaks | why |
|---|---|
| SPEC/02 criterion 2 | requires the two recorded runs to show **distinct resolved tiers** |
| SPEC/02 criterion 3 | cross-tier anti-collapse floor; needs two tiers |
| SPEC/02 Done-when (B) | hydration count-parity is AOSS-only |
| SPEC/02 Done-when (D) | the lane-off Tier B scorecard |
| SPEC/04's comparability criterion | no second tier to compare |
| SPEC/04:32-33 | `--subset retrieval` "on BOTH tiers (search stack down, then up)" |
| CLAUDE.md routing rule | "present → AOSS; absent → S3 Vectors. Both paths must pass evals" |
| ADR-0001 | the decision itself |

Amending those is the **PM seat's** act at that point (CLAUDE.md and ADR-0001 the
lead seat's), and it is a consequence to accept now rather than discover at M06.

**A cost that continues meanwhile.** ~$0.24/hr while up, a ~20-minute deploy with
reindex hydration, and a janitor Lambda that exists to destroy the stack when
someone forgets — now carried by leg 1 plus a pending case. A reason to reach M06
promptly, not a reason to keep the tier.

**SPEC/04's latency Done-when is a conjunction and only half is met.** The
artifact number exists; the UI readout "populated from a real per-query
measurement through the deployed API on both tiers" requires Phase 3, unbuilt.
M04 does not close on this criterion until that half lands.

**Revisit when** M06's concurrency measurement lands — Ruling 3's clause firing,
not an invitation to re-open early.

## Evidence

- `milestones/M04/answer-parity-3966b47.json` — the latency table, and the
  comparability result the replacement beat rests on. Re-judged under the
  hardened gate at `judged_by_sha: 8ab53a8`, exit 0, corpus fingerprint
  `b70879d76cea` identical across both halves, configurations identical, every
  recorded response `cache: bypass`.
- `docs/adr/0001-two-tier-retrieval.md` — the two legs, the reversal condition
  that fired, and the M02 ruling on the demo beat's meaning.
- `docs/adr/0009-cross-tier-parity-criteria.md` — Ruling 3(a), and its refusal
  to substitute one unmeasured claim for another, which is the obligation this
  ADR discharges rather than completes.
- `evals/history/*-retrieval-{s3vectors,aoss}.json` — the `wall_s` pairs:
  whole-run wall clock, not per-query latency, pointing the same way.
- `evals/run_demo_parity.py` — the instrument, and what a sample does and does
  not include.
