# M04 — API + Demo UI  **(IN PROGRESS)**

- Branch: `m04-api-demo`   PR: **#11 (draft)**   Spec: `SPEC/04-api-and-demo.md`
- Base: `main` at `f22b545` (M02 + M03 merged 2026-08-16)
- This pack is written mid-milestone, not at close. Everything below is either
  measured and cited, or named as not yet done. Nothing here is a projection.

## Where it stands

| phase | state |
|---|---|
| 0 — spec amendment (`/resume` auth) | **done**, `pm-spec-reviewer` accept-with-changes |
| 1 — `/query`, `/resume`, `/health`, `scenarios.json` | **done**, verified end-to-end against real AWS |
| 2 — response cache + bypass | **done**, verified against real DynamoDB |
| crossref wiring (M03 carryover, M04-blocking) | **done**, SPEC/04's retrieval gate now passes |
| 3 — UI | not started |
| 4 — `make demo-parity` + Tier B latency | **done**, both tiers measured against real AWS |
| 5 — golden set vs deployed API, both tiers | not started |

## Evidence

`evals/history/a7bd28c-s3vectors-full.json` — agent mode, 49-document corpus:

    overall            18/20  (90%)     was 16/20 before the crossref fix
    --subset retrieval   5/5            SPEC/04's Done-when clause: MET
    --subset trap        8/8
    --subset smoke       5/5
    --subset timeline    6/7

719 tests, ruff clean. **CI is RED on #11** — see "CI is red, and it is not
Phase 4" below.

### Phase 4 — `milestones/M04/answer-parity-3966b47.json`

`make demo-parity` run on each tier at one commit, across a `make up`. Verdict
**pass**, `dirty: false`, both tiers present, three scenarios, none vacuous.

| scenario | citations agree | `real_deadline` agree | same-tier determinism | cache |
|---|---|---|---|---|
| `healthy-claim` | ✅ `89 FR 106064`, `90 FR 10592` | ✅ `2028-02-25` | stable on both | `bypass` ×4 |
| `red-no-3` | ✅ `21 CFR 74.303`, `21 CFR 80.32(h)`, `90 FR 4628`, `91 FR 50475` | ✅ `2027-01-15` | stable on both | `bypass` ×4 |
| `needs-review` | ✅ `2024-29957`, `2025-03118`, `89 FR 106064` | ✅ `2028-02-25` | stable on both | `bypass` ×4 |

Both controls fired for real, not by assertion: every one of the twelve
responses recorded `cache: bypass`, and every scenario was answered twice on
**both** tiers rather than the one SPEC/04 requires. Answers and probes both
resolved to the requested tier with zero fallbacks, checked three ways —
`/health` before and after, and every `Resolution` observed during the run.

### The Tier B latency number, and what it says

ADR-0001 asked for this at M02 and M02 closed without it. It now exists:

| tier | median | p95 | min | max |
|---|---|---|---|---|
| A — S3 Vectors | **354.1 ms** | 621.2 ms | 320.8 ms | 630.4 ms |
| B — AOSS | **889.3 ms** | 1300.7 ms | 788.8 ms | 1328.5 ms |

n=27 each (9 probes × 3 passes), nearest-rank p95, warmup sample excluded and
recorded. No target, per SPEC/04 — what was gated is that an honest number
exists.

**Tier B is 2.5× slower, not faster.** SPEC/04 wrote the criterion for exactly
this outcome: "if Tier B turns out *not* to be meaningfully faster at this
corpus size that is a finding to record and a demo beat to drop, not a number
to tune until it passes." After ADR-0009 Ruling 3(a) retired the relevance
justification, latency was Tier B's **only remaining candidate justification**,
and this is the measurement that was owed against it.

Two caveats, so the number is read for what it is:

