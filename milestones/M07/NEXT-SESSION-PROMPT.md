# M07 resume prompt — written 2026-08-22

Paste everything below the line into a fresh Claude Code session.

---

Resume M07 (SPEC/07, governance). It is **one pull request from closable**, and
that pull request is blocked by a defect it documents.

**Read first, in this order, and do not re-derive any of it:**
`milestones/M07/README.md`, then `milestones/M07/eval-gate-flake-gap.md`, then
`milestones/M07/doors/README.md`.

## Where things stand

The governance layer is **built, live and enforcing on `main`**. Six PRs merged
(#15–#19), two staged demo PRs closed unmerged (#20 Door 1, #21 Door 3). All
three doors have run for real with CI verdicts, written up in
`milestones/M07/doors/`.

The live merge gate:

| | |
|---|---|
| required checks | `unit`, `golden-set`, `ruling-cited` — bare job names |
| admin bypass | **REMOVED** — `bypass_actors: []`, `current_user_can_bypass: never` |
| merge methods | `["merge"]` only |
| eval gate bar | **regression**, not 20/20 (PM ruling, `eval-gate-bar-ruling.md`) |
| `EVAL_GATE_ENABLED` | `true` |

**Budget: ~$1.43 of $1.50 spent.** Every pull request costs a ~$0.20
`golden-set` run. **Get a fresh budget decision before opening one.**

## The blocker, and the first task

**[PR #22](https://github.com/andaro74/regdelta/pull/22) is OPEN and BLOCKED.**
It carries the doors evidence pack. `unit` and `ruling-cited` pass;
`golden-set` fails on **q05**, which is unrelated to the PR — #22 changes
documentation only.

There is **one unpushed commit** on branch `m07-pr-f` (`b64dd7c`) carrying the
q05 probe and its evidence. Pushing it re-triggers the checks and costs a run.

### What is established about q05, and what is not

Read `milestones/M07/eval-gate-flake-gap.md` in full. In short:

- q05 declined at `confidence 0.00` on **two consecutive** CI runs, identically.
- Asked **alone** against the same staging endpoint, cache bypassed the same
  way: **3/3 answered, confidence 0.93–0.95, correct citations**
  (`q05-probe.txt`, reproduce with `python milestones/M07/q05_probe.py`, ~$0.03).
- So the decline is a property of **the run**, not of the question, the corpus,
  or the ground truth. **Do not "fix" q05 by weakening it** — that is the
  ROLES.md prohibition, and the probe is the reason it did not happen here.
- Earlier, PR #20 was blocked by **q03** for a different reason. The failures
  move between questions.

**The mechanism is NOT established.** Load is the obvious hypothesis — twenty
questions in sequence hitting a Bedrock throttle or timeout, whichever question
loses. `confidence 0.00` with an empty answer is distinct from the ordinary HITL
declines in CloudWatch, which sit at 0.20–0.30 *with* a real answer attached.

**Start here, and start from the metrics rather than from that hypothesis:**

1. Read Bedrock throttling metrics and the query Lambda's logs around the
   timestamps of runs `32588109622` and `32590313314` (the two q05 declines).
   Log group `/aws/lambda/regdelta-core-QueryFnB2E9AD3D-hjcFpUj3WSqT`,
   us-west-2. **On Git Bash, prefix `MSYS_NO_PATHCONV=1`** or the log group path
   gets mangled into a Windows path.
2. Check whether failure correlates with position in the run.
3. Only then rule on the gate. **If it is load, the fix is in the runner, not
   the gate** — and none of the three candidate fixes in the gap document would
   have been right.

This document has been renamed twice — "the q03 gap", then "run-to-run
non-determinism". Both named the nearest symptom. Treat its current framing with
the same suspicion.

## Then, to close M07

1. Merge PR #22 — `gh pr merge 22 --merge`. **`--merge` only** (squash and
   rebase are removed from the ruleset; a squash orphaned `f651aea` at M06).
   **Do not pass `--admin`** — there is no bypass to use, so it fails rather
   than forces.
2. `/close-milestone 07` — evidence pack, `run_evals.py --record`, ADR statuses,
   tag **`m07`** (short form, never the branch name).

If PR #22 cannot be merged without spending past budget, the options are: turn
`EVAL_GATE_ENABLED` off (a skipped required check reads CLEAN — measured on
PR #16 — so it merges for $0, but it means switching the gate off days after
switching it on), or restore the admin bypass (one call, exact value in
`bypass-removed.txt`, but it undoes the clause SPEC/07's Door 1 Done-when
depends on). **Both are seat decisions. Ask.**

## Carried open, not closed

- **ADR-0014 (M06) and ADR-0015 (M07) are still `proposed`**, awaiting the human
  seat.
- **M05 was never closed and has no tag.** Untouched by M07, deliberately.
- **q12 and q15 are real unfixed defects** — q12's answer-composition layer
  inverts a verdict sentence it has already reasoned correctly; q15's retrieval
  embeds one raw query at `NAIVE_TOP_K = 8` with no decomposition
  (`src/graph/nodes.py:345`). Ground truth was **upheld** on both
  (`q12-q15-triage.md`). Each needs its own milestone.
- **`stub_layer` is copy-pasted into four test modules** and now defined a fifth
  time in `tests/conftest.py`, which is the home. A sixth module that
  synthesises the core stack will skip it by not knowing — exactly how the
  2026-08-22 CI failure happened.
- **`job_workflow_ref` is unpinned** on the OIDC role. Its exact rendering is now
  observed (`oidc-claims.txt`); the `@refs/pull/N/merge` suffix is per-PR, so a
  pin needs `StringLike` on `...evals.yml@*`. Needs a `cdk deploy` and a run.
- **SPEC/07 items 1–4 carry no Done-when observables** while item 5 carries the
  strictest in the file.

## Traps that cost this project once each

- **Merge commits only, never squash.** Never delete tag `m06-disposition`.
- **Ruleset updates are `PUT`, not `PATCH`, and must send the WHOLE object** —
  a one-key body drops `rules` and deletes branch protection.
  `add_required_checks.py` and `remove_bypass.py` do it correctly and re-read
  every field.
- **GitHub issues the IMMUTABLE OIDC subject here** —
  `repo:andaro74@3157440/regdelta@1322516232:pull_request`. The documented
  `repo:owner/name:` form does not work, and the API endpoint that reports this
  **contradicts itself**. Decode the token; never read the API.
- **Heredocs mangle escapes**, and `git commit -m` with backticks gets
  command-substituted. Write scripts to a file; pass messages with `-F`.
- **Do not `git add -A` after a `cdk` command.** `.gitignore` now covers both
  `cdk.out/` spellings, but a stray build artifact swept in 702k lines once.
- **Claiming a suite is green: say WHERE it ran.** `unit` was "green" for a
  whole milestone on this laptop only; its first CI run produced nine errors
  from a `make layer` artifact CI never builds.
