# DRAFT — lead + PM seats: what actually enforces the role boundaries

<!-- DRAFT, written in the engineering seat for the lead and PM seats, which
     co-own docs/governance/ROLES.md. NOTHING in ROLES.md or demo-script.md has
     been changed. Complete replacement text below, so the ruling can be adopt /
     adopt with amendments / reject rather than a request for more drafting.
     Raised by spec07-door1-amendment.md and deliberately not folded into it. -->

**Status: awaiting the lead and PM seats.**

## What is wrong

`docs/governance/ROLES.md` line 4 says the roles are:

> (enforced by CODEOWNERS + branch protection)

and flow 1 says a human SME "approves any ground-truth change **via
CODEOWNERS**".

Neither is true, and one of them has never been true. Measured on the live
ruleset (`milestones/M07/baseline/ruleset-20392406.json`, and again in
`required-checks.txt`):

```
required_approving_review_count : 0        <-- no review is required at all
require_code_owner_review       : false    <-- CODEOWNERS is not wired in
```

CODEOWNERS on this repository is a **routing map**: it decides who gets
*requested*, not who must *approve*. ADR-0005 already ruled that, and ROLES.md
was never reconciled with it. And with one human here, a review requirement
would deadlock rather than enforce — which is the finding that produced Door 1's
rebuild.

A second sentence has the same defect and is in `demo-script.md`'s Close:

> "Accountability isn't a slide. It's CODEOWNERS, a required check, and a
> review seat you don't control."

There is no review seat anyone here does not control. That line now sits three
paragraphs below a Door 1 caption that says so explicitly, adopted by PM ruling
on 2026-08-22. Filming the Close as written would contradict the demo's own
Door 1 on camera.

## What IS enforced, as of M07

| boundary | enforced by | how a reader checks |
|---|---|---|
| ground truth (`evals/golden_questions.json`, `admitted_false_fails.json`, `scenarios.json`) | **`ground-truth-gate / ruling-cited`**, a required status check | open a PR touching one without a ruling on `main` |
| CI redness | **`unit`**, a required status check | `required-checks.txt` |
| `golden-set` | **required, but SKIPS and therefore does not gate** while `EVAL_GATE_ENABLED` is false or on a fork PR | `skipped-check.txt` |
| everything else in the table | **routing only** — CODEOWNERS requests a reviewer; nothing requires one | `require_code_owner_review: false` |

## Proposed replacement — ROLES.md, line 4

> The org chart is encoded in the repo. Each role owns different files and a
> different TRUTH. **What is mechanically enforced is narrower than this table,
> and the difference is deliberate rather than an aspiration:**
>
> - **Ground truth is enforced.** A pull request touching an SME-owned eval
>   path fails `ground-truth-gate / ruling-cited` unless it cites a ruling
>   already on `main` that names the file it changes. It binds the repository
>   owner and cannot be satisfied from inside the pull request it blocks.
> - **Everything else is routed, not enforced.** CODEOWNERS requests a
>   reviewer; `require_code_owner_review` is `false` and required approvals are
>   `0`. There is one human here, so a review requirement would deadlock rather
>   than enforce (ADR-0005).
> - **What makes a seat's decision sound is a ruling that cites primary sources
>   a reader can falsify — not a signature.** The seats below are real as
>   *responsibilities* and as *routing for the subagents*; only the row above is
>   real as a merge-button constraint.

## Proposed replacement — ROLES.md, flow 1

> 1. **Eval failure** → `sme-eval-triage` subagent classifies (regression /
>    world changed / bad question) → the SME seat issues a **ruling that cites
>    primary sources**, and lands it as its own pull request → only then may the
>    ground-truth change cite it and merge. Engineering never edits golden
>    answers unilaterally, and `ruling-cited` is what makes that a refusal
>    rather than a norm.

## Proposed replacement — demo-script.md, Close

> Show `docs/governance/ROLES.md` and the PR timeline of all three doors.
>
> LINE: "Accountability isn't a slide, and it isn't a signature either — there
> is one person here and no seat I don't control. It's a required check that
> demands a document I cannot write inside the pull request it's blocking. Go
> read the ruling; if it's wrong, you can prove it's wrong."

## What this does NOT propose

Removing the seats, the subagents, or CODEOWNERS. The routing rule is kept
because it works — CLAUDE.md records that stopping to route is what caught q08
and the fabricated compliance date. The change is to stop claiming CODEOWNERS
*enforces* what it *routes*.

## What the seats are asked to rule

1. Adopt the ROLES.md line-4 replacement?
2. Adopt the flow-1 replacement?
3. Adopt the demo-script.md Close replacement?

---

# LEAD + PM SEATS — RULING, 2026-08-22: ADOPT ALL THREE

**Status: ADOPTED.** `docs/governance/ROLES.md` line 4 and flow 1, and
`docs/governance/demo-script.md`'s Close, are changed to the replacement text
above. The do-not-film marker on the Close is lifted.

Ruling, with sources — not a signature. What makes this one sound is that every
claim it corrects is falsifiable against the live ruleset in one command:

```
$ gh api repos/andaro74/regdelta/rulesets/20392406
  required_approving_review_count : 0
  require_code_owner_review       : false
  bypass_actors                   : []
```

## 1. ROLES.md line 4 — ADOPTED

"Enforced by CODEOWNERS + branch protection" has never been true of this
repository, and ADR-0005 had already ruled that CODEOWNERS is a routing map.
The table was never reconciled with it. The replacement separates what is
*enforced* from what is *owned*, and says so in that order, because a reader
who takes the table as a description of the merge button will be wrong about
every row except the SME one.

## 2. Flow 1 — ADOPTED

"Human SME approves any ground-truth change via CODEOWNERS" describes an
approval that cannot be given: the author cannot approve their own pull
request, and there is no second account. The replacement describes what the
repository actually does, and it is not hypothetical — it ran twice on the day
of this ruling. PR #17 landed `q12-token-ruling.md`; PR #18 changed
`evals/golden_questions.json` and was accepted because that ruling was already
on `main` and named the file.

## 3. demo-script.md Close — ADOPTED

Of "CODEOWNERS, a required check, and a review seat you don't control", two
were false and one was carrying the whole claim. Filming it as written would
have contradicted Door 1 on camera, three paragraphs later, in the same video.

The replacement is weaker as a boast and stronger as evidence, which is the
trade this whole milestone makes: *"Go read the ruling; if it's wrong, you can
prove it's wrong."*

## What is deliberately NOT changed

The seats, the subagents and CODEOWNERS all stay. CLAUDE.md records that the
routing rule is kept **because it works** — stopping to route is what caught
q08 and the fabricated compliance date, and it is what caught the q12 false
pass on the day of this ruling. The correction is to stop claiming CODEOWNERS
*enforces* what it *routes*, not to stop routing.

## The one thing a reader should be suspicious of

This ruling was given by the same person who drafted it, in a repository with
one human — which is the exact condition ADR-0005 called "ceremony, not
accountability". It is not offered as an independent review and should not be
read as one. What is offered instead is the API output at the top: three
values, one command, and a claim that is wrong if they differ.
