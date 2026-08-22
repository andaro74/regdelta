# M07 — Governance Layer (three doors). **CLOSED.**

- Git tag: `m07`          Scorecard commit: `652d475`   Branch: `m07-pr-f`
- Spec: SPEC/07-governance.md
- ADRs touched: ADR-0015 (`proposed`), ADR-0013 (invoked, not amended).
  ADR-0014 carried from M06, still `proposed`. **Neither 0014 nor 0015 has
  been accepted by a human seat, and closing M07 does not accept them.**
- Sessions: 3 Claude Code sessions. Six pull requests merged (#15-#19, #22),
  two staged demo PRs opened and closed unmerged (#20 Door 1, #21 Door 3).

## Scorecard

| run | tier | subset | pass | total | mode |
|-----|------|--------|------|-------|------|
| `652d475` | s3vectors | full | 18 | 20 | agent |

`evals/history/652d475-s3vectors-full.json`, recorded at close on the
always-on tier. No `make up`, no OCU; the hot tier stayed down for the whole
milestone, so there is no Tier B row and M07 touches no retrieval code.

**Delta vs baseline (M00b): traps q01-q04 1/4 → 4/4, overall 30% → 90%.**
Unchanged from M06 — as it should be. **M07 is a governance milestone and
moved no answer-quality number.** A milestone that adds gates and reports a
score improvement would be reporting a coincidence, or a gate that had
started grading itself.

The two misses are `q12` and `q15`, both reported on every card and gating
nothing: they have recorded runs and have never passed in any of them. Both
were triaged from the SME seat this milestone (`q12-q15-triage.md`) and
**ground truth was upheld on both**. They are real product defects and each
needs its own milestone.

## What you can demo at this point (2-3 min)

1. **Open PR [#20](https://github.com/andaro74/regdelta/pull/20).** One line
   added to `evals/golden_questions.json` — an accept token that makes a
   failing question pass. `ruling-cited` FAILS with a message naming the SME
   seat; `unit` is GREEN on the same commit, so the block is attributable to
   the governance check and nothing else. Then open the merge box:
   `bypass_actors` is `[]` and the repository owner is offered **no override**.
2. **Follow it with [#17](https://github.com/andaro74/regdelta/pull/17) →
   [#18](https://github.com/andaro74/regdelta/pull/18).** The same change made
   the way the gate demands: the ruling lands first, in its own pull request,
   and the ground-truth edit then cites it. Both CLEAN. The triage is the part
   worth reading — `sme-eval-triage` upheld ground truth on both questions and
   moved no expected answer.
3. **Close on [#21](https://github.com/andaro74/regdelta/pull/21) and then on
   `eval-gate-flake-gap.md`.** #21 hides `resources=["*"]` inside a plausible
   pagination fix; `security-reviewer` returned two HIGH findings and also
   established that **the plausible fix does not exist** — the file it claims
   to fix already paginates on `main`. Then the honest ending: the gate caught
   a defect in this milestone's own work, was misdiagnosed four times, and the
   instrument that would have settled it was built at M05 and read by nobody.

## Evidence artifacts

- `evals/history/652d475-s3vectors-full.json` — the close scorecard
- `doors/` — all three doors as real pull requests with CI verdicts
- `close-verification.txt` — Done-when run at close, and the one substitution
  declared rather than assumed
- `q05-mechanism.txt` — the CloudWatch read that ended the flake story
- `ruleset-after-bypass-removal.json`, `bypass-removed.txt` — the live gate
- cost: **~$1.83** across three sessions (nine `golden-set` runs at ~$0.20;
  several early ones failed upstream of Bedrock and were free). No OCU spend.

## What broke / what I'd redo

**1. `unit` was called green for a whole milestone on the strength of a
laptop.** Its first CI run produced nine errors from a `make layer` artifact
the runner never builds. The measurement was real; the inference from it was
not.

**2. `stub_layer` was copy-pasted into four test modules with no home.** That
is why a fifth module omitted it by not knowing it existed. It now lives in
`tests/conftest.py` and the four copies are still there — a sixth module will
repeat this.

**3. The eval gate's failure was diagnosed wrong four times running** — q03,
then non-determinism, then load, then completion length — because
`stop_reason`, built at M05 precisely to tell these apart, is in the API
response body and read by no consumer. The instrument existed and pointed at
nothing.

**4. The OIDC mutation suite spent hours asserting "0 survivors out of 5"
about a string that no longer existed in `core_stack.py`.** Caught only
because the runner distinguishes NOT APPLIED from KILLED. The property was
never undefended; the *proof* that it was defended had quietly stopped being
run.

**5. Three of the five above are the same defect.** An artifact that was true
when written, still being read as current after the thing it measured moved.
That is what this milestone is about, and it kept happening inside the
milestone.

---

# Session record

What follows is the working journal, left as written.

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

## What still had to happen — ALL DONE

*(Left as written. Every item below happened: the doors ran as PRs #20, #17 ->
#18 and #21, and are written up in `doors/`.)*

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
| `roles-amendment-draft.md` | lead+PM | **ADOPTED** — applied to `docs/governance/ROLES.md` line 4 and flow 1, and at close to the root `README.md` Governance section, which had carried the same CODEOWNERS-enforces claim. |

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

> **SUPERSEDED, AND KEPT.** The four rows marked below were true when written
> and are false now — `EVAL_GATE_ENABLED` is `true`, all three checks are
> required, and the admin bypass is gone. **The State of the gate table at the
> top of this file is authoritative.** This one is left standing because a
> journal that quietly rewrites its own earlier state is exactly the artifact
> this milestone spent itself learning not to trust. Read it as a snapshot
> with a date on it, not as current.

| | state |
|---|---|
| `unit` | ~~GREEN LOCALLY ONLY~~ **SUPERSEDED — green in CI on a runner** (the wrong claim is dissected below, and is worth reading) |
| q03 FRAGILE gate | resolved by the admitted-false-fail register (ADR-0015) |
| `regdelta-ci-eval` OIDC role | **deployed**, verified against live IAM |
| Actions secrets / variables | `AWS_EVAL_ROLE_ARN`, `STAGING_API_URL` (secrets), `REGISTRY_TABLE` (variable) |
| `EVAL_GATE_ENABLED` | ~~still `false`~~ **SUPERSEDED — now `true`** |
| Door 1 mechanism | built as a required check, not a review. No second account. |
| Required status checks | ~~still only `unit`~~ **SUPERSEDED — all three required and green** |
| Admin bypass | ~~still `always`~~ **SUPERSEDED — REMOVED, `bypass_actors: []`** |

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

## Next session, in order — DONE, and what it found

**Everything SPEC/07's Done-when asks for now exists.** All three doors ran as
real pull requests with CI verdicts, and the run-through is written up in
`milestones/M07/doors/` with the three PR URLs.

| door | PR | outcome |
|---|---|---|
| 1 | [#20](https://github.com/andaro74/regdelta/pull/20) | BLOCKED by `ruling-cited`, `unit` green, bypass empty. Closed unmerged. |
| 2 | [#17](https://github.com/andaro74/regdelta/pull/17) -> [#18](https://github.com/andaro74/regdelta/pull/18) | MERGED CLEAN. Not staged — the milestone delivering itself. |
| 3 | [#21](https://github.com/andaro74/regdelta/pull/21) | BLOCKED, two HIGH findings, `unit` red too. Closed unmerged. |

**1. `eval-gate-flake-gap.md` — CAUSE ESTABLISHED, ruling drafted.** Read it
and `q05-mechanism.txt` before closing. **The gate was right.** The metrics
refute the load hypothesis outright — no throttle in either window (the metric
does not exist for this account), no timeout, no retry, no error, and q05 is
question five of twenty. The verdict call **succeeded** both times, 7083 in and
764 out against a `max_tokens` of 2000, on a prompt byte-identical to the one
the probe answered 6/6. `_json_object` could not parse the reply, returned
`{}`, and every downstream field collapsed. **q05 is a parse defect in
`verdict()`, not noise** — same layer as q12, and it belongs in that milestone.
All three candidate fixes the gap document proposed would have hidden it; one
would have made it permanently invisible. What remains open is one policy
question, not a gate-theory question.

The history below is left as filed, because the diagnosis was wrong three
times in the same direction and that is the useful part:

- PR #20 — q03 regressed. `unit` was green on the same commit because
  `replay_history` honoured the ruled admission; `golden-set` failed because
  `gate_verdict()` never consults the register.
- PR #22 — q05 regressed, and not on a token: the system **DECLINED to answer**
  at confidence 0.00. q05 has passed in eleven recorded runs. PR #22 changes
  documentation only.

So the narrow fix ("consult the register") is insufficient: the register admits
one ruled q03 observation and ADR-0015 caps it there. The real shape is that
`run_evals.py` scores **one live sample** per question and the gate calls any
miss a regression, while `replay_history.py` compares recorded runs and has a
`FRAGILE` classification precisely because questions flip.

**Operational consequence, with no bypass:** a docs-only PR cannot merge until a
non-deterministic system happens to produce a passing sample, and the only
recourse is re-running at ~$0.20 a time — the "repeat until green" behaviour
`run_evals.py` itself warns about. **The gate currently makes the repository's
own anti-pattern the only way to merge.**

**2. Close the milestone** — `/close-milestone 07`: evidence pack,
`run_evals.py --record`, the ADRs, tag `m07`. **DONE, 2026-08-22.** Step 1 is
recorded in `close-verification.txt`, including the one substitution declared
and the stale mutation suite it caught. Step 2 recorded 18/20 at `652d475`.
Step 4: no new ADR — the bypass removal and Door 1's shape are already PM-seat
rulings in this pack, and ADR-0005 already rules that the seat is what counts.
ADR-0014 and ADR-0015 stay `proposed`; closing M07 does not accept them.

**Watch for:** every pull request costs a ~$0.20 `golden-set` run, and there is
no admin bypass. A red check has no override — that is the point, and it is also
what will surprise someone at the wrong moment. Restoring it is one call and the
exact value is in `bypass-removed.txt`.

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

- **THE EVAL GATE IGNORES THE ADMISSION REGISTER** (`eval-gate-flake-gap.md`).
  Still true and still open: `unit` admits a ruled q03 observation; `golden-set`
  does not, because `gate_verdict()` never consults
  `evals/admitted_false_fails.json`. The register is keyed per recorded artifact
  and a live run has none, so a fix has to decide what an admission MEANS for an
  answer nobody has seen. **It is no longer the biggest one, and it was never
  q05's cause** — that was a parse defect in `verdict()`, measured in
  `q05-mechanism.txt`. This is q03's problem only.

- **`_json_object` SWALLOWS AN UNPARSEABLE MODEL REPLY** and reports it as
  confidence 0.00 with an empty answer (`q05-mechanism.txt`). Blocked PR #22
  twice. The instrument that identifies it — `stop_reason`, built by M05 and
  ADR-0013 — is in the API response body and is read by no consumer:
  `run_evals.py` does not print it on a failure and neither did `q05_probe.py`,
  and nothing records the raw completion. **The next occurrence will cost
  another session of archaeology until that changes.** Product defect, same
  layer as q12, and it belongs in that milestone rather than this one.

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
