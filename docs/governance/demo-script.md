# The Governance Demo — "One change, three doors" (8-10 min)

Setup: RegDelta deployed; branch protection on; the three seats exist.
Premise on screen: "FDA amends the rule — q01's expected answer must
change. Watch the org chart, encoded in the repo, decide what happens."

## Door 1 — Engineer tries to fix ground truth directly (2 min)
As @regdelta-eng: edit evals/golden_questions.json, push branch, open PR.
SHOW: merge blocked — "Review required from code owners (@regdelta-sme)".
LINE: "Engineering literally cannot define what 'correct' means. That's
not a policy document — it's the merge button."

## Door 2 — The right path (3 min)
In Claude Code: invoke sme-eval-triage on the failing question. SHOW its
triage table: class = WORLD CHANGED, FR citation, proposed diff, required
approver. Approve as the SME seat; PM approves the spec touch; eval-gate
posts the scorecard comment; merge succeeds.
LINE: "Same change, minutes later — with a complete audit trail of who
decided, who verified, and which commit."

## Door 3 — The scary one (3 min)
As @regdelta-eng: a branch where an IAM policy 'helpfully' widened to
resources:["*"] while fixing something else (stage this diff in advance).
Invoke security-reviewer on the diff → HIGH finding, file:line. PR shows
security approval required; the diff dies in review.
LINE: "The engineer owns every line the AI wrote — and the system is
built assuming some of those lines will be wrong."

## Close (1 min)
Show docs/governance/ROLES.md table + the PR timeline of all three doors.
"Accountability isn't a slide. It's CODEOWNERS, a required check, and a
review seat you don't control."
