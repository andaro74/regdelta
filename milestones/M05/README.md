# M05 — Deploy + Lifecycle

Branch `m05-deploy-lifecycle`, cut from `m04-api-demo` at `8ac6c37`, rebased
onto `main` after PR #11 merged. Live window run 2026-08-20.

**Status: NOT closed.** Four of SPEC/05's four items are built and measured
live. The Done-when's `make evals` green criterion is **pending an SME ruling
on q03** (below), and I am not recording the milestone as done on a
"green-modulo-a-known-false-fail" argument.

---

## What SPEC/05 asked for, and where it stands

| # | Item | State |
|---|---|---|
| 1 | State-table split: query role reads/writes `THREAD#*`, writes but never reads `REVIEW#*` | built, probed live (`leadingkeys_probe.py`), deployed |
| 2 | Dedicated CFN role so the janitor deletes via PassRole | built, **deleted the real stack live** |
| 3 | `aoss:APIAccessAll` scoped to the collection ARN | built, moved to the ephemeral stack, deployed |
| 4 | Hydration gate — `make up` fails if count-parity fails | built, **passed and refused live** |

Security tightening: Bedrock scoped to exact model ARNs (M04), `aoss:APIAccessAll`
pinned to `collection.attr_arn`, AOSS data-access policy split write/read.

---

## Item 4 — the hydration gate (the M02 deferral)

`milestones/M02/README.md:591` deferred this here: the SSM endpoint parameter
was written by CloudFormation, which knows a collection exists and knows
nothing about whether an index was filled. Confirmed as an artifact rather than
an argument — `EndpointParam` had **no `DependsOn` at all** in the synthesized
template.

The consequence M02 named: on a stack UPDATE, a Trigger failure rolls the
Lambda's environment back but **not** the AOSS index contents, and the
parameter from the previous successful deploy survives. `router.active_endpoint()`
reads only that parameter, so retrieval routes to a knowingly-short index and
answers **with citations**. Neither the resolved-tier assertion nor the
date-attribution preflight looks at completeness.

**The fix, in three parts.**

- **Inside.** `reindex.handler` deletes the parameter *before* `_create_index`
  (which DELETEs the index as its opening move) and republishes it only after
  count-parity **and** `_assert_knn_mapping` have both returned. It reads
  `config.SSM_SEARCH_ENDPOINT` — the same constant the router reads — rather
  than spelling the name a fourth time.
- **Template.** `EndpointParam` is created before the Trigger, which now
  `DependsOn` it (otherwise CloudFormation's create lands on a name the Lambda
  just published → `ParameterAlreadyExists`). CloudFormation still **owns** the
  parameter, which is what makes `cdk destroy` and the janitor return retrieval
  to S3 Vectors.
- **Outside.** `make up` gates on `evals/check_hydration.py`, which reads the
  index and **never the deploy's exit code**. The gate runs either way — the
  deploy's status is captured, not chained with `&&` — so a deploy that exits 0
  over an index nobody hydrated is still refused.

### Live evidence

`make up`, cycle 1, from the ReindexFn log group:

```json
{"endpoint_retired": true, "parameter": "/regdelta/search/endpoint"}
{"bulk_complete": 1157, "awaiting_count": 1157}
{"index_visible_after_s": 0.2}
{"source": 1157, "sent": 1157, "indexed": 1157, "dropped": 0,
 "index": "chunks", "endpoint_published": "/regdelta/search/endpoint",
 "endpoint_retired": true}
```

`endpoint_retired: true` means CloudFormation had created the parameter and
hydration **took it away**, then gave it back after both assertions. Older log
groups in the same account show the identical run shape with no endpoint
fields — the before/after is visible side by side.

Gate verdict, both cycles: `1157 chunks indexed, 1157 in the corpus,
embedding=knn_vector`.

**The refusal is exercised too**, at $0 with the tier down:

```
REFUSED  the hot tier is not usable:
  [endpoint] /regdelta/search/endpoint is absent, so retrieval routes to
  S3 Vectors and the hot tier is not up. …
```
exit 1, having read 1157 corpus records in the same pass.

### Two CloudFormation premises, run rather than assumed

`orphan_param_probe.py` ($0, reproducible, tears down on failure). Both had to
hold or the design was worse than the bug it fixes:

- **`DeleteStack` succeeds when the parameter is already gone.** Had it failed,
  a failed hydration would strand the stack in `DELETE_FAILED` — `make down`
  and the janitor both blocked, a collection billing ~$0.24/hr until a human
  noticed. Trading a silent wrong answer for an unbounded bill is not a fix.
