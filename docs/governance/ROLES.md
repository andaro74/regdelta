# RegDelta — Roles, Ownership, Accountability

The org chart is encoded in the repo. Each role owns different files
(enforced by CODEOWNERS + branch protection), and each owns a different
TRUTH:

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
1. **Eval failure** → sme-eval-triage subagent classifies (regression /
   world changed / bad question) → human SME approves any ground-truth
   change via CODEOWNERS → engineering fixes regressions. Engineering
   never edits golden answers unilaterally.
2. **Infra/IAM change** → security-reviewer subagent on the diff →
   @regdelta-security approval required → merge.
3. **Spec change** → pm-spec-reviewer subagent → @regdelta-pm approval →
   only then does implementation start.

## Solo-operator mode (demo reality)
One person plays all roles honestly by: separate GitHub accounts (or
teams mapped to yourself), the PR template checklist, and NEVER skipping
a subagent review even when you'll approve your own PR. The audit trail
still demonstrates the mechanism — that is the demo.
