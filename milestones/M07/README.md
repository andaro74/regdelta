# M07 — Governance Layer. **IN FLIGHT, NOT CLOSED.**

Branch `m07-governance`, cut from `main` at `8be904a`. Close tag will be `m07`.
**Nothing is pushed** — the branch is local only, so there is no open PR and no
CI running. **Session spend to date: $0.** No `make up`, no OCU; the hot tier is
down (`/regdelta/search/endpoint` is `ParameterNotFound`) and M07 does not need
it.

Read this file first. The commit messages carry the detail; this says where to
pick up.

---

## The two things waiting on the human seats

1. **PM ruling on Door 1's caption** — `spec07-door1-amendment.md`. It contains
   the *complete* replacement text for `demo-script.md` Doors 1 and 2 and for
   SPEC/07's Done-when, so it is adopt / amend / reject, not a drafting task.
2. **Go-ahead to spend.** Flipping `EVAL_GATE_ENABLED` starts Bedrock on every
   PR, ~$0.18–0.20 per 20-question run. Budget $1.50, spent $0.

Everything else is mine and is described below.

---

## What changed, and what it cost

| | state |
|---|---|
| `unit` | **GREEN** — 1273 passed, 0 failed. First green since M04. |
| q03 FRAGILE gate | resolved by the admitted-false-fail register (ADR-0015) |
| `regdelta-ci-eval` OIDC role | **deployed**, verified against live IAM |
| Actions secrets / variables | `AWS_EVAL_ROLE_ARN`, `STAGING_API_URL` (secrets), `REGISTRY_TABLE` (variable) |
| `EVAL_GATE_ENABLED` | **still `false`** — the spend line |
| Door 1 mechanism | built as a required check, not a review. No second account. |
| Required status checks | still only `unit`. `golden-set` and `ruling-cited` NOT yet added. |
| Admin bypass | still `always`. Probed and restored; not yet removed for real. |

## The two decisions that shaped it

**q03.** M05 open thread 7 proposed scoring q03 structurally. Measured across
all 22 recorded answers before building it: the field it names
(`answer_rows[*].citations`) is `[]` in the **passing** answers too, so the rule
cannot discriminate, and 10 of 22 answers carry no `answer_rows` at all. Two
other candidates measured and dead. The SME seat ruled option A — a per-artifact
admission register — and the PM seat homed it in SPEC/07.

**Door 1.** ADR-0005 had already rejected the second-account route as "ceremony,
not accountability", and its extension rules that "the signature is theater; the
seat is not". Door 1 is now `ground-truth-gate / ruling-cited`: a PR touching an
SME-owned path must cite a ruling that is already on `main` **and** names the
file it rules on. It binds the repository owner, cannot be satisfied from inside
the PR it blocks, and needs no second identity.

---

## Next session, in order

**1. Land M07 as TWO pull requests.** The gate blocks this branch, correctly:

```
$ python evals/check_ground_truth_ruling.py --base main --head HEAD
BLOCKED: a changed path has no ruling behind it.
  evals/admitted_false_fails.json — no cited ruling on main names it
  citation 'milestones/M07/q03-rulings.md' rejected — not present on the base commit main
```

So: **PR A** carries `milestones/M07/q03-rulings.md` and the gate itself, and
touches no SME-owned path (passes trivially). **PR B** carries
`evals/admitted_false_fails.json` with `RULING: milestones/M07/q03-rulings.md`
on its commit. The milestone delivering itself is the mechanism's first live
exercise, and is better evidence than a staged demo.

Splitting the existing eight commits is the first real task and is not trivial —
they interleave. Consider cherry-picking the ruling doc onto a fresh branch
rather than rewriting history.

**2. Flip the gate and add the required checks, in one change.**
`.github/workflows/evals.yml`'s own reversal condition and ADR-0005's M04 debt
both land here.

- `gh variable set EVAL_GATE_ENABLED --body true`
- add `golden-set` and `ruling-cited` to the ruleset by **bare job name** —
  never `eval-gate / golden-set`, which is the display format that matched
  nothing and deadlocked PR #1 for four days (ADR-0005)
- restore the sentence in `evals.yml`'s header that was removed because it was
  false (security-reviewer M4) — only after the check is actually required

**Expect the first run to fail.** `golden-set` has never executed once. That run
simultaneously tests the first-ever assumption of the OIDC role, a region that
was wrong until M07, a `REGISTRY_TABLE` never passed before, a fork guard added
at M07, and a secrets-vs-variables switch. Budget several cycles.

