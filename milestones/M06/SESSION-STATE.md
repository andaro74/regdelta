# M06 — session state, 2026-08-20

Written at the end of the first M06 session so the next one starts from a
record rather than from a re-derivation. **Nothing is deployed. Nothing has
been spent.** Every AWS call this session made was read-only: Service Quotas,
CloudWatch metrics, Cost Explorer, DynamoDB reads, and one `logs:TestMetricFilter`.

Branch `m06-load-and-observability`, cut from `m05-deploy-lifecycle` at
`f1de2a3` (**not** from `main`; PR #12 is untouched and `main` is untouched).
Head **`65c15e4`**, four commits, 29 files, +4541/-66. Working tree clean.

Suite: **1044 passed, 1 skipped, 3 failed** — the three failures are the known
`test_replay_exit_codes` q03 FRAGILE gate, red by the seat's M05 decision.
Lint clean across `src evals infra tests loadtest`.

---

## The two findings that shaped the milestone

### 1. SPEC/06's Tier B disposition clause cannot be executed in this account

`L-ED2BADF9` caps Claude Opus 4.6 at **2,592,000 tokens/day** and reports
`Adjustable: false`. One uncached `/query` costs **5,881.8 Opus tokens**
(CloudWatch `AWS/Bedrock`, 60 golden calls of the M05 window), so the cap is
**440 queries/day for everything this account does**.

At SPEC/06's 500-concurrent-user profile the cap is gone **13.6 s** into the
first of six required runs. Six five-minute holds are **324,688,133 tokens —
125× the cap — $2,629**.

And the profile does not measure what the clause names: retrieval is 2.6–5.8%
of an uncached request, so 500 closed-loop users deliver **11.4 (Tier A) /
25.8 (Tier B)** concurrent retrieval calls, not 500.

`milestones/M06/spec06-disposition-amendment.md` is the proposal. **DRAFT v3,
not adopted.** Two `pm-spec-reviewer` passes returned 10 then 13 blockers; all
23 are dispositioned inline, six of them arithmetic that did not re-derive.

### 2. LangGraph silently drops undeclared state keys

`nodes.verdict` returned `stop_reason` and `truncated`; `RegDeltaState`
declared neither, so M05's fix could never have worked. **This closes M05 open
thread 9** — not "we have not looked" but "it cannot work". Found by compiling
a two-node graph offline, for $0.

Fixed, and generalised into `tests/test_graph_state_declares_node_outputs.py`.

---

## What is built

| area | state |
|---|---|
| `shared/observability.py` | EMF + X-Ray subsegment over the daemon UDP socket. **No new runtime dependency.** |
| `graph/instrument.py` | Per-node span policy. Every `RegDeltaState` key has an explicit disposition; five are `SECRET` and never logged. |
| `graph/graph.py` | All seven nodes wrapped. |
| Token capture | `supervisor_usage` / `verdict_usage`, one key per model-calling node. |
| `api.py` | Request-level `QueryLatency` / `Queries` by cache status and verdict status. |
| `infra/core/observability.py` | Dashboard `regdelta`, 5 alarms, 2 janitor metric filters, X-Ray tracing, nightly rule. |
| `src/ops/nightly.py` | Free nightly check — graph logic, tier, corpus, eval staleness. **Verified live: 52 docs, 3/3 dated, $0.** |
| `src/ops/retrieval_load.py` | The open-loop step driver. Tested, not yet deployed. |
| `loadtest/budget.py` | The seat's **$20 ceiling**, as two refusals: dollars, and non-adjustable daily caps. |
| `shared/corpus.py` | One fingerprint definition; both callers agree and match the M05 card. |
| `shared/util.py` | `retry` now counts throttles — the exclusion SPEC/06 states was unenforceable without it. |

**Mutation harnesses, all clean:** `state_declaration_mutations` 6/6,
`budget_guard_mutations` 11/11. `janitor_filter_probe` puts six real janitor
outputs through `logs:TestMetricFilter` — all six match as intended.

---

## Decisions the human seat made this session

1. **Observability in full; the `/query` load profiles (100- and 500-user) are
   DEFERRED**, quota as the stated reason.
2. **The 28-cent Tier B disposition measurement IS wanted.**
3. **Hard ceiling of $20 on any load test.** Now `config.LOADTEST_BUDGET_USD`,
   enforced by `loadtest/budget.py`, pinned by a test, mutation-checked.
4. **The nightly job must be free** — hence no golden questions in it.

Consequence: **`locust` is no longer needed.** No new dependency has been added
at any point this milestone.

---

## What is left, in order

1. **Deploy surface for the driver.** `LoadDriverFn` in `regdelta-core`;
   `infra/app.py` passes its role ARN to the search stack; `search_stack.py`
   adds it to `index_readers` (the AOSS data-access policy — the driver cannot
   read the index without it). This is an infra/IAM diff → **security-reviewer**.
2. **`loadtest/retrieval_load.py`** — the orchestrator that walks the
   pre-registered schedule (10/25/50/75/90 calls/s × 60 s), invokes the driver
   per step per tier, and writes
   `loadtest/reports/tier-disposition-<sha>.json` with the verdict.
3. **`make tier-disposition`** — exits non-zero on a dirty sha, mismatched
   corpus fingerprints across halves, a resolved tier that disagrees with the
   half it was recorded under, or no qualifying dispositive step.
4. **Amendment v4** — add the `/query` deferral and the nightly-set
   interpretation as named changes, then **re-run `pm-spec-reviewer`** and take
   the seat's ruling.
5. **`security-reviewer`** on the infra/IAM diff, **`eng-code-reviewer`** on the
   whole branch. Note for the reviewer: `WILDCARD_EXEMPT` in
   `tests/test_query_fn_iam.py` is a new, pinned, two-action X-Ray exemption to
   an existing security rule, recorded as **documented-not-measured** because
   this repo asserted the same "no resource ARNs" claim about `aoss` at M05 and
   it was false.
6. **The window** — `make core`, `make up`, the disposition run, one
   `make smoke` (~$0.24) to populate the dashboard, dashboard screenshot,
   `make down`. Budget **≈ $0.55**; ceiling $20.

**The disposition run is BLOCKED until step 1 lands**, and the amendment says
so: SPEC/06 defines the measured interval as the one carried on the per-node
retrieval span, and the report must record the span emission status.

---

## Traps, so the next session does not re-learn them

- **A unit test of the driver reached the real retrieval path** and asked for
  50,000 calls/second. It hung, was killed, and `AWS/Bedrock` showed no Titan
  invocations, so nothing was spent — luck, not design. Both fixtures in
  `tests/test_retrieval_load_driver.py` are now `autouse`, and one of them fails
  any test that constructs a boto3 client. **Keep it that way.**
- **The driver over-reported its own rate by 14%** at small n, because it
  divided by the gap between first and last dispatch rather than the window it
  held. That made a well-behaved step *ineligible*.
- **`DocTimeline` has no `dates` attribute.** The nightly check asked for one
  through `getattr(..., default)` and would have reported every document
  undated, nightly, forever.
- **Two corpus fingerprints of the same 52 documents** differed by one
  separator. One definition now, in `shared/corpus.py`.
- `q03` stays failing, `q12`/`q15` stay deferred, and
  `milestones/M05/negation_scope_false_passes.py` remains the acceptance bar
  for any future attempt. **Not M06's work.**
