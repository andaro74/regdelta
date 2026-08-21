# M06 — session state, 2026-08-21

Written so the next session starts from a record rather than a re-derivation.
**Nothing is deployed. Nothing has been spent.** Every AWS call across both
M06 sessions has been read-only: Service Quotas, CloudWatch metrics, Cost
Explorer, DynamoDB reads, and one `logs:TestMetricFilter`.

Branch `m06-load-and-observability`, cut from `m05-deploy-lifecycle` at
`f1de2a3` (**not** from `main`; PR #12 and `main` are untouched).

Suite: **1129 passed, 1 skipped, 3 failed** — the three are the known
`test_replay_exit_codes` q03 FRAGILE gate, red by the seat's M05 decision.
Lint clean across `src evals infra tests loadtest`.

---

## What the second session did

Session one built observability and found that SPEC/06's disposition clause
could not be executed. Session two built the thing that executes the amended
one, and **three review passes found five ways it would have retired Tier B
without measuring it.** That is the milestone's real finding and it is why the
file is this long.

### The deploy surface (step 1)

`LoadDriverFn` in `regdelta-core`, its role threaded through `infra/app.py`
into `regdelta-search`'s data-access policy as an index READER. It lives in the
persistent stack because the Tier A half is taken with the hot tier destroyed;
its AOSS grant lives in the ephemeral one, so the permission exists exactly as
long as the collection does.

`bedrock:InvokeModel` is scoped to **Titan Text Embeddings V2 alone**. Reusing
`_bedrock_model_arns()` is the obvious edit and would hand a 90-call-per-second
driver a grant on Opus 4.6. `loadtest/budget.py` cannot help there — it is a
Python object inside the orchestrator and cannot constrain a console invoke.
IAM can.

### The orchestrator (step 2)

`loadtest/retrieval_load.py` walks the pre-registered schedule (10/25/50/75/90
calls/s × 60 s, three runs per tier, first discarded), invokes the driver per
step, checkpoints after every run, merges each half into
`loadtest/reports/tier-disposition-<sha>.json` and judges. Six exit codes.
Everything gated is **re-derived** from the recorded steps —
`dispositive_eligible` is the driver's word and is deliberately not read.

`make tier-disposition` and `make tier-disposition-price`.

---

## The five ways it would have retired Tier B without measuring it

Each was found by a review, each is fixed, and each has the mutation that
would undo it.

| # | found by | the defect |
|---|---|---|
| 1 | security-reviewer | A step could report `tiers_observed ["s3vectors"]`, `errors 0`, `dispositive_eligible true` while pointed at AOSS. The router falls back silently by design, so a data-access-policy propagation delay filed **Tier A's latencies under Tier B**. |
| 2 | security-reviewer | The driver's `aoss:APIAccessAll` grant was guarded by nothing — deleting all four lines left the **entire suite green**. Without it every AOSS call 403s, the router falls back, same outcome as 1. |
| 3 | security-reviewer | The p95 was computed over **survivors**. A call that never returned was in no sample, so invisible in `n` AND in the error rate; measured, 2 of 20 calls returned and the step reported `error_rate 0.0` and called itself eligible. Biased toward whichever tier failed more — it can manufacture a `keep` as readily as a `retire`. |
| 4 | eng-code-reviewer | `attempts_per_tier` counted **recorded attempts, not failed measurements**. Reproduced: one gate-failed attempt (the corpus moved between halves) plus one real failed measurement gave `verdict: retire`, exit 5. |
| 5 | pm-spec-reviewer | A fallback **disqualified** a step, so Tier B degrading under concurrency — the only regime its remaining case is about — produced no error, no dispositive step, no failed measurement and no attempt. Only unbounded re-runs, with the default outcome unreachable by the behaviour the clause exists to measure. |

Two more that would have measured the wrong thing rather than the wrong tier:

- **`s3vectors_tier`'s connection pool was botocore's default 10**, against ~32
  (Tier A) and ~80 (Tier B) calls in flight at the top step. The excess blocks
  in urllib3 **inside `router.retrieve()`** — the interval the p95 is defined
  over — so the comparison would have been between two queues in one process.
  `config.RETRIEVAL_POOL_SIZE`.
- **`aoss_client` rebuilt a botocore Session per request**: 6.430 ms median of
  GIL-bound CPU, AOSS path only, inside the measured interval — 579 ms of CPU
  per wall second at 90 calls/s. Measured offline,
  `milestones/M06/aoss_per_call_overhead.json`. Memoised.

**Still present and RULED, not fixed:** `aoss_client` opens a fresh TCP+TLS
connection per call because nothing installs an opener with a pool, while Tier
A holds a urllib3 pool. Not measurable offline, and not a change to make in the
week Tier B is disposed of. The seat ruled **option 2 — record it and run**, and
it is in every report as `known_limitations`, which bounds a `retire` verdict to
*RegDelta's AOSS tier as implemented* rather than to OpenSearch Serverless.

---

## What is built

| area | state |
|---|---|
| `shared/observability.py` | EMF + X-Ray subsegment over the daemon UDP socket. **No new runtime dependency.** |
| `graph/instrument.py` | Per-node span policy; optional `on_span` sink so the driver can record each span's emission status per call. |
| `src/ops/retrieval_load.py` | The open-loop step driver. Thread ceiling, absolute join deadline, three disjoint call outcomes, all three populations reported. |
| `loadtest/retrieval_load.py` | The orchestrator and the judgement. |
| `loadtest/budget.py` | The $20 ceiling as two refusals. **`Meter` is UNUSED and now says so** — three comments and the recorded artifact claimed it enforced the ceiling on actuals. |
| `evals/check_opus_headroom.py` | **NEW.** The seat's "Opus must not reach throttle", as a measured pre-flight refusal. Wired into `make smoke` and `make evals` with `&&`. |
| `infra/core/observability.py` | Dashboard, 5 alarms, 2 janitor filters, X-Ray, nightly rule. `EvalStalenessAlarm` now BREACHES on missing data. |
| `src/ops/nightly.py` | Free nightly check; emits a staleness **sentinel** rather than nothing when no pass rate was ever recorded. |
| `loadtest/DEFERRED.md` | **NEW.** The three Done-when clauses with no disposition in writing, now with reasons. `locustfile.py` deleted. |

**Mutation harnesses:** `load_driver_guard_mutations` and
`disposition_guard_mutations`, five families each
(widen / remove / tier / sample-completeness / population / ordering). Two
survivors this session were real gaps — an idempotency case and a redundancy
that let a mutation hide — and both are closed.

---

## The rulings taken 2026-08-21

Recorded in `spec06-disposition-amendment.md` as **rulings with sources**, not
approvals (CLAUDE.md, ADR-0005).

1. **Item E — the fallback split ADOPTED.** A resolved-tier mismatch is a gate
   refusal; a fallback during a step is a search-backend failure, counted in
   the error rate, leaving the step dispositive with no latency sample from it.
2. **Item D — option 2.** Record the transport asymmetry and run.
3. **Item B — ratified**, with its direction corrected: it IS a strictness
   change against Tier B, in one region.
4. **Change 8 split out** into `spec06-nightly-amendment.md` — it amends
   Observability, not the disposition clause.
5. **Done-when: both `/query` profiles, the report artifacts and the chaos test
   DEFERRED**, reasons in `loadtest/DEFERRED.md`.
6. **Session ceiling $25**; `config.LOADTEST_BUDGET_USD` stays at the ruled $20.

**Both amendments are DRAFTS awaiting adoption.** If they are not adopted, the
deferrals have no authority and M06 does not close.

---

## What is left

1. **The window.** `make core`, `make up`, the disposition run, one
   `make smoke`, dashboard screenshot, `make down`. Priced at **≈$0.49** by
   `make tier-disposition-price` plus the smoke run; ceiling $20 in code, $25
   for the session.
2. **The nightly verification artifact** — `pm-spec-reviewer` blocker B8. One
   free read-only invocation of `NightlyCheckFn`, recorded as
   `milestones/M06/nightly-verification.json`. Owed before the nightly
   amendment is acted on.
3. **Re-run `security-reviewer` and `eng-code-reviewer`** on this session's
   fix commits before the PR. Both reviews found defects in what the previous
   review's fixes introduced, so a third pass over the third pass is not
   ceremony.

---

## Traps, so the next session does not re-learn them

- **A heredoc is not a literal.** Three separate edits to the mutation
  harnesses were written as `bash <<'PY'` with `\n` inside generated string
  literals, and all three produced a file with real newlines inside quotes —
  fourteen syntax errors each time. The working rule says write scripts to a
  file; it exists for this. Anchors are now read out of the source and
  `repr`'d, so a reflowed line cannot silently turn a mutation into
  NOT-APPLIED.
- **`make` exits 2 for any nonzero recipe status.** The six exit codes do not
  survive it; read `disposition.verdict` from the artifact.
- **A NOT-APPLIED mutation is a guard nobody checked** wearing the word
  "killed" in the previous run's JSON. Anchors are now read out of the source
  and `repr`'d rather than retyped, so a reflowed line fails loudly.
- **A MUTATION HARNESS MAKES THE WORKING TREE UNSTABLE FOR THE LENGTH OF ITS
  RUN, and `git add -A` is a snapshot of whatever instant it lands in.** One
  commit this session shipped two live mutations — the completeness gate
  disabled and the 1.7 MB log line back — because staging happened while a
  background harness had the file mutated. The harness restored correctly
  seconds later and every test was green in both directions, so nothing caught
  it but `git diff` against the tree afterwards. **Never stage while one is
  running.** The sidecar added this session protects the next HARNESS run from
  an interrupted one; nothing protects a concurrent `git add`.
- **Never run two harnesses over overlapping subject files at once.** Two
  driver-harness runs overlapped here and produced contradictory results for
  the same mutation — SURVIVED in one, KILLED when applied by hand — because
  each was restoring the other's edits.
- **A flaky test inside a mutation harness manufactures evidence.** A red run
  reads as "mutation killed", so a test that fails one time in five certifies
  a guard that may not exist. `test_mean_concurrency_*` was flaky for four
  runs in this session: it read a still-growing integral and compared two
  reads microseconds apart. Fixed by reading it with nothing in flight. Its
  replacement was ALSO wrong once — it asserted `mean(0.05) <= 1.0` after a
  `sleep(0.05)`, and `sleep` sleeps longer than asked, so the honest answer is
  1.01. A test whose premise is false is the same defect as a comment whose
  claim is false.
- **Redundant defences hide mutations.** Two places excluded fallen-back calls
  from the latency population, so deleting either one survived. One place now.
- **Piping a harness into `tail` masks its exit code** — done once this
  session, on the run that had a survivor.
- `q03` stays failing, `q12`/`q15` stay deferred, and
  `milestones/M05/negation_scope_false_passes.py` remains the acceptance bar
  for any future attempt. **Not M06's work.**
