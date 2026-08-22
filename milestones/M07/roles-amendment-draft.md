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
