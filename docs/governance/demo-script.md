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

<!-- PREMISE CORRECTED 2026-08-22, under the Door 1 ruling at
     milestones/M07/spec07-door1-amendment.md rather than as a new ruling.

     The adopted text opened "unit is red on q03". That was true when the
     amendment was written and M07 ITSELF made it false: the admitted-false-fail
     register turned q03 green the same milestone. Filming it would have
     reproduced the precise defect the amendment exists to remove — a caption
     its own screen contradicts.

     The replacement premise is live and was filmed: PR #20, where the token
     addition made q12 pass and ruling-cited refused the merge anyway. Evidence
     in milestones/M07/doors/. Only the premise sentence changed; the SHOW and
     LINE blocks the PM seat adopted are untouched. -->

## Door 1 — Engineer tries to fix ground truth directly (2 min)

As engineering: `golden-set` reports q12 failing on its accept group. Do the
obvious thing — the model's answer contains the words "a fair reading", so add
`"fair reading"` to the group. One token, one line, green build. Push, open the
PR.

(It is also the exact false pass the SME seat closed hours earlier: the answer
reads "No, that was **not** a fair reading", and `"fair reading"` is a substring
of it. That is what makes it a realistic thing for an engineer to do rather than
a strawman.)

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
Show docs/governance/ROLES.md and the PR timeline of all three doors.

LINE: "Accountability isn't a slide, and it isn't a signature either — there
is one person here and no seat I don't control. It's a required check that
demands a document I cannot write inside the pull request it's blocking. Go
read the ruling; if it's wrong, you can prove it's wrong."

<!-- RULED 2026-08-22, lead+PM seats
     (milestones/M07/roles-amendment-draft.md). The do-not-film marker that
     stood here is lifted.

     The original Close read: "Accountability isn't a slide. It's CODEOWNERS, a
     required check, and a review seat you don't control." Two of those three
     were false. CODEOWNERS routes a review request and does not require one —
     required_approving_review_count is 0 and require_code_owner_review is
     false on the live ruleset — and there is no review seat the one human here
     does not control, which is what Door 1 above now says out loud. Only "a
     required check" survived, and it is doing all of the work.

     The replacement claims less and can be checked: a required check that
     demands a document which cannot be written inside the pull request it
     blocks. docs/governance/ROLES.md line 4 and flow 1 were corrected in the
     same ruling. -->
