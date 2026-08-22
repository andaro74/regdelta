# M07 baseline — what the governance layer actually was on 2026-08-21

Captured on branch `m07-governance` at `8be904a`, **before any M07 change**.
Every claim below is a file in this directory, re-readable without trusting
this summary.

The reason this capture exists: SPEC/07's Done-when is a recorded run-through
of `docs/governance/demo-script.md`, and one of its three doors describes a
GitHub state that does not exist. Recording the before-state is what makes the
after-state a change rather than an assertion.

---

## 1. The ruleset (`ruleset-20392406.json`)

```
ruleset 20392406 "Branch Protection"   enforcement: active
  conditions            include refs/heads/main
  rules                 deletion · non_fast_forward · pull_request · required_status_checks
  required_status_checks           [{"context": "unit"}]
  required_approving_review_count  0
  require_code_owner_review        false
  require_last_push_approval       false
  bypass_actors                    [RepositoryRole 5 (admin), bypass_mode "always"]
  current_user_can_bypass          "always"
```

This is ADR-0005's configuration, unchanged since it was written, plus one
later edit (`updated_at: 2026-08-21T14:09`).

## 2. What Door 1 claims, and what GitHub would say

`docs/governance/demo-script.md` Door 1:

> SHOW: merge blocked — "Review required from code owners (@regdelta-sme)".

With `required_approving_review_count: 0` and `require_code_owner_review:
false`, GitHub emits no such message. There is exactly one thing that can
block a PR to `main` today: the `unit` status check.

And `unit` is red — **by seat decision**, not by accident.

## 3. `unit` is red, and has been since M05 (`pytest.txt`, `replay-history.txt`)

```
3 failed, 1187 passed, 1 skipped
FAILED tests/test_replay_exit_codes.py::test_the_repo_as_it_stands_does_not_fail_ci
FAILED tests/test_replay_exit_codes.py::test_admitted_findings_are_reported_but_do_not_gate
FAILED tests/test_replay_exit_codes.py::test_it_runs_with_no_aws_environment_at_all
```

All three are downstream of one finding in `python evals/replay_history.py`
(exit 1):

```
FRAGILE  q03: agent answers disagree across runs —
         … 1fa942a=PASS 1f46b92=FAIL 1f46b92=PASS 95235d9=PASS 95235d9=PASS
         1f46b92 failed on: forbidden text present: 'TTB requires'
```

That is the M05 q03 false fail, left visible on purpose
(`milestones/M05/q03-ruling.md` §11, option 3). It is a real finding about a
real non-determinism, and the seat chose one honest red check over a weakened
detector.

**The consequence for M07:** filming Door 1 in this state captures a red test
suite and captions it as an org chart. `workflow-runs.json` shows every
eval-gate run since 2026-08-20 concluding `failure`; the last `success` was
M04's `m04-api-demo`. PR #14 read `mergeStateStatus: BLOCKED` for this reason
and was merged from the admin seat anyway, which the `bypass_mode: "always"`
above is what permitted.

So the milestone's first problem is not a config chore. Three separate things
have to be true before Door 1's screenshot means what its caption says, and
only one of them is a ruleset field.

## 4. Seats (`collaborators.json`, `repo.json`, `.github/CODEOWNERS`)

```
collaborators   ["andaro74"]          (one)
visibility      PUBLIC
isFork          false
owner           andaro74 (User, not an Organization)
```

`.github/CODEOWNERS` maps every path to `@andaro74` and says so in its own
header: all five `@regdelta-*` placeholders 404'd, and `@org/team` syntax needs
an org this repo does not have (ADR-0005).

A code-owner review requirement is therefore **unsatisfiable today** for any
path: GitHub does not let an author approve their own PR, and the only code
owner is the only author. Turning `require_code_owner_review` on without first
adding a second collaborator reproduces PR #1's deadlock exactly.

## 5. Actions configuration (`actions-variables.json`, `actions-secrets.json`)

```
variables   EVAL_GATE_ENABLED = "false"   (set 2026-08-04, reset 2026-08-08)
secrets     0
absent      STAGING_API_URL · AWS_EVAL_ROLE_ARN
```

`.github/workflows/evals.yml` has two jobs. `unit` runs. `golden-set` is
skipped on every run by `if: vars.EVAL_GATE_ENABLED == 'true'` and has never
executed a single step.

**A false claim is being posted on PRs.** The scorecard comment `golden-set`
would post ends:

> _Ground truth owned by @regdelta-sme (CODEOWNERS). A failing gate blocks
> merge by branch protection._

