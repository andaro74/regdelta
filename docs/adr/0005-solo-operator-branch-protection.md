# ADR-0005: Branch protection reflects one human, not a simulated org

- Status: accepted
- Date: 2026-08-07
- Milestone: M02 (pre-work)
- Amends: ADR-0003 (governance-as-code)

## Context
ADR-0003 encoded the org chart in repo mechanics: CODEOWNERS maps files to
role seats, and branch protection requires code-owner review plus the
eval-gate status check. That configuration deadlocked at the first real
merge. PR #1 (M01) sat `BLOCKED` with no reachable path to green, for two
independent reasons:

1. **The review requirement was unsatisfiable.** The ruleset required one
   approving review with `require_code_owner_review: true` and no bypass
   actors. GitHub does not let an author approve their own PR, and this
   repo has exactly one collaborator. Worse, all five `@regdelta-*` owner
   handles returned 404 — they were placeholders the scaffold's own comment
   said to replace, and the replacement never happened. This is a personal
   repo, not an org, so `@org/team` syntax could not have resolved either.
   **CODEOWNERS was enforcing none of the boundaries it appeared to.**

2. **`eval-gate / golden-set` was a required check that cannot pass.** The
   job is `if: vars.EVAL_GATE_ENABLED == 'true'`, deliberately off until the
   staging API exists at M04 (see `68ccbd3`). It reports `SKIPPED`, and a
   skipped check does **not** satisfy a required status check — verified
   empirically: with the review requirement removed, PR #1 remained
   `BLOCKED` on this alone.

Both are the same failure: a gate whose passing condition no one had
checked was reachable. Asserting a control and never exercising it is the
exact failure mode this product exists to catch in regulatory text.

## Decision
Configure protection to what a single-human repo can actually honor.

**Kept (still real):** PR required for `main` (no direct pushes), required
status check `eval-gate / unit` (ruff + pytest), block force-push, block
deletion, no bypass actors.

**Dropped:** `required_approving_review_count` → 0;
`require_code_owner_review` → false; `eval-gate / golden-set` removed from
required checks **until M04**, when the staging API and OIDC role exist and
the job can actually run.

**CODEOWNERS is retained as a routing map, not a gate**, with owners mapped
to `@andaro74` so the file is at least valid. The seat names now say which
role subagent must review a path and which PR-template checklist item
carries the attestation. `/evals/` was added (SPEC/02 prerequisite C, open
since M00b finding 5) so `run_evals.py` has an owner of record.

## Alternatives considered
- **Second account to play the SME/security seats.** Keeps the mechanism
  mechanically real, but GitHub's ToS allows one free personal account per
  human (machine accounts are the carve-out), and it is still the same
  person clicking approve. Ceremony, not accountability.
- **Add self as bypass actor, leave the rules as written.** Unblocks with
  the smallest diff, but leaves a config that claims a review gate while
  documenting its own circumvention. Strictly worse than saying so plainly.
- **Move the repo to an org with real teams.** The honest fix, and the right
  one if a second human ever joins. Not justified for one person.

## Consequences
+ Merges are possible, so the eval gate that *does* work can start gating.
+ The claim made to a reader is now true. Enforcement is the role-subagent
  pass plus the eval gate — which is what actually caught M01's
  merge-blocking prompt-injection HIGH. The GitHub approval button caught
  nothing, because it was never reachable.
- Role separation is no longer mechanically enforced. It rests on the
  subagent reviews and the PR checklist, both of which the author can skip.
  **This is a real reduction in assurance and should be stated as one** —
  ADR-0003's "every accountability claim is showable as a blocked or
  approved PR" no longer holds for the review dimension.
- `eval-gate / golden-set` must be restored to required checks at M04.
  Tracked as an M04 exit item; nothing enforces the restoration.

## Note for anyone reading this repo as a work sample
The interesting artifact here is not the final config. It is that the
governance scaffold was wrong in a way that was invisible until exercised,
and that both defects were found by trying to merge rather than by reading
the policy. A gate is a hypothesis until something fails against it.