**3. Answer ADR-0005's open question**, two milestones overdue: does a SKIPPED
required check block a merge? `golden-set` can now actually skip (fork guard,
or the flag), so it is finally answerable. Free.

**4. Remove the admin bypass** — only after `unit` and the new checks are green,
because that bypass is the only way past a red check today.

**5. Doors 1, 2, 3.** Door 3's insecure branch is authorised, with mitigations:
in-diff marker naming it a staged demo artifact, PR opened immediately so the
security finding is attached from the start, closed unmerged the same session.

---

## Traps, all of them paid for once already

- **Merge with a merge commit, never a squash.** PR #13's squash orphaned
  `f651aea` and forced a preservation tag. Never delete tag `m06-disposition`.
- **Ruleset updates are `PUT`, not `PATCH`** — PATCH returns a flat 404 that
  says nothing. And send the **whole ruleset**: if PUT replaces rather than
  merges, a one-key body silently drops `rules`, deleting branch protection.
  `bypass_probe.py` does it correctly.
- **A `script:` body is a YAML value, not a comment.** Actions expression syntax
  inside a `//` comment there is still parsed; an empty one is a syntax error.
- **Do not re-run `gh api .../actions/variables` into a committed file.** That
  endpoint returns variable **values**. It is safe today only because the
  secrets went to secrets.
- **Heredocs mangle escapes.** Two probe files were corrupted this session by
  `\\n` in a heredoc, and a commit message lost a line to backtick command
  substitution. Write scripts to a file; pass commit messages with `-F`.
- **Line endings.** The working tree is CRLF and git stores LF. A probe reading
  `read_bytes()` and matching `\n` anchors silently matched nothing — it
  reported "not applied" rather than "killed", which is the only reason it was
  legible.

---

## Artifacts

| file | what |
|---|---|
| `baseline/` | the governance state before anything changed, and 4 defects found reading it |
| `q03-rulings.md` | the SME and PM rulings, with the drafts they were made against |
| `q03_*.py` + `.txt` | five $0 probes; why M05 open thread 7 does not work |
| `admission_mutations.py` + `.txt` | 13 cases against the register, 0 survivors |
| `ground_truth_gate_mutations.py` + `.txt` | 13 attempts to sneak a ground-truth edit past Door 1, 0 survivors |
| `workflow_guard_mutations.py` + `.txt` | 11 mutations of the workflow permissions guard, 0 survivors |
| `ci_eval_role_mutations.py` + `.txt` | 5 mutations of the OIDC role, 0 survivors |
| `ci-eval-role/` | `cdk diff`, and the LIVE trust and permission policies read back from IAM |
| `bypass_probe.py` + `.txt` | emptying `bypass_actors` flips the owner to `can_bypass: never`; rules survive; restored |
| `wire_actions_config.py` + `.txt` | secrets and variables set from stack outputs, values digested not printed |
| `spec07-pm-review.md` | pm-spec-reviewer's 13 findings and what was done about each |
| `security-review.md` | security-reviewer's 9 findings, one HIGH that this branch introduced |
| `spec07-oidc-amendment.md` | ADOPTED — item 2's permission clause |
| `spec07-door1-amendment.md` | **AWAITING THE PM SEAT** — Door 1's caption |
| `unit-green/` | the green `unit`, and `replay_history --no-admissions` showing the unadmitted truth beside it |

## Still open, carried not closed

- **SPEC/07 items 1–4 carry no Done-when observables at all** while item 5
  carries the strictest in the file (pm-spec-reviewer 12). A Done-when change,
  so a PM ruling of its own.
- **`ROLES.md` still claims CODEOWNERS enforces the boundaries.** After M07 that
  is true of `ground-truth-gate` and false of CODEOWNERS. Lead + PM co-owned.
- **The register can hold a badly-reasoned entry.** No check reaches that
  (ADR-0015). The cap of one entry is enforced by a test; growing it takes a
  seat ruling and a spec change.
- **`job_workflow_ref` not pinned on the OIDC role** — deliberate, so the first
  AccessDenied is not ambiguous about which claim was wrong. Add it after the
  first successful assumption.
- **The staging API is public and unauthenticated.** Pre-existing, named in
  SPEC/07 as scope, and owed a security-seat question of its own.
- **M05 is still not closed and has no tag.** Untouched by M07, deliberately.
- **ADR-0014 is still `proposed`**, and M06's "what I'd redo" is still DRAFT.
