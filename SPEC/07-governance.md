# SPEC/07 — M07: Governance Layer ("one change, three doors")

## Goal
The separation-of-roles demo is executable end-to-end on GitHub. See
docs/governance/ROLES.md, ADR-0003.

## Build / configure
1. GitHub: teams or seat accounts per docs/governance/branch-protection.md;
   branch protection with CODEOWNERS review + eval-gate required check;
   Actions variables (EVAL_GATE_ENABLED, STAGING_API_URL, AWS_EVAL_ROLE_ARN).
2. AWS: regdelta-ci-eval OIDC role (trust = this repo; permissions =
   invoke staging API only) — add to infra/core as a construct.
3. Stage Door 3: branch `demo/door3-iam-widening` containing a plausible
   diff that widens an IAM policy to resources:["*"] amid a real fix.
4. Verify all four subagents run clean against representative diffs.

## Out of scope
SSO/RBAC in the app itself; multi-tenant auth (named as roadmap, not built).

## Done when
Recorded run-through of docs/governance/demo-script.md exists in
milestones/M07/: Door 1 PR shows the blocked-merge screenshot; Door 2 PR
shows triage table + SME approval + eval-gate comment + merge; Door 3 PR
shows the HIGH security finding and required security seat. All three PR
URLs listed in the journal.