- **Vantage is the dev laptop**, in-process, not Lambda-to-AOSS in-region. That
  is the instrument SPEC/04 names for the artifact (the deployed round trip is
  the UI readout, "different instruments" by that criterion's own wording), but
  a production vantage could move the ratio and has not been measured.
- **Sequential, single stream.** Concurrent load is M06's, so this licenses no
  throughput claim — and Tier B's case, if one survives, is likelier to live
  there than here.

It agrees in direction with the only other number in the repo: whole-run
`wall_s` had AOSS slower in every recorded pair. Two unlike instruments, same
direction.

**This is a PM-seat call and is NOT decided here.** SPEC/04: "Deciding what to
do with it is a PM-seat call once it exists." What is decided is that CLAUDE.md's
"do not say faster" now has a measurement behind it rather than an absence.

## What Phase 4 required — and how the harness answers each part

SPEC/04's comparability criterion, read closely — it carries **two controls that
are corrections, not refinements**, and the criterion measures nothing without
them:

1. **Both tier runs bypass the response cache**, and the artifact records that
   they did. Implemented and ready: `no_cache: true` in the body, or the
   `x-regdelta-no-cache` header; every response carries a `cache` field
   (`hit|miss|bypass|disabled`). Without this the two runs are minutes apart
   inside a 1h TTL, the second is a hit returning the first tier's answer, and
   citations agree by construction.
2. **Each scenario answered twice on ONE tier.** Without a same-tier control a
   disagreement cannot be attributed: ordinary run-to-run variance and genuine
   tier-caused divergence look identical.

The artifact is `milestones/M04/answer-parity-<sha>.json`, recording per
scenario per tier: scenario `id`, **sha256 of the question and profile as run**,
the citation set, every `real_deadline`, and the cache status. It passes when
the two tiers agree on citations (as sets) and every `real_deadline` exactly.
Confidence and prose may differ.

Plus **Tier B's latency**, a debt owed since ADR-0001 asked for "retrieval p50
per tier" at M02: median and p95 `router.retrieve()` per tier over the probe
set, in the artifact. **No target is set, deliberately** — the criterion gates
that an honest number exists, not that it beats a threshold. If Tier B is not
meaningfully faster, that is a finding and a demo beat to drop.

`evals/run_demo_parity.py` adds **two guards SPEC/04 does not name**, because
without them the gate can be green while measuring nothing — the same defect
class its own blockquote records:

3. **The scenario's status must match `expected_status`.** A scenario that
   pauses when it should answer carries no citations and no deadlines on either
   tier, so empty agrees with empty and it passes by construction. Status
   mismatch **voids** the scenario.
4. **A comparison with nothing in it is marked `vacuous`.** `needs-review`
   legitimately could have carried nothing; three "agree" verdicts must not read
   as three scenarios' worth of evidence. (In the recorded run all three are
   substantive — even the paused one returns a verdict row and citations.)

Each of the four is unit-tested in `tests/test_demo_parity.py`, and each test
was checked against the unguarded code: **eight mutations, eight caught.**

## What went wrong on the way, and is now fixed

**The hot tier could not come up at all.** `make up` failed at
`HydrateOnDeploy`: `Unable to import module 'retrieval.reindex': No module
named 'retrieval'`. The reindex Lambda's asset held two files.

`infra/search/search_stack.py` staged `src/` with an allowlist,
`exclude=["*", "!**/*.py"]`, under CDK's **default** `IgnoreMode.GLOB`. Measured
with a probe synth over a tree containing `.env`, `.aws/credentials`, `dev.env`,
`secrets.json`, a `credentials` file with no extension and `__pycache__`:

    GLOB (deployed)  ['.env', '__init__.py']      source tree dropped, .env LEAKED
    GIT              ['__init__.py']              still no source tree
    DOCKER           the .py tree, and only it    correct

One line failing at both of its jobs: `*` matches directories and a pruned
directory cannot be re-entered by a later negation, so `!**/*.py` reached
nothing below the root; and minimatch's `*` does not match a dot-prefixed name,
so the allowlist added by security-review finding **L4** never excluded the
shapes it was written for. Fixed with `ignore_mode=IgnoreMode.DOCKER`, plus a
third pattern `**/*.py/**` closing a hole `security-reviewer` found in the fix
itself (a *directory* named `keys.py` re-included its whole subtree).

**The test that should have caught it asserted the handler string**, which is a
claim about the template — and the template cannot say whether the module is in
the zip. Its replacement stages a **planted hostile tree** through the stack's
own `ASSET_EXCLUDE` / `ASSET_IGNORE_MODE` constants. The first version of that
replacement asserted over the real `src/` and `security-reviewer` showed it
passed vacuously in a clean checkout — green by construction, one level down,
in the test written to close a green-by-construction defect. Five mutations now
checked, all caught.

## CI is red, and it is not Phase 4

`gh pr checks 11` → `unit fail`, and it was red before this session started.
`f060cea` added `evals/history/a7bd28c-s3vectors-full.json`, and
`replay_history.py` now reports a gating finding:

    FRAGILE  q14: agent answers disagree across runs —
             2cea737=FAIL a7bd28c=PASS e26d8ef=FAIL
             both failures on: missing required: '101.13(h)'

Three `tests/test_replay_exit_codes.py` tests fail on it. Reproduced with this
session's changes stashed, so it is not Phase 4's. **It is a determinism finding
about the answer layer** — the same property `make demo-parity`'s control 2
tests, which the three demo scenarios passed cleanly on both tiers. Untouched
here: it is an eval-instrument and golden-set matter, which routes through
`sme-eval-triage` and a human ruling, not an implementer.

## Deferred, with evidence — not forgotten

- **q15 / retrieval decomposition.** One unfiltered query at `top_k=8` for a
  question naming two unrelated triggers; the colour half dominates the
  embedding and the 'healthy' half is never retrieved. NOT in any gated subset
  (`[applicability, verdict]`) and all three demo scenarios pass, so it does not
  block M04. It is the worst remaining defect for a compliance product: it told
  a manufacturer bearing a 'healthy' claim that no such rule could be confirmed.
- **q12 / point-in-time reasoning.** The system answers "was that a fair reading
  in mid-2025" as a likelihood question rather than a finality one. Ruled (a)
  SYSTEM by `sme-eval-triage` against 21 U.S.C. 371(e)(2); the question stands.