- **An UPDATE that does not change the parameter does not re-create it**, and
  the update demonstrably ran (a second, unrelated resource reached
  `CREATE_COMPLETE` in the same update). Had it re-created it, a redeploy would
  republish the endpoint without re-running hydration and the gate would leak.

---

## The blocker both reviewers found independently

`security-reviewer` and `eng-code-reviewer` ran on the branch diff, from
different starting points, and reported the same HIGH finding.

Moving `aoss:APIAccessAll` into the ephemeral stack (`from_role_arn(...,
mutable=True)`) puts an `AWS::IAM::Policy` in `regdelta-search` whose `Roles:`
list resolves — through `Fn::Select`/`Fn::Split`/`Fn::ImportValue` over core's
export — to `regdelta-core-QueryFnServiceRole…`. Deleting it calls
`iam:DeleteRolePolicy` against **that** role, and the deletion role was scoped
to `role/regdelta-search-*`. It does not match.

`DeleteStack(RoleARN=search_deleter)` would take AccessDenied and land in
`DELETE_FAILED` with the collection still billing — the exact shape the role
exists to prevent, on the only path with no human watching. And because
`DELETE_FAILED` had just been added to the deletable set, the janitor would
have retried that AccessDenied **nightly, forever**.

**It would not have shown up in the Done-when.** `make down` is `cdk destroy`
under the bootstrap AdministratorAccess role and succeeds every time. Nor could
this milestone's own janitor probe have caught it: an inert stack holding one
SSM parameter has no cross-stack policy in it by construction. That probe was
written to close a "reasoned, not run" gap and had one of its own, one level up.

Fixed with `iam:DeleteRolePolicy` + `GetRolePolicy` on the query role's ARN.
**Not** `iam:PutRolePolicy` — the review offered it for update-rollback, but
this role is only ever handed to `DeleteStack`, and the pre-existing
`test_the_deletion_role_cannot_create_anything` correctly refused to let an
unattended role attach arbitrary inline policies to the internet-facing query
role. That test caught the over-grant on the first attempt.

The new test asserts the **property, not the prefix**: synthesize both stacks
in one app as `infra/app.py` does, find every role the search stack attaches a
policy to but does not own, resolve each through core's Outputs, and require
the deletion role to reach it.

### Confirmed live

The janitor was invoked against the real stack. `QueryLambdaRolePolicyC151784C
→ DELETE_COMPLETE` at `15:24:50.897Z`. **Zero `DELETE_FAILED` events.** Stack
`DELETE_COMPLETE` at `15:25:25.931Z`, collection gone at `15:25:19.887Z`.

Janitor return values, both branches:

```json
{"status": "delete-requested", "was": "UPDATE_ROLLBACK_COMPLETE",
 "billing_stopped": false, "retry_of_failed": false, "role_arn": "…SearchStackDeletionRole…"}
{"status": "already-down", "billing_stopped": true}
```

`billing_stopped` is false for the request and true only for the invocation
that **observed** absence — ADR-0013, and one structured line printed per run
because EventBridge discards return values.

---

## Teardown verified five ways

| check | result |
|---|---|
| `list-collections` | `[]` |
| `/regdelta/search/endpoint` | `ParameterNotFound` |
| CloudFormation stack | does not exist (not `DELETE_FAILED`) |
| live API `/health` | `{"status":"ok","tier":"s3vectors"}` |
| IAM roles `regdelta-search*` | `[]` |

---

## Three premises refuted by running

This milestone spent its measurement budget on things that were written down as
true and were not.

1. **"The M04 janitor does not work at all"** (M04 README:860) — reasoned,
   never run, and false. Probed at $0 against an inert stack: it deleted, and
   the resource went with it. CloudFormation reuses a stack's associated role
   and does not re-check `iam:PassRole`. So the RoleARN change is a
   **narrowing**, not a repair.
2. **"A failed hydration leaves the endpoint absent."** Written into
   `make fault-drop` and refuted by the live run. On an UPDATE of a healthy
   stack the deploy *does* fail — and CloudFormation then rolls the Trigger
   back, and CDK re-invokes the **previous Lambda version**, which has no
   `REINDEX_FAULT_DROP`. Observed: version `:2` failed, version `:1` was
   invoked, and the gate found `1157/1157` with a live endpoint. The gate was
   right; my assertion was wrong. A failed update does not merely fail safe, it
   **self-repairs to the last known-good index** — a stronger property than the
   one the target was written to demonstrate. `fault-drop` now asserts a
   *forbidden state* (an endpoint naming a short index) rather than an expected
   outcome.
3. **"`reindex` leaves retrieval on the tier that still works" on every failure
   path.** True of the parameter, not of its readers — see open thread 1.

