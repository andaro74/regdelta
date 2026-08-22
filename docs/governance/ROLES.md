# RegDelta — Roles, Ownership, Accountability

<!-- Line 4 and flow 1 were replaced 2026-08-22 by lead+PM ruling
     (milestones/M07/roles-amendment-draft.md). The originals said the roles
     were "enforced by CODEOWNERS + branch protection" and that the SME
     approves ground-truth changes "via CODEOWNERS". Measured on the live
     ruleset: required_approving_review_count is 0 and
     require_code_owner_review is false. CODEOWNERS routes; it does not
     enforce. -->

The org chart is encoded in the repo. Each role owns different files and a
different TRUTH. **What is mechanically enforced is narrower than the table
below, and the difference is deliberate rather than an aspiration:**

- **Ground truth is enforced.** A pull request touching an SME-owned eval path
  fails `ground-truth-gate / ruling-cited` unless it cites a ruling already on
  `main` that names the file it changes. It binds the repository owner and
  cannot be satisfied from inside the pull request it blocks. The admin bypass
  was removed on 2026-08-22 (`milestones/M07/bypass-removed.txt`).
- **Regressions are enforced.** `unit` and `golden-set` are required checks. A
  golden question that has ever passed and now fails blocks the merge; one that
  has never passed is reported on every scorecard and does not gate
  (`milestones/M07/eval-gate-bar-ruling.md`).
- **Everything else is routed, not enforced.** CODEOWNERS requests a reviewer;
  `require_code_owner_review` is `false` and required approvals are `0`. There
  is one human here, so a review requirement would deadlock rather than enforce
  (ADR-0005).
- **What makes a seat's decision sound is a ruling citing primary sources a
  reader can falsify — not a signature.** The seats below are real as
  *responsibilities* and as *routing for the subagents*; only the bullets above
  are real as merge-button constraints.

| Role (team) | Owns the truth about | Owned artifacts | May not do |
|---|---|---|---|
| Product (@regdelta-pm) | WHAT to build & when it's acceptable | SPEC/**, milestones/** | Define correctness of answers; merge code |
| Compliance SME (@regdelta-sme) | What CORRECT means | evals/golden_questions.json, regulatory-domain skill; staffs the HITL queue | Write product code; weaken trap questions to green a build |
| Engineering (@regdelta-eng) | That it WORKS | src/** | Self-approve ground truth, specs, or tool policy |
| Tech lead (@regdelta-lead) | HOW we build | CLAUDE.md, docs/adr/**, interface seams (router.py) | Bypass security or SME gates |
| Security (@regdelta-security) | What tooling & infra MAY DO | .claude/settings.json, .claude/agents/security-reviewer.md, infra/**, .github/workflows/** | Define product scope |
| Legal (advisory gate) | What we may USE and SAY | DATA_SOURCES.md, verdict disclaimer wording | Day-to-day merges (category sign-off, not per-PR) |

## The prime rule of AI-assisted engineering
The engineer owns every line Claude Code produced as if they typed it.
"The AI wrote it" is never an accepted root cause. Review of generated
diffs is mandatory and stricter than human review (trust-then-verify gap).

## Accountability flows for the three recurring events
1. **Eval failure** → `sme-eval-triage` subagent classifies (regression /
   world changed / bad question) → the SME seat issues a **ruling that cites
   primary sources**, and lands it as its own pull request → only then may the
   ground-truth change cite it and merge. Engineering never edits golden
   answers unilaterally, and `ruling-cited` is what makes that a refusal rather
   than a norm. Run for real on 2026-08-22: the ruling landed in PR #17 and the
   change cited it in PR #18.
2. **Infra/IAM change** → security-reviewer subagent on the diff →
   @regdelta-security approval required → merge.
3. **Spec change** → pm-spec-reviewer subagent → @regdelta-pm approval →
   only then does implementation start.

## Solo-operator mode (demo reality)
One person plays all roles honestly by: separate GitHub accounts (or
teams mapped to yourself), the PR template checklist, and NEVER skipping
a subagent review even when you'll approve your own PR. The audit trail
still demonstrates the mechanism — that is the demo.
