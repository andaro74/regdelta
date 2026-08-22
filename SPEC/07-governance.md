# SPEC/07 — M07: Governance Layer ("one change, three doors")

Item 5 and the second Done-when clause were added 2026-08-21 by PM-seat ruling
(`milestones/M07/q03-rulings.md` §B) and rewritten the same day after
`pm-spec-reviewer` returned **request changes** on the first draft. Its findings
and what was done about each are in
`milestones/M07/spec07-pm-review.md`; two of them were defects in the mechanism
rather than in this text.

## Goal
The separation-of-roles demo is executable end-to-end on GitHub. See
docs/governance/ROLES.md, ADR-0003.

## Build / configure
1. GitHub: teams or seat accounts per docs/governance/branch-protection.md;
   branch protection with CODEOWNERS review + eval-gate required check;
   Actions variables (EVAL_GATE_ENABLED, STAGING_API_URL, AWS_EVAL_ROLE_ARN).
2. AWS: regdelta-ci-eval OIDC role (trust = this repo; permissions = read the
   registry table for the corpus fingerprint, and nothing else) — add to
   infra/core as a construct. **The staging API is unauthenticated and needs no
   grant at all**, which is stated rather than left as an apparent omission: a
   reader who expects an invoke permission and finds none should learn why from
   this line.

   *Amended 2026-08-21 by PM-seat ruling. The original clause read "permissions
   = invoke staging API only", which is not implementable — `apigw.HttpApi` is
   created with no authorizer and `run_evals.ask()` sends an unsigned POST, so
   there is nothing to grant and a role satisfying it literally would hold an
   empty policy. Reasoning and the ruling in
   `milestones/M07/spec07-oidc-amendment.md`.*
3. Stage Door 3: branch `demo/door3-iam-widening` containing a plausible
   diff that widens an IAM policy to resources:["*"] amid a real fix.
4. Verify all four subagents run clean against representative diffs.
5. **The admitted-false-fail register.**

   `evals/replay_history.py` decides whether a recorded answer blocks a merge,
   and had no owning SPEC. It acquires one here rather than in SPEC/05,
   because what blocks a merge and on whose authority is this milestone's
   subject — the same claim SPEC/07 makes about CODEOWNERS and the eval gate.

   **The product claim, which is what this item is for:** *a merge gate may be
   overridden only per named observation, only by a seat ruling a reader can
   open, and never invisibly.*

   Concretely: a register records recorded answers the SME seat has
   individually examined and ruled false fails. An entry names one artifact —
   question, sha, a digest of the exact text the scorer scores, and the failure
   reasons it admits, **all four matched exactly** — plus a reference to the
   seat ruling that created it, **which must resolve to a document in the tree
   for the entry to be usable at all**. An entry may only subtract a failure
   from an answer that is already failing.

   This is an override list and therefore a reduction in assurance; ADR-0015
   records it as one.

   *Item 5 was implemented before this item was written; what M07 owes is the
   demonstration, not the build.* The file names, the flag spelling and the
   invocation shape are engineering's and may change without reopening this
   clause — the properties below may not.

   **What must hold, and what M07 must show is true:**

   - the register does not touch `evals/golden_questions.json` (SME-owned) and
     does not touch the scorer, so a plain evals run still scores an admitted
     answer as failing and the live scorecard still says so;
   - a paraphrase of an admitted answer is **not** admitted, so FRAGILE stays
     live on new non-determinism;
   - an admitted answer that starts failing for a different or additional
     reason is **not** admitted;
   - an entry whose ruling reference is absent or does not resolve **does not
     admit anything and fails the run**;
   - every admission is reported on every run with its ruling reference, and an
     admitted answer is reported as admitted, never as passing;
   - an entry matching a recorded answer that no longer fails as ruled **fails
     the run**, so the register cannot accumulate dead overrides. An entry
     whose question has no recorded answer in the run at all is reported as
     unevaluated and does **not** gate, because a subset run produces the
     identical condition — that exemption is a hole and ADR-0015 records it as
     one;
   - the unadmitted state is reachable by a flag and is recorded in the
     evidence.

## Out of scope
SSO/RBAC in the app itself; multi-tenant auth (named as roadmap, not built).

Out of scope for item 5: fixing q03's underlying scorer defect
(`make discrimination` keeps reporting it via the `LIMIT_FALSE_FAIL`
specimen); any per-rule or class-wide admit path into FRAGILE, which M05 §11
refused and which stays refused; redesigning q03; and any effect on
`make evals` or the live scorecard.

**M07 adds exactly one entry — q03 at `1f46b92`, the observation the SME seat
examined (`milestones/M07/q03-rulings.md` §A.4: "one entry … is what the
measurement covers, and I would not open it wider"). A second entry is a new
seat ruling, not an application of this one.**

## Done when
Recorded run-through of docs/governance/demo-script.md exists in
milestones/M07/: Door 1 PR shows `ground-truth-gate / ruling-cited`
**failing**, with the gate's own message naming the SME seat, and the merge
blocked with **no bypass available to the repository owner** — the ruleset's
`bypass_actors` is empty at the time of the screenshot, and the screenshot is
accompanied by the ruleset JSON showing it; Door 2 PR shows triage table + the
ruling landed as its own PR + `ruling-cited` green + eval-gate comment +
merge; Door 3 PR shows the HIGH security finding and required security seat.
All three PR URLs listed in the journal.

<!-- The Door 1 and Door 2 clauses were replaced 2026-08-22 by PM-seat ruling
     (milestones/M07/spec07-door1-amendment.md, ruling at the foot). The
     original read "Door 1 PR shows the blocked-merge screenshot", which is
     satisfiable by a screenshot whose caption nothing can falsify — the trap
     this milestone opened by finding in milestones/M07/baseline/. The ruling
     records the consequence it accepted: this clause is downstream of the
     admin bypass coming off, which is downstream of the new required checks
     going green. If it cannot be filmed, the clause is NOT MET and M07 does
     not close on it. It is not to be softened afterwards to fit. -->

**And, for item 5** *(added 2026-08-21)*:

1. Each of the properties in item 5 is named in the evidence pack **beside the
   exercise that establishes it**. A property with no exercise beside it is not
   met.
2. The refusal set is authored to **break** the register, not to describe it,
   and includes at least: a changed sha, a changed question, a one-character
   digest change, an extra failure reason, a different failure reason, an empty
   reason list, an entry with no ruling reference, an entry citing a document
   not in the tree, an entry whose question has no recorded cards, an unruled
   entry beside a ruled one, and an absent register file.
3. Every refusal is **run**, and the survivor count is recorded **and equal to
   zero**. Any survivor blocks the milestone.
4. `python evals/replay_history.py --no-admissions` is recorded in
   `milestones/M07/` alongside the run that gates green, so the unadmitted
   state is in the evidence pack and not only the admitted one.

<!-- Criterion 2 enumerates the set rather than saying "every refusal" because
     "every" is not a set anyone can check, and because the first version of
     the refusal set was written by the mechanism's own author with the
     mechanism in hand — the 2026-08-15 failure mode, named twice already in
     milestones/M05/q03-ruling.md §10. The list above is falsifiable by someone
     who has never opened admission_mutations.py, and two of its entries are
     cases that set originally missed. pm-spec-reviewer, M07 finding 8. -->