---

## The window

| step | outcome |
|---|---|
| `make core` | deletion-role fix live, verified against IAM |
| `make up` #1 | gate passed, 1157/1157 |
| `evals` (AOSS run 1) | 16/20 |
| `make down` | verified, OCU 14:43:49→15:00:20Z |
| `evals` (S3 Vectors) | 17/20 |
| `make up` #2 | gate passed, 1157/1157, **new collection id** |
| `evals` (AOSS run 2) | **18/20** — the stable baseline |
| `make fault-drop` | deploy failed; rollback self-repaired (premise 2) |
| janitor teardown | stack + collection deleted by the restricted role |

**OCU: 34.7 minutes across two cycles ≈ $0.14**, plus Bedrock for three full
golden runs. Under the $0.60–0.75 estimate.

The new collection id on cycle 2 (`uul5zj…` → `0wn5tm…`) is live confirmation
of why the AOSS grant had to move to the ephemeral stack: the ARN it is scoped
to does not exist until `make up` creates it.

---

## q03 — an SME ruling is owed, and CI is red until it lands

The AOSS run 1 card recorded q03 failing on `forbidden text present: 'TTB
requires'`. `sme-eval-triage` classified it **(c) BAD QUESTION — defective
check**, not a system regression, with falsifiable evidence:

- The banned literal occurs only inside *"I cannot confirm … whether TTB
  requires …"*. `evals/run_evals.py:447-449` is a bare case-folded substring
  test with no notion of negation scope.
- The 2026-08-19 passing answer and the 2026-08-20 failing one share paragraph
  1 **verbatim**, with identical `status: pending_review`, `confidence: 0.3`,
  `review_reason`, and citation list. The only difference is the paraphrase of
  the hedge.
- The answer attaches **zero** citations to the TTB row and explicitly declines
  — it does not commit the error the ban exists to catch.
- Corpus drift ruled out: the S3 Vectors card carries `documents_sha:
  35a293e17117`, 52 documents — **identical to the 2026-08-19 baseline**. The
  cited stay document `91 FR 50475` was already in the corpus on 08-19 (it
  appears in the *passing* card), and FR full-text shows nothing published in
  this subject since.
- Code drift ruled out: `git diff 1fa942a..1f46b92 -- src/graph/nodes.py` is 45
  lines, all additive stopReason instrumentation, none touching the prompt,
  retrieval, or answer construction.

Three observations of q03 today: **FAIL** (aoss run 1), **FAIL** (s3vectors),
**PASS** (aoss run 2). Non-deterministic at `temperature: 0`.

**`replay_history` independently flagged it**, by a completely different
mechanism: `!! q03 … 1fa942a:agent=PASS 1f46b92:agent=FAIL 1f46b92:agent=PASS`
— a genuine PASS→FAIL, which is what FRAGILE means. FRAGILE gates by design
("if this ever fails, a real FRAGILE finding appeared — which is the point"),
and there is deliberately no admit path for it. So
`tests/test_replay_exit_codes.py` is red on a **true** finding.

I have not touched `evals/golden_questions.json` and will not.

