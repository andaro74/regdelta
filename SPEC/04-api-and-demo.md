# SPEC/04 — API + Demo UI

## API (src/api/api.py — FastAPI + Mangum on Lambda)
- POST /query {question, company_profile?, no_cache?} → {answer_rows[],
  citations[], confidence, status, trace_id, **cache**, thread_id?,
  resume_token?} — `cache` is exactly one of `hit | miss | bypass | disabled`
  (`disabled` = the response cache is off by configuration; `bypass` =
  suppressed for this request, via `no_cache` or the `x-regdelta-no-cache`
  header, which is what `milestones/M04/answer-parity-3966b47.json` records).
  `thread_id` and `resume_token` are present only when status is `needs_input`
  or `pending_review`, and together they are the only way to resume that run.
- POST /resume/{thread_id} {reviewer_decision, resume_token} → final answer.
  The path segment is the thread id; LangGraph keys checkpoints by thread, so
  there is no separate checkpoint identifier (evals/serve_local.py:69-73).
  SPEC/03 already writes it this way; this file said `checkpoint_id` and the
  two terms named one thing.
- GET  /health → includes active retrieval tier (aoss|s3vectors)
- Response cache: DynamoDB exact-match on normalized question hash, TTL 1h.
  Semantic cache OFF by default (flag SEMANTIC_CACHE=1) — a wrong cache hit
  in compliance is worse than a slow answer.

## UI (ui/ — static, S3+CloudFront)
Single page: question box; one canned-scenario button per entry in
`evals/scenarios.json`; verdict table with
citation links (federalregister.gov / ecfr.gov); confidence badges;
"needs human review" state; an active-tier indicator that visibly flips across
`make up` / `make down`; a per-response cache-state label reading exactly one of
`hit | miss | bypass | disabled`, and a cache-bypass control; a retrieval latency
readout (reported, not a claim — ADR-0012); and a cross-tier comparison panel
retaining the previous tier's `citations[]` and every `real_deadline` beside the
current tier's, stating an explicit **equal / differs** verdict computed on
`citations[]` **as sets** and `real_deadline` **exactly** — the live tier-switch
demo moment, which demonstrates that the answer does not change when the
infrastructure does.

## Done when
The scenario with id `healthy-claim` renders the full Nordvale table in a
browser against the
deployed stack; /health reports the correct tier before and after
`make up`; a cached repeat query returns < 500ms.

The tier-switch panel is exercised end to end: with the bypass control on, the
`healthy-claim` scenario is answered on each tier across a `make up`, every
response labelled `bypass`, and the panel reports **equal**. This is the UI
counterpart of `make demo-parity`; the artifact gates, the panel is what a viewer
sees. Evidence is a screenshot of the panel recorded in `milestones/M04/` — a
browser procedure with no record is rehearsal, not a criterion.

Plus — **the prose assertions SPEC/02 relocated here**:
`python evals/run_evals.py --subset retrieval` passes against the deployed
API on BOTH tiers (search stack down, then up). M02 measures retrieval at
the `router.retrieve()` contract because no answering endpoint exists yet;
this milestone is the first point at which those questions can run as
written, and it is where they become binding. See SPEC/02 "Why not the
golden set here" — that deferral is only honest if this clause holds.

This also re-verifies SPEC/00's "same golden set must pass on both paths":
after M02, cross-tier evidence is chunk-level only, so the live tier-switch
demo moment above has no answer-level verifier until this runs.

### Answer-level cross-tier comparability (owed by ADR-0009)
Passing the same assertions on both tiers is **not** the same as producing
comparable *answers*, and the tier-switch demo beat sells the latter. ADR-0009
recorded this as unhomed; it is homed here.