Neither half holds. `@regdelta-sme` does not exist and CODEOWNERS maps ground
truth to `@andaro74`; and `golden-set` is not among the required status
checks, so a failing gate blocks nothing. ADR-0005 owed the restoration of
`golden-set` to required checks *at M04* — "as `golden-set` and not `eval-gate
/ golden-set`, and probed rather than assumed" — and recorded that "nothing
enforces the restoration, which depends on a human remembering and is the
weakest link in this ADR." It was not remembered at M04, M05 or M06. This is
that ADR's own predicted failure, observed.

## 6. Four defects found while reading, all of which would fire the first time
   the gate ran

Recorded here because they were found in the before-state, not introduced by
M07.

1. **The gate would run in the wrong region.** `golden-set` pins
   `aws-region: us-east-1`. The stack is `us-west-2`
   (`ApiUrl: https://<api-id>.execute-api.us-west-2.amazonaws.com/api`), and
   `run_evals.resolve_api_url` falls back to `boto3.client("cloudformation")`
   with no region.
2. **Every posted scorecard would be corpus-blind.** `corpus_fingerprint()`
   delegates to `shared.corpus.fingerprint`, which returns
   `{"available": false, "reason": "REGISTRY_TABLE unset"}` when that env var
   is missing. No workflow variable supplies it. That is precisely the defect
   M05 recorded against itself — the AOSS run-1 card carried
   `corpus: {"available": false}` and it was the one card where q03 first
   failed.
3. **SPEC/07's OIDC role is not implementable as specified.** SPEC/07 item 2
   says "permissions = invoke staging API only". There is nothing to grant:
   `infra/core/core_stack.py:532` creates an `apigw.HttpApi` with no
   authorizer, and `run_evals.ask()` sends an unsigned `urllib` POST. The
   role's only genuine need is read access for the corpus fingerprint
   (`dynamodb:Scan` on the registry table). Amending the spec is a PM-seat
   call.
4. **The declined permissions guard was declined for a reason that is false.**
   `evals.yml` declines a test asserting each job holds only the permissions
   its steps need, because "PyYAML is not transitive from boto3, langgraph,
   fastapi, starlette, mangum or ruff, so it would have had to become a
   dependency." It is transitive: `langgraph → langchain-core →
   pyyaml<7.0.0,>=5.3.0`, resolved to 6.0.3 and installed by
   `requirements-dev.txt` in CI today. The same comment sets a reversal
   condition — add the guard "in the same change that flips the flag" — so M07
   is where it lands, at no dependency cost.

## 7. Cost baseline

`/regdelta/search/endpoint` is `ParameterNotFound`, so the hot tier is down and
retrieval routes to S3 Vectors. **M07 needs no `make up`**, and it should not
want one: a merge gate that depends on an ephemeral tier is a gate that fails
whenever the tier is down.

Per-run Bedrock cost could not be derived from Cost Explorer — this account
carries unrelated workloads (Claude Opus 4.6 at $8.40 on 2026-08-19, plus
SageMaker, RDS, VPC and a non-AOSS OpenSearch domain), so daily service totals
do not isolate RegDelta. The usable anchor is the application's own
`RegDelta/BedrockCostUsd` metric, which began emitting at M06:

| hour (UTC) | Opus 4.6 | Sonnet 4.6 | total | what ran |
|---|---|---|---|---|
| 2026-08-21T17:00 | $0.1760 | $0.0036 | **$0.180** | golden runs |
| 2026-08-21T23:00 | $0.9287 | $0.0259 | $0.955 | M06 load test |

$0.180 for a 20-question run is consistent with M05's three full golden runs
landing under its $0.60–0.75 estimate. M07 budgets 4–6 runs: **$0.80–$1.40,
ceiling $1.50, zero OCU.**

---

## Files

| file | what |
|---|---|
| `ruleset-20392406.json` | the live ruleset, unedited API response |
| `actions-variables.json`, `actions-secrets.json` | one variable, zero secrets |
| `collaborators.json`, `repo.json` | one collaborator; public; personal repo |
| `pytest.txt` | 3 failed, 1187 passed — the `unit` redness |
| `replay-history.txt` | the q03 FRAGILE finding those three tests read |
| `workflow-runs.json` | every eval-gate run failing since 2026-08-20 |

## Redaction, and a warning about repeating this capture

**The `execute-api` hostname is redacted above** (`security-reviewer`, M07, HIGH).
That host reaches the API directly, bypassing CloudFront and everything attached
to it; the API has no authorizer and `/query` spends a Bedrock call per request.
The rate limit (`rate_limit=20, burst_limit=40`) bounds requests per second, not
dollars. The endpoint being unauthenticated is a pre-existing accepted risk
(SPEC/04, and `spec07-oidc-amendment.md` records it as an open security-seat
question); **publishing its address on a public repo is not**, because obscurity
was the whole of the control. The sentence above is making a point about region,
and loses nothing to the redaction.

**Do not re-run the capture verbatim at M07 close.**
`gh api /repos/.../actions/variables` returns variable **values**, not just
names — unlike the secrets endpoint, which returns names only, which is why
`actions-secrets.json` is safe by construction. Today the only variable is
`EVAL_GATE_ENABLED=false` and nothing leaks. Once `AWS_EVAL_ROLE_ARN` and
`STAGING_API_URL` are populated, the same command writes the AWS account id and
the API host into this public repo. Redact both, or capture names only.