**The recommendation is explicitly not a token edit.** Narrowing `"TTB
requires"` reopens the false pass the 2026-08-12 ruling closed, and the q03
note already predicted this exact failure in the mirror direction ("a ban
cannot help, because 'you must file a new formula' is reproduced by the correct
hedge"). The proposed lever is **negation-scope awareness in the scorer** —
`run_evals.py`, not the golden set, so no CODEOWNERS gate — but it changes
scoring semantics for every banned token and needs an SME ruling plus
engineering review, with `make discrimination` replaying both a hedge specimen
and a bare-assertion specimen before adoption.

**A second finding, present in the *passing* 08-19 answer too:** both runs open
with *"you mention this likely refers to the Alcohol and Tobacco Tax and Trade
Bureau (TTB)"* — but the 2026-08-12 ruling deliberately removed TTB from the
stem so the answer could not echo it. The system attributes to the asker
something they did not say. No token catches it, it is not the regression, and
on an honesty-subset question it deserves its own ruling.

q01 failed run 1 on `HTTP Error 503` (`cache: "unreachable"`, never reached the
API) and passed run 2. Transport, not scoring.

---

## Open threads

1. **The router's 60s endpoint cache outlives the retire.** `reindex.py`
   claimed "every failure path leaves retrieval on the tier that still works".
   True of the parameter, not of its readers: a warm query container keeps the
   memoised endpoint for up to `_TTL = 60`s, so once `_bulk` starts landing
   batches it can see a **partial** index and answer with citations. Bounded at
   ~60s per hydration. Fixes on the table — a hydration sentinel the tier
   checks, or a doc-count floor in `aoss_tier` — are retrieval-path design, not
   deploy lifecycle. Raised by `security-reviewer`; the comment now states the
   residual instead of the stronger claim.
2. **`stop_reason` is recorded and nothing routes on it.** `_needs_review`
   never consults it; a truncated verdict reaches `pending_review` only
   incidentally via `_confidence({}) == 0.0`, and the reviewer is told
   "confidence 0.00" rather than "the model was cut off". Wiring it changes
   review routing, which is SPEC/03 exit-criteria and sits behind the PM ruling
   still owed on `fail-declined`.
3. **`run_retrieval.py` and `run_demo_parity.py` still overwrite at one sha.**
   The M04 thread named the golden set; giving retrieval cards a trail means
   deciding what a parity *pair* means when one half was re-run — a question
   about the gate, not about recording. Noted in the file so it does not read
   as handled.
4. **The deletion role's trust policy has no `aws:SourceAccount`/`SourceArn`
   condition.** One line of standard confused-deputy scoping, deliberately not
   applied hours before a live teardown that exercises exactly that role.
5. **The `aoss:*` control-plane grant is `Resource: "*"`.** The old rationale
   ("these actions do not accept resource ARNs at all") is untrue of
   `DeleteCollection`/`BatchGetCollection`. The honest statement — now in the
   source — is that this role can delete the policies of any collection in the
   account. Tightening needs collection tagging plus an `aws:ResourceTag`
   condition.
6. **M04 threads 1 and 2 remain parked** behind the PM ruling on whether a
   `fail-declined` should block a milestone.

---

## Instruments that lied, and were caught

ADR-0013 says an instrument reads the field that describes its own claim. Six
instances this milestone, every one caught by running rather than reading:

1. A template test filtered `AWS::IAM::Policy.Roles` on a full ARN; the field
   carries role **names**. Reported the grant missing while the template held it.
2. A state-table test filtered on `dynamodb:` alone and so reported on the
   registry table's unconditioned grant — three assertions about the wrong table.
3. `test_the_expected_mapping_is_read_off_the_one_the_stack_ships` asserted
   `EXPECTED_EMBEDDING_TYPE == INDEX_MAPPING[…]`, which is `"knn_vector" ==
   "knn_vector"` whether the guard derived it or spelled it. It **survived**
   mutation C6. It now mutates the shipped mapping and re-imports.
4. The `record()` supersession fixture monkeypatched the archive location as
   well as `HISTORY`, overriding the sibling-vs-subdirectory choice its own
   test claimed to check — mutation D2 survived until the constant was derived
   from `HISTORY` at call time.
5. `check_mapping` let `AossError` escape, so an unreachable AOSS would end
   `make up` in a traceback instead of the refusal report. Three tests raised
   straight through that line.
6. **`stop_reason` never left the graph.** `nodes.verdict` recorded it; the
   first live golden run came back with `stop_reason: null` on all twenty
   questions, because `_shape` is an **allowlist** and nobody added the field.
   Third time for that function — `dropped_citations` and `retrieval_ms` were
   both lost the same way, and both notes sit beside it in the source. Fixed in
   both shapes, and the shim/API parity test now compares **key sets** against a
   named exclusion list rather than two fields by name.

And one in the evidence-gathering itself: the AOSS run-1 card was recorded
without the environment resolved, so it carries `corpus: {"available": false}`.
The corpus fingerprint exists precisely to answer "did the corpus move under
us?", and it was missing from the one card where q03 first failed. `make evals`
and `make smoke` now resolve the environment the way the other targets do.

---

## Artifacts

| file | what |
|---|---|
| `orphan_param_probe.py` | the two CloudFormation premises the gate rests on |
| `leadingkeys_probe.py`, `perprefix_probe.py` | the state-table policy, chosen and rejected designs |
| `janitor-probe.json` | inert stack for the $0 janitor probe |
| `hydration_gate_mutations.py` + `.json` | 14 mutations, no survivors |
| `m04_thread_mutations.py` + `.json` | 7 mutations, no survivors |
| `deletion_role_mutations.py` + `.json` | 2 mutations, no survivors |
| `evals/history/1f46b92-aoss-full.json` | AOSS run 2, 18/20, with `supersedes` trail |
| `evals/history/superseded/1f46b92-aoss-full.run1.json` | AOSS run 1, 16/20, kept |
| `evals/history/1f46b92-s3vectors-full.json` | S3 Vectors, 17/20 |

Full suite at close: see the final commit. Lint clean.
