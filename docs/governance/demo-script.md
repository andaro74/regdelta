<!-- Doors 1 and 2 were replaced 2026-08-22 by PM-seat ruling
     (milestones/M07/spec07-door1-amendment.md). The originals scripted a
     code-owner review that GitHub does not emit on a single-human repository;
     ADR-0005's 2026-08-08 extension had already ruled that "the signature is
     theater, the seat is not". The mechanism is now a required status check.
     Door 3 is unchanged. See the note under Close. -->

# The Governance Demo — "One change, three doors" (8-10 min)

Setup: RegDelta deployed; branch protection on; the three seats exist.
Premise on screen: "FDA amends the rule — q01's expected answer must
change. Watch the org chart, encoded in the repo, decide what happens."

## Door 1 — Engineer tries to fix ground truth directly (2 min)

As engineering: `unit` is red on q03. Do the obvious thing — edit
`evals/golden_questions.json` to drop the token that is failing. Push, open
the PR.

SHOW: `ground-truth-gate / ruling-cited` fails, and says why in its own
words:

```
This pull request changes what CORRECT means:
  evals/golden_questions.json

BLOCKED: no ruling cited.
  Engineering may not decide what correct means (ROLES.md, CLAUDE.md).
  Route the question through sme-eval-triage and land the ruling first,
  in its own pull request.
```

SHOW: the merge button, blocked, with no bypass offered — the admin bypass
was removed, and the repository owner is subject to the rule like anyone
else.

LINE: "Engineering literally cannot define what 'correct' means. And notice
what is doing the work — it is not that someone else has to approve, because
there *is* no one else. It is that the repo demands a ruling that does not
exist yet, and I cannot write it in this pull request. The gate asks for
evidence, not a signature."

## Door 2 — The right path (3 min)

In Claude Code: invoke `sme-eval-triage` on the failing question. SHOW its
triage table: class, FR citation, proposed diff, required approver. Land the
ruling as its own PR — it touches no SME-owned path, so the gate passes
trivially. Then the change, carrying `RULING: <path>` on its commit. SHOW
`ruling-cited` going green and naming the document; the eval gate posts its
scorecard; merge succeeds.

LINE: "Same change, minutes later — with an audit trail of who decided, on
what evidence, and which commit. Two pull requests, because the decision and
the code are two different acts."

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

<!-- RAISED, NOT RULED ON (2026-08-22). This line still credits CODEOWNERS and
     "a review seat you don't control", which Door 1 above now explicitly says
     does not exist here. Same defect as docs/governance/ROLES.md's CODEOWNERS
     claim, and it belongs to the same lead+PM co-owned ruling — the Door 1
     amendment raised that one rather than folding it in, and this follows it.
     Do not film the Close with this caption until it is ruled on.
     Tracked in milestones/M07/README.md. -->