`answer_rows[]` are SPEC/03's verdict rows — `{product, trigger,
required_change, real_deadline, confidence, citations[]}`.

**Done when:** `make demo-parity` writes
`milestones/M04/answer-parity-<sha>.json` recording, per scenario in
`evals/scenarios.json` (`{id, question, company_profile}`) per tier: the
scenario `id`, the **sha256 of that scenario's `question` and
`company_profile` exactly as run**, the citation set, every `real_deadline`,
and each response's **cache status**. It passes when, for each scenario, the two tiers agree on (a) every
`citations[]` entry — FR doc number and CFR section, as sets — and (b) every
`real_deadline`, exactly. Confidence may differ; prose may differ. **A citation or
a date that changes when only the infrastructure changed is a bug**, by the same
argument that makes an uncited answer a bug rather than a style issue.

The sha256 is what keeps the artifact readable later. "Scenario 1" in a
six-month-old artifact means nothing if the question behind it was since
reworded, and SPEC/00's prose is not a diffable subject for a gate — that is
the trap-census defect class, a criterion whose subject can move without a
diff.

Two controls, without which this criterion measures nothing:

1. **Both runs bypass the response cache**, and the artifact records that they
   did. The cache is an exact-match DynamoDB lookup on the normalised question
   hash with a 1h TTL, and the two tier runs are minutes apart across a `make up`
   / `make down` — well inside the TTL. Uncontrolled, the second tier's request is
   a **cache hit returning the first tier's stored answer**, so citations and
   dates agree by construction and the criterion measures the cache.
2. **Each scenario is additionally answered twice on ONE tier.** Without a
   same-tier control a disagreement cannot be attributed: ordinary LLM
   run-to-run variance and genuine tier-caused divergence look identical. A
   same-tier disagreement is a **determinism** finding and voids the cross-tier
   reading for that scenario.

> **Both controls are corrections, not refinements.** The first draft of this
> criterion was **green by construction via the response cache** — the same defect
> class as ADR-0009 fact 4's in-filter tautology (a comparison that was 1/1 by
> construction and measured nothing), reproduced in a criterion written *after*
> that finding was recorded. It also claimed a disagreement "indicates the answer
> layer is non-deterministic across tiers", which does not follow without control
> 2 — the same instrument objection SPEC/02 makes against using the golden set at
> M02, pointed at my own new criterion. And it asserted on `real_deadline`, a
> field this spec never defined, with no command or artifact producing the
> comparison. `pm-spec-reviewer` B10 and B11.

After ADR-0009 Ruling 3(a) both tiers run the same retrieval algorithm, so this is
expected to pass easily. It stays because "expected to pass" is not "checked", and
because the tier-switch demo beat sells answer-level equivalence specifically.

### `/resume` is not an open door
Raised by `security-reviewer` against `evals/serve_local.py:66-81`, which is
harmless on loopback with a uuid4 thread id and which declares itself the
template this milestone copies (`serve_local.py:222-223`). Unauthenticated,
`/resume` returns the full answer, `citations[]` and `confidence` for any
thread id a caller supplies — and that checkpoint holds the asker's
`company_profile` and the passages retrieved for them. `/query` exposes public
FDA rules; `/resume` exposes one asker's state. Those are not alike.

**What it is not:** no identity provider, no accounts, no login, no session.
The `resume_token` above is a bearer capability minted with the checkpoint,
unguessable, bound to exactly one thread, and expiring with it. It is not
single-use: `hitl_gate` re-executes on resume and the review write is
idempotent for that reason (`src/graph/checkpoint.py`), so a token burned by a
failed round trip would strand an intact checkpoint — a worse failure than the
one single-use prevents.

**Done when:** `make test` runs a test that (a) starts a run that pauses,
captures its `thread_id` and `resume_token`, and resumes successfully; and (b)
POSTs that same `thread_id` four ways — a token minted for a *different*
thread, a malformed token, no token at all, and a `thread_id` that was never
created. All four return **404 with byte-identical bodies**, so the response
cannot distinguish "not yours" from "does not exist". The body carries the
`trace_id`; which of the four occurred is written to the server log against
that `trace_id` and appears nowhere in the response.

The requirement is **indistinguishability**, not the status code. "404 rather
than 403" is trivially satisfiable by a 404 whose body reads "token does not
match thread t-abc", and the leak survives the letter of it. Four byte-identical
responses is falsifiable by diffing them. The log line is not optional wording:
an opaque 404 makes a legitimate resume failure hard to diagnose, and without a
recorded reason keyed to `trace_id` the honest ruling would be against the
opaque 404 — an undiagnosable demo failure costs more than a uuid4 existence
oracle.

### Tier B's latency claim (owed by ADR-0009 Ruling 3(a))
Ruling 3(a) retired Tier B's relevance justification: with the lexical lane off
it runs the same algorithm as Tier A. Its remaining candidate justification was
**latency**, and M04 measured it: Tier A 354.1 ms median / 621.2 ms p95 against
Tier B's 889.3 ms / 1300.7 ms, n=27 each
(`milestones/M04/answer-parity-3966b47.json`). **Tier B is slower, so the latency
justification is retired** (ADR-0012). What remains is the availability contract
(ADR-0001 leg 1) and an untested concurrency case whose keep-or-retire bar is now
written into SPEC/06. The UI readout displays a number; displaying one is not
asserting one.

**Done when:** the UI readout is populated from a real per-query measurement
through the deployed API on both tiers, and `make demo-parity`'s artifact records
**median and p95 `router.retrieve()` latency per tier over the probe set**. The
artifact number is what gates; the UI readout is what a viewer sees. Those are
different instruments — in-process harness versus Lambda round trip — and an
earlier draft fused them into one criterion without saying which one gates
(`pm-spec-reviewer` N5).

**No target is set here, deliberately.** A threshold invented before the first
measurement would be fitted to nothing, and if Tier B turns out *not* to be
meaningfully faster at this corpus size that is a finding to record and a demo
beat to drop, not a number to tune until it passes. What this criterion gates is
the **existence and honesty of the number**. Deciding what to do with it is a
PM-seat call once it exists.

**This obligation is older than this milestone.** ADR-0001's Evidence line asked
for "retrieval p50 per tier" recorded at **M02**. M02 closed without it, recorded
as deferred rather than met — see SPEC/02 "The lexical lane". M04 supplied it
(`milestones/M04/answer-parity-3966b47.json`) and the claim was **retired, not
narrated** (ADR-0012); the whole-run `wall_s` proxy, which had AOSS slower in
every recorded pair, agrees in direction.

## Out of scope
Added at `pm-spec-reviewer`'s request (B9): this file gained two gating criteria
while having no scope boundary at all, so each omission below was a judgement
buried in prose rather than a declared exclusion.

- **Any latency *target*.** The criterion above gates that a real number exists
  and is recorded, not that it beats a threshold. The number now exists and the
  PM call was made: the claim was **retired**, not given a target (ADR-0012). The
  only threshold in play is SPEC/06's keep-or-retire bar for Tier B, which is a
  disposition condition and not a figure the system is tuned against.
- **Concurrent-load and throughput evidence.** M06's (SPEC/00, "load test &
  observability"). The latency criterion times sequential probes in a single
  stream and cannot become concurrency evidence — so **until M06, Tier B has no
  performance claim at all**: latency was measured and retired (ADR-0012), and
  concurrency is M06's to measure.
- **Prose- and confidence-level cross-tier comparability.** Explicitly excluded
  by the comparability criterion: only citations and `real_deadline` must match.
- **Comparability for anything but the scenarios in `evals/scenarios.json`.**
  The golden set runs per tier (above); pairwise answer comparison does not.
  That file is the canonical scenario set. SPEC/00's "Demo scenarios" prose is
  the narrative behind them and is not this gate's subject.
- **Semantic cache.** Flag-off by default (`SEMANTIC_CACHE=1`), and a wrong cache
  hit in compliance is worse than a slow answer. No criterion here exercises it.
- **Auth on `/query`.** Not specified in this milestone. Worth naming because
  "production-grade demo" and "production" differ here, and this is one of the
  places they differ. **This exclusion does not extend to `/resume`**, gated
  under "`/resume` is not an open door" above: `/query` answers questions about
  public rules, while `/resume` serves back a specific asker's checkpointed
  state, including the company profile they supplied and the passages retrieved
  for them. Leaving both unauthenticated would be one decision; leaving one
  unauthenticated and the other unmentioned was an omission. What `/resume`
  gets is a bearer capability, not an identity — **user accounts, login, SSO
  and multi-tenant isolation remain out of scope here, as SPEC/07 declares.**
- **Who may read the HITL review queue.** `write_review_item` puts the asker's
  question text at `pk=REVIEW#<thread>` (`src/graph/checkpoint.py`) for the SME
  seat to work (ROLES.md: the SME "staffs the HITL queue"). No API surface in
  this milestone reads it, so there is nothing here to gate; the exposure is a
  table read, and scoping table reads is SPEC/05's "Security tightening".
  Named rather than left to be found — it is the same class of gap as
  `/resume`, differing only in that `/resume` has an endpoint and this does
  not.