- **The naive control passes four of the eight traps** (q02, q04, q11, q20) on
  its own recorded answers. SME-seat re-read. Declared in SPEC/03 and the M03
  pack.
- **Rule (7)'s match reporter.** `check()` reports only failure reasons, so a
  PASS is unauditable at token granularity. Would have caught q05 while green.
- **Per-job workflow permissions guard.** Declined 2026-08-16 with a reversal
  condition recorded in `.github/workflows/evals.yml`: add it in the same change
  that flips `EVAL_GATE_ENABLED`.
- **`>= 80%` as a form of bar.** At twenty questions it permits four failures
  where it permitted two at ten. Recommendation on file is an absolute count,
  with an ADR, before the set grows again.
- **`infra/core/core_stack.py` ships `../src` with no exclude at all.** Measured
  by `security-reviewer` during the M04 asset fix: **75 files staged, 39 of them
  non-`.py`** — `.pytest_cache/`, every `__pycache__/*.pyc` — into the poller,
  processor and query Lambdas, on the **persistent** stack. Larger blast radius
  than the ephemeral stack the fix closed, and `core_stack` has **no test
  coverage at all**. Not fixed here: it is a persistent-stack change needing
  `make core`, and SPEC/04's scope is the demo. For the human seat.
- **`router.hydrate` reports no `Resolution`.** `run_demo_parity.py` observes
  every retrieval to prove which tier answered, but hydration has its own
  AOSS→S3-Vectors fallback and is invisible to that check. A crossref hydration
  that fell back mid-run would not be caught. Named in the harness docstring.
- **FR doc numbers and `NN FR PPPP` are one document in two notations**, and the
  parity comparison treats them as two citations. It did not fire here (both
  tiers cited the same forms), and resolving one to the other would make the
  comparison depend on the document registry — a third store. A false positive a
  reader can see both sides of is the better failure; recorded in the harness.

## Environment notes that cost real time this session

- **Always `eval "$(python evals/local_env.py)"` before anything touching AWS.**
  It resolves the deployed query Lambda's own environment. Without it the shim
  exits and `make agent-evals` measures nothing.
- **Two interpreters.** `.venv` and the user-level Python 3.14 both exist and
  disagreed; `.venv` was missing `langgraph`, `fastapi`, `ruff` and `httpx`
  entirely. `pip install -r requirements-dev.txt` makes `.venv` match CI.
- **`gh` is at `/c/Program Files (x86)/GitHub CLI/gh.exe`** and may not be on
  PATH in a shell started before the 2.97 upgrade.
- **ruff's `EXE001`/`EXE002` are skipped on Windows** — they read the filesystem
  exec bit. `tests/test_file_modes.py` closes that gap from the git index.
- **This shell mangles backslashes in heredocs.** Write scripts with a file, not
  a heredoc, when they contain regexes or line continuations. It cost a mangled
  test file again this session: `"a\\nb"` inside a `<<'PY'` heredoc reached the
  file as a real newline and broke the parse. Use the file tools instead.
- **`make up` takes ~20 minutes** (collection CREATING, then the reindex
  hydration custom resource) and the SSM parameter appears **before** the stack
  reaches `CREATE_COMPLETE`. Do not start a tier-B measurement on the parameter:
  wait for the stack status, or the run measures a half-hydrated index.
- **Watch a long run's progress, not its exit.** Piping through `grep` buffers
  everything until the process ends; `run_demo_parity.py` sets
  `line_buffering=True` on stdout for the same reason, since `make demo-parity`
  is normally watched down a pipe.
- **A failed `make up` leaves nothing running** — CloudFormation rolls the
  collection back on its own — but a SUCCEEDED one bills until `make down`. The
  hot tier was left up overnight this session (~04:43–13:30 UTC) because the
  session ended between the deploy and the measurement.

## Decisions open for the human seat

**1. What Tier B is for, now that the number exists.** The latency table above
retires the last candidate justification: Tier B is 2.5× slower at this corpus
size, from this vantage, sequentially. SPEC/04 says the disposal of that number
is a PM-seat call. The options it names are to drop the tier-switch demo beat,
or to re-home Tier B's case in M06 where concurrent load lives. Neither is taken
here. What is settled: CLAUDE.md's "do not say faster" is now backed by a
measurement rather than by an absence, and the same file's "same algorithm,
different infrastructure" remains the only accurate description.

**2. Whether retrieval decomposition** (q15) is folded into M04 or takes its own
milestone. It is out of SPEC/04's scope and blocks nothing M04 gates on; the
argument for pulling it in is that `make demo-parity`'s artifact would otherwise
describe a system that changes shortly after. That argument is weak — artifacts
here are sha-stamped by design — so the default is: **leave it deferred.**

**This default holds until the human seat overturns it.** It is a scope
decision, not an engineering one: q15 is outside SPEC/04, blocks nothing M04
gates on, and pulling it in would widen a milestone in flight. An implementer
noticing that q15 still fails is not grounds to fix it here — that is exactly
how a milestone's boundary erodes. Raise it, cite the cost, and wait.
