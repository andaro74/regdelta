# M07 — Governance Layer. **IN FLIGHT.** Doors 1–3 are what remain.

Branch work landed as **four pull requests, all merged** (#15, #16, #17, #18).
Close tag will be `m07`. **Session spend: ~$0.60** of a $1.50 budget — three
`golden-set` runs at ~$0.20. No `make up`, no OCU; the hot tier stays down.

Read this file first. The commit messages carry the detail.

---

## State of the gate, 2026-08-22

| | |
|---|---|
| required checks | `unit`, `golden-set`, `ruling-cited` — **bare job names**, all green on `main` |
| `EVAL_GATE_ENABLED` | **`true`** |
| eval gate bar | **regression, not 20/20** (PM ruling, `eval-gate-bar-ruling.md`) |
| admin bypass | **REMOVED** — `bypass_actors: []`, `current_user_can_bypass: never` |
| merge methods | **`["merge"]` only** — squash and rebase removed |
| `unit` | green in CI, first time ever verified on a runner |
| `golden-set` | green at 18/20; q12 and q15 reported, not gating |

`ruleset-after-bypass-removal.json` is the JSON SPEC/07's Door 1 Done-when
requires beside the screenshot.

## What still has to happen

**Doors 1, 2, 3 — the recorded run-through.** Everything they need now exists,
and Door 1 is finally filmable: the bypass is gone, so a pull request touching
`evals/golden_questions.json` without a ruling is refused to the repository
owner with no override offered.

**Each door costs ~$0.20**, because `golden-set` runs on every pull request.
Door 1 is one PR, Door 2 is two (ruling, then the change citing it), Door 3 is
one. Budget accordingly before starting.

Door 3's insecure branch is authorised with mitigations: an in-diff marker
naming it a staged demo artifact, the PR opened immediately so the security
finding is attached from the start, closed unmerged the same session.

## Rulings made this session

| file | seat | what |
|---|---|---|
| `spec07-door1-amendment.md` | PM | **ADOPTED** — Door 1 is a required check, not a review. Doors 1/2 of `demo-script.md` and SPEC/07's Done-when rewritten. |
| `eval-gate-bar-ruling.md` | PM | **ADOPTED** — the eval gate fails on a REGRESSION, not on 20/20, which had never been met. |
| `q12-token-ruling.md` | SME | **ADOPTED** — six accept tokens deleted; they admitted the answer the question excludes. |
| `q12-q15-triage.md` | SME | ground truth **UPHELD on both**. q12 is a model defect, q15 a retrieval defect. |
| `roles-amendment-draft.md` | lead+PM | **STILL OWED.** Complete replacement text written and waiting. |

## What the mechanism proved about itself

The milestone delivered itself through its own gate, and the gate refused it
twice on the way:

- PR #15 held back `evals/admitted_false_fails.json` because the ruling
  authorising it was inside the same pull request. Merged with the bypass, once,
  over redness `main` had carried since M04.
- PR #16 merged **CLEAN** — the first legitimate pass of `ruling-cited`.
- PR #17 merged CLEAN with `golden-set` green under the new bar.
- PR #18 changed `golden_questions.json` for real and was accepted **only**
  because PR #17 had put its ruling on `main` first.

---

---

## The two things that were waiting on the human seats — both RESOLVED

1. ~~PM ruling on Door 1's caption~~ — **ADOPTED all three**, 2026-08-22, at the
   foot of `spec07-door1-amendment.md`. Applied verbatim to `demo-script.md`
   Doors 1 and 2 and to SPEC/07's Done-when.
2. ~~Go-ahead to spend~~ — **given, capped at ~$0.60**, and ~$0.60 is what three
   `golden-set` runs cost. The first two failed before reaching Bedrock and were
   free.

**What is owed to a human seat now** is the lead+PM ruling on
`roles-amendment-draft.md`: `ROLES.md` line 4 and flow 1 still say CODEOWNERS
enforces the role boundaries, and `demo-script.md`'s Close still credits "a
review seat you don't control" three paragraphs below a Door 1 caption saying
there is no one else. Complete replacement text is written; it is
adopt / amend / reject. The Close is marked do-not-film until it is ruled on.

---

## What changed, and what it cost

| | state |
|---|---|
| `unit` | **GREEN LOCALLY ONLY, and that was the wrong claim** — see below. |
| q03 FRAGILE gate | resolved by the admitted-false-fail register (ADR-0015) |
| `regdelta-ci-eval` OIDC role | **deployed**, verified against live IAM |
| Actions secrets / variables | `AWS_EVAL_ROLE_ARN`, `STAGING_API_URL` (secrets), `REGISTRY_TABLE` (variable) |
| `EVAL_GATE_ENABLED` | **still `false`** — the spend line |
| Door 1 mechanism | built as a required check, not a review. No second account. |
| Required status checks | still only `unit`. `golden-set` and `ruling-cited` NOT yet added. |
| Admin bypass | still `always`. Probed and restored; not yet removed for real. |

### Correction, 2026-08-22: `unit` had never run green in CI

This file said "GREEN — 1273 passed, 0 failed. First green since M04." That
number was real and was measured **on this laptop only**. The first time the
branch reached GitHub, `unit` produced **nine errors** nobody here could have
seen:

```
FileNotFoundError: build/lambda-layer does not exist — run `make layer` first
```

`tests/test_ci_eval_role.py` synthesises the core stack to read the OIDC role
off the template, and the stack refuses to synth without the ~101MB `make
layer` artifact, which is not committed. This machine ran `make layer` months
ago. The runner never has.

The root cause is not the missing stub, it is that `stub_layer` was already
copy-pasted into **four** modules with no shared home, so a fifth module omits
it by not knowing it exists. It now lives once in `tests/conftest.py`, beside
the AWS-profile block that exists for exactly this class of defect. The four
copies are left alone and carried as open.

Same shape as the defect this milestone opened by finding: a measurement that
was true, and an inference from it that was not. CI is the falsifier here, and
nothing on this branch had been shown to it.

**In CI, on PR #15, after the fix: 3 failed, 1245 passed — exactly the three
`tests/test_replay_exit_codes.py` failures `main` carries today.** PR A adds no
new redness, and that sentence is now measured where it matters rather than
here.

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

Steps 1-4 of the previous plan are DONE: the two-PR split (which became four),
the flag flip and required checks, ADR-0005's SKIPPED question, and the admin
bypass removal. What is left is the demo itself.

**1. Doors 1, 2, 3 — the recorded run-through.** ~$0.20 per pull request,
because `golden-set` runs on every one. Door 1 is one PR, Door 2 is two, Door 3
is one: budget ~$0.80 before starting.

- **Door 1** is finally filmable and was not before. Edit
  `evals/golden_questions.json` with no ruling; `ruling-cited` fails and prints
  the SME seat by name; the merge is refused **to the repository owner with no
  bypass offered**. `ruleset-after-bypass-removal.json` is the JSON SPEC/07's
  Done-when requires beside the screenshot.
- **Door 2** is the path this milestone has already run for real, twice —
  PR #17 landed a ruling, PR #18 cited it. Film it again on the demo change, or
  cite those two if a live take is not affordable.
- **Door 3**: the insecure branch is authorised with mitigations — in-diff
  marker naming it a staged demo artifact, PR opened immediately so the security
  finding is attached from the start, closed unmerged the same session.

**2. The lead+PM ruling on `roles-amendment-draft.md`,** which Door 3's Close
depends on. `demo-script.md`'s Close is marked do-not-film until then.

**3. Close the milestone** — `/close-milestone 07`, `run_evals.py --record`, the
ADRs, the tag.

**Watch for:** every pull request now costs a `golden-set` run, and the admin
bypass is gone. A red check has no override — that is the point, and it is also
the thing that will surprise someone at the wrong moment. Restoring it is one
call and the exact value to restore is printed in `bypass-removed.txt`.

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
  AccessDenied is not ambiguous about which claim was wrong. **That paid off**:
  the first AccessDenied was unambiguous and the cause was the `sub` claim, not
  this. The value is now OBSERVED and recorded in `oidc-claims.txt`:
  `andaro74/regdelta/.github/workflows/evals.yml@refs/pull/17/merge`. Note the
  `@refs/pull/N/merge` suffix is per-pull-request, so a pin needs `StringLike`
  on `...evals.yml@*`. Still not done — it needs a `cdk deploy` and a run to
  confirm, and the role has only just started working.
- **`stub_layer` is copy-pasted into four test modules** and now defined a fifth
  time in `tests/conftest.py`. That fifth one is the home; the four are not
  collapsed into it, because they pass and the refactor did not belong in the
  branch that found the bug. A sixth module that synthesises the core stack will
  skip it by not knowing, which is exactly how this one happened.
- **q12 and q15 are real defects and are now non-gating.** q12's
  answer-composition layer inverts a verdict sentence it has already reasoned
  correctly; q15's retrieval embeds one raw query at `NAIVE_TOP_K = 8` with no
  decomposition (`src/graph/nodes.py:345`). Triage and sources in
  `q12-q15-triage.md`. Neither is M07 scope; both need their own milestone.
- **The staging API is public and unauthenticated.** Pre-existing, named in
  SPEC/07 as scope, and owed a security-seat question of its own.
- **M05 is still not closed and has no tag.** Untouched by M07, deliberately.
- **ADR-0014 is still `proposed`**, and M06's "what I'd redo" is still DRAFT.
