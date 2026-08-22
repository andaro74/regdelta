# M07 kickoff prompt

Paste everything below the line into a fresh Claude Code session.

---

Start M07 — SPEC/07, the governance layer ("one change, three doors"). This is
the last milestone.

**Read first, do not re-derive:** `SPEC/07-governance.md`,
`docs/governance/demo-script.md`, `docs/governance/ROLES.md`,
`docs/governance/branch-protection.md`, `docs/adr/0003-governance-as-code.md`
and `docs/adr/0005-solo-operator-branch-protection.md`. Work on branch
`m07-governance` cut from `main` (`8be904a`). The close tag is `m07`.

## Where the repo stands

M06 closed and merged (PR #14, merge commit `8be904a`, tag `m06`). Six of seven
milestones closed. Both retrieval tiers score 18/20 at `95235d9`, failing only
the deferred q12/q15.

**M05 is built, deployed and measured but never formally closed, and has no
tag.** Its own README refuses the close on the `make evals` criterion. Do not
quietly close it as part of M07 — see the q03 question below.

**Two M06 items are still with the human seat and may land during M07:**
`docs/adr/0014-tier-b-kept-and-bounded.md` is `status: proposed`, and the
"What broke / what I'd redo" section of `milestones/M06/README.md` is marked
DRAFT in an HTML comment.

## The finding that should shape this milestone

**Door 1, as `demo-script.md` scripts it, cannot happen today.** I measured the
live ruleset on 2026-08-22:

    ruleset 20392406 "Branch Protection", enforcement active
    required status checks    : ["unit"]
    required approvals        : 0
    require_code_owner_review : false
    bypass_actors             : [RepositoryRole 5 (admin), mode "always"]

The script says Door 1's screenshot shows *"Review required from code owners
(@regdelta-sme)"*. GitHub does not say that. With zero required approvals and
code-owner review off, what it says is that the **`unit` check failed** — and
`unit` is red *by seat decision* on the three q03 FRAGILE tests, and has been
since M05. PR #14 read `mergeStateStatus: BLOCKED` for exactly that reason and
was then merged from the admin seat anyway.

So filming Door 1 now would capture a red test suite and caption it as an org
chart. **Do not do that.** Making Door 1 real needs, at minimum: required
approvals ≥ 1, code-owner review on, a GitHub account holding a seat the admin
does not control, the admin always-bypass narrowed, and `unit` green — or the
q03 gate resolved — so the block has the *intended* cause.

Treat that as the milestone's first real problem, not a config chore.

## Current unset state

- Actions variables: `EVAL_GATE_ENABLED=false`; `STAGING_API_URL` and
  `AWS_EVAL_ROLE_ARN` do not exist.
- One workflow: `.github/workflows/evals.yml`.
- `.github/CODEOWNERS` maps every path to `@andaro74` and says so in its own
  header — all five `@regdelta-*` placeholders 404'd, and team syntax needs an
  org this repo does not have (ADR-0005).
- No `regdelta-ci-eval` OIDC role exists yet.

## Two things to put to me before you build anything

1. **Door 3 stages a deliberately insecure diff** — an IAM policy widened to
   `resources:["*"]` hidden inside a real fix — on a branch pushed to a
   **public** repo. It never merges, but it exists and is public. Ask me
   explicitly; do not infer authorisation from "start M07".
2. **Door 1 needs a second GitHub account** for a seat I do not control. That
   is an account creation, not a config change, and it is mine to do.

## The q03 question you will run into

`unit` is red because of q03, and that redness now blocks every PR and would
corrupt Door 1's evidence. M05's open thread 7 is the real fix: score q03
**structurally** — the defect is a TTB proposition carrying a Red No. 3
citation, and the failing answer's `answer_rows[1].citations` was `[]`, so it
is checkable without looking at wording. A substring attempt was already tried
and reverted for creating four false passes
(`milestones/M05/negation_scope_false_passes.py` is the acceptance bar: any new
rule must let zero of those four through).

That fix needs an SME ruling on the semantics and a PM ruling on which SPEC
owns it. **Both are mine.** Bring me the rulings; do not make them yourself,
and do not edit `evals/golden_questions.json` — the routing rule is kept
because stopping is what caught q08 and the fabricated compliance date.

## How I want you to work

- Ask before `make up` — OCU billing starts and `make down` is the only
  within-session brake. I do not expect this milestone needs the hot tier at
  all; say so if it does and price it first.
- One priced recommendation, not a menu. I usually reply "go ahead".
- Verify by running, not by reasoning. When you add a guard, run everything
  that guard can refuse (ADR-0013).
- Check exit codes directly; piping into `tail` masks them.
- Write scripts to a file, never a heredoc. Keep AWS calls as single plain
  commands. SSM and log-group paths with leading slashes need
  `MSYS_NO_PATHCONV=1`.
- `eval "$(python evals/local_env.py)"` before anything touching AWS.
- Run `security-reviewer` on any infra/IAM/workflow diff — M07 is almost
  entirely such diffs — and `eng-code-reviewer` before opening a PR.
- Merge PRs with a **merge commit, not a squash**: PR #13's squash orphaned
  `f651aea` and forced a preservation tag. Never delete tag `m06-disposition`.
- For prose that belongs to a human seat, give me a labelled draft to approve
  rather than blocking on me.
- q12 and q15 stay deferred. Noticing a failure is not grounds to fix it.

## Done when

`SPEC/07`'s own criterion: a recorded run-through of
`docs/governance/demo-script.md` in `milestones/M07/` — Door 1's blocked-merge
screenshot, Door 2's triage table plus SME approval plus eval-gate comment plus
merge, Door 3's HIGH security finding and required security seat — with all
three PR URLs listed in the journal.

Start by reading the specs and the governance docs, then come back with an
ordered plan, a price, and your reading of whether Door 1 can be made honest
this milestone or has to be rescoped.
