# DRAFT — PM ruling owed: Door 1 becomes a check, not a review

<!-- DRAFT, written in the engineering seat for the PM seat. Nothing in
     docs/governance/demo-script.md or SPEC/07's Done-when has been changed.
     The replacement text below is complete, so the ruling can be "adopt",
     "adopt with amendments", or "reject" rather than a request for more
     drafting. -->

**Status: awaiting the PM seat. `demo-script.md` and SPEC/07's Done-when are
unchanged.**

## What is being asked

Door 1 of `docs/governance/demo-script.md` says:

> SHOW: merge blocked — "Review required from code owners (@regdelta-sme)".

GitHub does not emit that message on this repository and cannot be made to
without a second account. The mechanism M07 built instead is a required status
check. **The demo script and SPEC/07's Done-when both need to say so, or the
milestone's evidence will be captioned with a claim its own screenshot
contradicts.**

## Why the second account was not the answer

It was the recommended option earlier in this session, and that was wrong.
ADR-0005 had already considered and rejected it, in these words:

> **Second account to play the SME/security seats.** Keeps the mechanism
> mechanically real, but GitHub's ToS allows one free personal account per human
> (machine accounts are the carve-out), and it is still the same person clicking
> approve. **Ceremony, not accountability.**

Its 2026-08-08 extension goes further and is the governing text here:

> **The signature is theater. The seat is not.** … An SME-seat ruling is sound
> when it cites primary sources inline so a reader can falsify it without
> trusting the author — not when someone signs it.

So Door 1 as scripted re-stages the exact fiction ADR-0005 removed. The demo
script predates that extension and was never reconciled with it.

## What the check does that a review could not

`ground-truth-gate / ruling-cited`. A pull request touching
`evals/golden_questions.json`, `evals/admitted_false_fails.json` or
`evals/scenarios.json` fails unless it cites a ruling that **(1) is already on
`main`** and **(2) names the file it rules on**.

| | code-owner review | required check |
|---|---|---|
| binds the repository owner | no — author cannot approve, so it deadlocks | **yes**, measured below |
| satisfiable from inside the PR it blocks | n/a | **no** |
| what it demands | a signature | **a document a reader can open** |
| needs a second identity | yes | **no** |

**Measured, not assumed** (`milestones/M07/bypass-probe.txt`). The repo's own
history is why this was run: ADR-0005 records a required check that matched
nothing and sat pending forever, and a root cause that was called "verified
empirically" and was wrong.

```
BEFORE   bypass_actors: [RepositoryRole 5 (admin), "always"]
         current_user_can_bypass: 'always'
AFTER    bypass_actors: []
         current_user_can_bypass: 'never'
         the four rules survived the update: True
RESTORED verified field by field, rules included
```

What that establishes is narrow and should be said narrowly: **GitHub reports
the owner as no longer able to bypass.** Whether a merge is then actually
refused is settled only by a real blocked pull request — which is Door 1
itself, and is the reason to film it rather than to describe it.

## Proposed replacement — `docs/governance/demo-script.md`, Door 1

> ## Door 1 — Engineer tries to fix ground truth directly (2 min)
>
> As engineering: `unit` is red on q03. Do the obvious thing — edit
> `evals/golden_questions.json` to drop the token that is failing. Push, open
> the PR.
>
> SHOW: `ground-truth-gate / ruling-cited` fails, and says why in its own
> words:
>
> ```
> This pull request changes what CORRECT means:
>   evals/golden_questions.json
>
> BLOCKED: no ruling cited.
>   Engineering may not decide what correct means (ROLES.md, CLAUDE.md).
>   Route the question through sme-eval-triage and land the ruling first,
>   in its own pull request.
> ```
>
> SHOW: the merge button, blocked, with no bypass offered — the admin bypass
> was removed, and the repository owner is subject to the rule like anyone
> else.
>
> LINE: "Engineering literally cannot define what 'correct' means. And notice
> what is doing the work — it is not that someone else has to approve, because
> there *is* no one else. It is that the repo demands a ruling that does not
> exist yet, and I cannot write it in this pull request. The gate asks for
> evidence, not a signature."

**Why the replacement is not weaker.** The original caption describes an
approval nobody would give and a seat nobody occupies. This one describes a
refusal that happens, to the person who owns the repository, for a reason a
viewer can reproduce in thirty seconds. It also matches what this project
claims about AI-assisted work generally: the control is a checkable artifact,
not an assertion of who reviewed what.

## Consequential change to Door 2

Door 2 is "the right path", and the right path is now specific: the ruling
lands in **its own pull request**, then the change cites it.

> In Claude Code: invoke `sme-eval-triage` on the failing question. SHOW its
> triage table: class, FR citation, proposed diff, required approver. Land the
> ruling as its own PR — it touches no SME-owned path, so the gate passes
> trivially. Then the change, carrying `RULING: <path>` on its commit. SHOW
> `ruling-cited` going green and naming the document; the eval gate posts its
> scorecard; merge succeeds.
>
> LINE: "Same change, minutes later — with an audit trail of who decided, on
> what evidence, and which commit. Two pull requests, because the decision and
> the code are two different acts."

Door 3 is unaffected: its substance is `security-reviewer` returning a HIGH
with file:line, which needs no second identity.

## Proposed change to SPEC/07's Done-when

Replace *"Door 1 PR shows the blocked-merge screenshot"* with:

> Door 1 PR shows `ground-truth-gate / ruling-cited` **failing**, with the
> gate's own message naming the SME seat, and the merge blocked with **no
> bypass available to the repository owner**. The ruleset's `bypass_actors` is
> empty at the time of the screenshot, and the screenshot is accompanied by the
> ruleset JSON showing it.

The last sentence is the part that matters: a screenshot of a blocked merge
proves nothing about *why* it was blocked, and this milestone began by finding
exactly that trap — a red `unit` check being captioned as an org chart.

## Also owed, and not proposed here

`docs/governance/ROLES.md` still says CODEOWNERS + branch protection enforce
the boundaries. After M07 that is true of `ground-truth-gate` and false of
CODEOWNERS, which remains a routing map (ADR-0005). ROLES.md is lead+PM
co-owned and its correction is a separate, smaller ruling. Raised rather than
folded in.

## What the PM seat is asked to rule

1. Adopt the Door 1 replacement, adopt with amendments, or reject?
2. Adopt the Door 2 consequential change?
3. Adopt the Done-when replacement, including the requirement that the ruleset
   JSON accompany the screenshot?
