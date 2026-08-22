# Branch protection setup (5 minutes, cannot live in the repo itself)

GitHub → Settings → Branches → Add rule for `main`:
- [x] Require a pull request before merging
- [x] Require approvals (1)
- [x] Require review from Code Owners        ← activates CODEOWNERS
- [x] Require status checks to pass — **by BARE JOB NAME**:
      - `unit`
      - `golden-set`             (after setting EVAL_GATE_ENABLED=true)

      NOT `eval-gate / unit`. That is the UI's display format — workflow name,
      slash, job name — and it is a rendering, not a context. A required check
      written that way matches nothing and sits pending forever, which
      deadlocked PR #1 for four days. Isolated with a single-variable A/B/A in
      PR #4: same commit, same passing check, only the context string changed,
      and the verdict flipped with it. ADR-0005.
- [x] Do not allow bypassing the above (include administrators)

Repo → Settings → Secrets and variables → Actions:

| name | kind | value |
|---|---|---|
| `EVAL_GATE_ENABLED` | variable | `true` (after M04: staging API exists) |
| `REGISTRY_TABLE` | variable | `regdelta-core` `RegistryTableName` output |
| `STAGING_API_URL` | **secret** | `regdelta-core` `ApiUrl` output |
| `AWS_EVAL_ROLE_ARN` | **secret** | `regdelta-core` `CiEvalRoleArn` output |

## What a `vars` value does and does not hide on a public repo

Nothing. This is the note `.github/workflows/evals.yml` points at, written
after `security-reviewer` was asked the question directly at M07.

**Actions variables are not masked in logs.** A `with:` input is echoed into the
step log *before* the action runs, so `configure-aws-credentials`'s
`mask-aws-account-id` cannot help — masking is registered by the action, after
the echo. An `env:` block is logged the same way. On a public repo those logs
are world-readable.

- **`AWS_EVAL_ROLE_ARN` is a secret**, because the ARN carries the AWS account
  id. It costs nothing to move: a fork PR cannot use the role either way — it
  cannot mint an OIDC token at all — so nothing working changes, and owner runs
  gain masking. The ARN is not itself a credential; the trust policy is the
  control. This is defence in depth, not the gate.
- **`STAGING_API_URL` is a secret, and this one matters most.** It names an API
  with **no authorizer**, where every `/query` spends a Bedrock call. The
  `execute-api` hostname reaches it directly, bypassing CloudFront and
  everything attached to it, and the API's rate limit bounds requests per
  second rather than dollars. The endpoint being unauthenticated is a
  pre-existing accepted risk (SPEC/04); publishing its address is not, because
  obscurity is the whole of the control. `security-reviewer` M07, HIGH.
- **`REGISTRY_TABLE` stays a variable.** A table name, on a table nothing
  reaches from the internet, and it is useful to see in a log.

Also: `gh api /repos/OWNER/REPO/actions/variables` returns variable **values**,
not just names — unlike the secrets endpoint, which returns names only. Do not
commit that response to this repo once these are populated.

The role's permissions are **read the registry table for the corpus
fingerprint, and nothing else** — see SPEC/07 item 2 as amended, and
`milestones/M07/spec07-oidc-amendment.md`. The staging API needs no grant at
all because it is unauthenticated, which is stated rather than left looking
like an omission.

Teams (org) or collaborator accounts:
- regdelta-pm, regdelta-sme, regdelta-security, regdelta-lead, regdelta-eng
Solo mode: map all to yourself, or create 2 extra free accounts for the
SME and Security seats — the demo's Door 1 and Door 3 need at least one
seat you don't control from your main account.
