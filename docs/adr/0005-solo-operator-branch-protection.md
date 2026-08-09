# ADR-0005: Governance reflects one human, not a simulated org

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

2. **Both required-check contexts were written in the UI display format and
   matched nothing.** The ruleset required `eval-gate / unit` and
   `eval-gate / golden-set`. GitHub Actions reports a check run named for the
   *job* (`unit`), carrying the workflow name in a separate field; the
   `workflow / job` string is a rendering, not the context. Neither required
   context ever resolved, so both sat pending forever and no PR to `main`
   could go green.

Both are the same failure: a gate whose passing condition no one had
checked was reachable. Asserting a control and never exercising it is the
exact failure mode this product exists to catch in regulatory text.

### Correction — the first version of this ADR named the wrong cause

As originally written, cause 2 said `golden-set` reported `SKIPPED`, that a
skipped check does not satisfy a required check, and that this was "verified
empirically." **That was wrong, and the verification claim was the worst part
of it** — the observation behind it (PR #1 still `BLOCKED` after the review
requirement was lifted) is equally explained by a context that never matched,
and nothing had been run to tell the two apart.

Isolated afterwards with a two-phase probe (PR #3) and a single-variable A/B/A
(PR #4), both closed unmerged and kept as evidence:

| context | `unit` conclusion | mergeStateStatus |
|---------|-------------------|------------------|
| `unit` | FAILURE (deliberate F401) | BLOCKED |
| `unit` | SUCCESS | **CLEAN** |
| `eval-gate / unit` | SUCCESS | **BLOCKED** (stable, 9 reads) |
| `unit` | SUCCESS (same commit) | **CLEAN** |

Same PR, same commit, same passing check — only the context string changed,
and the verdict flipped with it. So the display format is what deadlocked
PR #1. The `SKIPPED` conclusion was never shown to block anything, and the
`golden-set` removal was not what unblocked the merge.

Two consequences worth carrying:
- **Use the bare job name as the context.** `unit`, not `eval-gate / unit`.
  When `golden-set` is restored at M04 it must be `golden-set`, and it must
  be probed the same way rather than assumed.
- **Whether a `SKIPPED` required check blocks is still unknown here.** It was
  never isolated, and this record no longer claims otherwise. That question
  has to be answered at M04, when there is a job that can actually skip.

## Decision
Configure protection to what a single-human repo can actually honor.

**Kept (still real):** PR required for `main` (no direct pushes), required
status check **`unit`** (ruff + pytest — bare job name, see the correction
above), block force-push, block deletion, no bypass actors. Verified live by
PR #3/#4: a red lint blocks the merge, a green one clears it.

**Dropped:** `required_approving_review_count` → 0;
`require_code_owner_review` → false; `golden-set` removed from required
checks **until M04**, when the staging API and OIDC role exist and the job
can actually run.

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
- `golden-set` must be restored to required checks at M04, as `golden-set`
  and not `eval-gate / golden-set`, and probed rather than assumed. Tracked
  as an M04 exit item; nothing enforces the restoration, which depends on a
  human remembering and is the weakest link in this ADR.
- `unit` is restored and verified live, so this is no longer outstanding.

## Extension 2026-08-08: the same rule applies to the SME seat

This ADR fixed the *mechanical* gate and then the rest of the repo went on
claiming a *human* one. ADR-0006 and ADR-0007 shipped with
`Approved by: human SME sign-off`. Commit messages said rulings were "signed
off by the human SME". SPEC/02 says `retrieval_truth.json` is
"SME-countersigned". There is one person here. No second seat approved
anything, and writing as though one did is the same fiction this ADR exists to
remove — just relocated from branch protection to prose.

**The signature is theater. The seat is not.** What actually gave the SME
rulings their weight this session was never an approval:

- **Primary-source verification.** `sme-eval-triage` did not consult the repo
  to settle the fabricated compliance date — it pulled 89 FR 106064's DATES
  section from federalregister.gov. That check is re-runnable by anyone and
  would carry identical weight with zero humans agreeing.
- **The deferral, not the approval.** q08's defect was found at M00b close and
  recorded "drafted, not applied". Its value was that ground truth was *not*
  edited silently — it stayed visible for two milestones. Nobody approved
  anything; someone declined to act unilaterally.
- **The category switch.** Asking "is this settled by reading a chunk, or does
  it require knowing what the regulation means?" is a real distinction even
  when the same person answers both.

**Decision.** Wording across the repo changes from *approval* to *ruling with
citation*. An SME-seat ruling is sound when it cites primary sources inline so
a reader can falsify it without trusting the author — not when someone signs
it. ADR headers read `SME-seat ruling; primary sources cited inline; no second
approver exists (ADR-0005)`.

**Kept, because it demonstrably works:** the *routing* rule in CLAUDE.md —
engineering may not edit `evals/golden_questions.json` to make a failure pass,
and a ground-truth question stops and goes to the SME seat. That is a speed
bump against you-in-a-hurry at 11pm, and it is the mechanism that caught q08
and the fabricated date. It does not require a second person to work.

**Consequence for a reader of this repo as a work sample:** "I simulated three
roles and here is what each one caught, with primary sources" is defensible and
checkable. "Three roles approved this" invites the obvious question — who? —
and the honest answer undermines everything else on the page.

## Note for anyone reading this repo as a work sample
The interesting artifact here is not the final config. It is that the
governance scaffold was wrong in a way that was invisible until exercised,
and that both defects were found by trying to merge rather than by reading
the policy. A gate is a hypothesis until something fails against it.

The second-order lesson is sharper. The first version of this ADR explained
the deadlock with a plausible mechanism and called it "verified empirically"
on the strength of an observation that did not discriminate between two
candidate causes. It took a deliberately failing probe and a single-variable
A/B/A to find out which was real — and the answer was the other one. A
correct-sounding root cause in a decision record is itself an unverified
claim, and this project's whole premise is that those get checked.
