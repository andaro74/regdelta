# M04 — API + Demo UI  **(IN PROGRESS)**

- Branch: `m04-api-demo`   PR: **#11 (draft)**   Spec: `SPEC/04-api-and-demo.md`
- Base: `main` at `f22b545` (M02 + M03 merged 2026-08-16)
- This pack is written mid-milestone, not at close. Everything below is either
  measured and cited, or named as not yet done. Nothing here is a projection.

## Where it stands

| phase | state |
|---|---|
| 0 — spec amendment (`/resume` auth) | **done**, `pm-spec-reviewer` accept-with-changes |
| 1 — `/query`, `/resume`, `/health`, `scenarios.json` | **done**, and now verified **through the deployed API** |
| 2 — response cache + bypass | **done**, verified through the deployed API: miss 11.2s → hit 247ms |
| infra — API Gateway, CloudFront, UI bucket, dependency layer | **done**, deployed |
| crossref wiring (M03 carryover, M04-blocking) | **done**, SPEC/04's retrieval gate now passes |
| 3 — UI | **done**, and verified in a browser **against the deployed distribution** — see "Phase 3" below |
| 4 — `make demo-parity` + Tier B latency | **done** for the artifact; the latency criterion's **UI conjunct is now met too** — the readout is populated from a real per-query measurement through the deployed API on both tiers (Phase 3) |
| 5 — golden set vs deployed API, both tiers | **done**: `--subset retrieval` 5/5 on both tiers through the deployed API — but the first Tier B card was false, see below |

## Evidence

`evals/history/a7bd28c-s3vectors-full.json` and `4296f04-s3vectors-full.json` —
agent mode, 49-document corpus, two runs three days apart at the same corpus
fingerprint `b70879d76cea`:

    overall            18/20  (90%)     was 16/20 before the crossref fix
    --subset retrieval   5/5            SPEC/04's Done-when clause: MET
    --subset trap        8/8
    --subset smoke       5/5
    --subset timeline    6/7

746 tests, ruff clean, **CI green on #11** — see "CI was red because the system
got better" below. The infra tests now run there too: they were skipping
silently, 713 tests in CI against 733 locally. (Phase 3 takes the suite to
**840 passed, 1 skipped**; the 746 is the figure at the time this paragraph was
recorded and is left as written.)

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

**The latency criterion is a conjunction, and BOTH halves are now met.**
SPEC/04 gates on the artifact recording median and p95 **and** on "the UI
readout populated from a real per-query measurement through the deployed API on
both tiers". The artifact half is the table above. The UI half was outstanding
when this paragraph was first written — raised by `eng-code-reviewer`, which
found the phase table saying "done" against a conjunction — and is closed by
Phase 3 below, which had to add the measurement before there was a number to
read. The two are deliberately the same span from two vantages; neither is a
target, and displaying one is not asserting one (ADR-0012).

### The gate was reviewed, and it had holes

`eng-code-reviewer` on the Phase 4 diff found **two HIGH and four MEDIUM**
defects in `compare()` — each reproduced by running it, not argued:

- **It returned `pass` having compared nothing.** Both tiers present, zero
  scenarios, no failures generated, exit 0. A truncated `evals/scenarios.json`
  would have produced a green gate that asked no questions.
- **Three of the four guards read fields the writer declared** rather than
  re-deriving them: `repeats: 2` beside one run per scenario passed control 2;
  `deterministic: true` beside two visibly disagreeing runs passed the
  determinism guard; a scenario with no `expected_status` made guard 3 inert.
  All three were `.get()` calls, so a rename in the writers would have disabled
  a guard **silently, with no test failing**.
- **`compare()` never checked tier identity**, so an artifact whose `aoss` half
  recorded `tier_resolved_answers: ["s3vectors"]` and a fallback still passed —
  a tier compared against itself, reported as perfect agreement.
- **Nothing asserted "only the infrastructure changed."** The two halves are
  6.5 hours apart and the poller moves the corpus unattended; a document landing
  between them would have been read as a tier difference.
- **`vacuous` counted `["", ""]` as content**, so an uncited answer with no
  deadline scored as substantive evidence.
- **`normalise_citation` erased secondary references** — `"21 CFR 101.65 and
  101.13"` normalised to just `101.65`, so that tier compared *equal* to one
  citing only `101.65`. Agreement by erasure, in the branch whose docstring
  refuses to do it.

All are fixed, each with a test that fails against the unfixed code: **ten
mutations re-introduced, ten caught.** `compare()` now re-derives every gated
quantity from `runs`, and one round-trip test builds a tier half through
`run_scenarios`' own recording path so a field rename cannot leave the guards
inert while the fixtures stay green.

**The recorded artifact was re-judged under the hardened gate and still
passes** (`--compare-only`, `judged_by_sha: 8ab53a8`, exit 0), with the
strengthened checks live: `documents_sha` identical across both halves
(`b70879d76cea`), configs identical, two real runs per scenario, correct tier
resolution, no fallbacks, three of three scenarios substantive. Its answers were
measured at `3966b47`; the file records who judged them and when.

## The deployed stack answers — measured 2026-08-18

The first end-to-end evidence in this milestone, taken against the deployed
stack rather than in-process. `ApiUrl` and `DemoUrl` are CloudFormation outputs;
no environment variable is needed, because `run_evals.resolve_api_url` reads the
output and the Makefile's `demo` target reads the other.

| check | result |
|---|---|
| `GET /health` via API Gateway | 200 `{"status":"ok","tier":"s3vectors"}` |
| `GET /api/health` via CloudFront | 200, same body — the same-origin proxy works |
| `GET /` via CloudFront | the UI page, from the private bucket via OAC |
| `POST /query`, cache bypassed | 200 in ~10s; citations `89 FR 106064`, `90 FR 10592`; `real_deadline` `2028-02-25` |
| response cache, same question twice | miss **11.2s** → hit **247ms** |
| `run_evals.py --subset retrieval` vs the deployed API | **5/5** |
| `/resume` round trip | pause → token → resume returns `status: ok` with a verdict row |
| the four refusals | all four return `{"detail": "not found"}`, varying only in `trace_id` |

Two SPEC/04 Done-when clauses are met by that table and were not before:
**"a cached repeat query returns < 500ms"** (247ms), and **`--subset retrieval`
passes against the deployed API** — on Tier A. The clause says BOTH tiers, so
the AOSS half is still owed and needs a `make up`.

The answer through the deployed API matches
`milestones/M04/answer-parity-3966b47.json` on citations and `real_deadline`
exactly, which is a small cross-check of the in-process instrument against the
deployed one.

**Getting there took three defects that only a real invoke could show**, all in
this session:

1. **No dependencies shipped.** `src/` is first-party Python by policy, and
   nothing packaged fastapi, mangum or langgraph — no layer, no bundling
   anywhere in `infra/`. The function had failed on every invoke since it first
   deployed: `No module named 'fastapi'`.
2. **A named stage puts itself in the path.** With the layer fixed the Lambda
   ran and returned FastAPI's own 404 on every route: an HTTP API's named stage
   is in the event's `rawPath`, so `/api/health` arrived as `/api/health` and the
   app has `/health`. Mangum's base path now comes from `API_BASE_PATH`, which
   the stack sets from the same constant it names the stage with.
3. **The persistent stack's Lambdas shipped 39 non-Python files** — caches and
   `.pytest_cache/` — into zips anyone with `lambda:GetFunction` can download.

## "Verified end-to-end against real AWS" meant something narrower

Corrected 2026-08-18. Every run in this milestone described that way drives the
graph **in-process** — `fastapi.testclient` over `src/api/api.py`, or the
loopback shim — against real S3, DynamoDB, Bedrock and S3 Vectors, configured
from the deployed function's own environment via `evals/local_env.py`. That
exercises the code and the AWS resources it talks to, which is what those claims
were about and what they still support.

What it never did was **invoke the deployed function**. Doing that, for the
first time, returned:

    Unable to import module 'api.api': No module named 'fastapi'

`src/` ships first-party Python only, and nothing had ever packaged anything
else — no layer, no bundling, anywhere in `infra/`. The deployed query Lambda
has failed on every invoke since it first deployed, and no run in this repo
could have seen it, because none of them called it.

Fixed by `make layer` and a `LayerVersion` on the query function; the stack now
refuses to synth without it rather than shipping an empty one. The phase-1 and
phase-2 rows above are re-worded to say *in-process*, which is what they meant.

**The general lesson, recorded because it is the third instance this milestone.**
An instrument that measures something adjacent to the claim reads exactly like
one that measures the claim: the parity gate that would have passed comparing
nothing, the allowlist test that was green in a clean checkout, and now
"end-to-end" that never touched the end. In each case the fix was to ask what
the instrument *cannot* see.

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

## CI was red because the system got better — ruled and fixed

`gh pr checks 11` was `unit fail` before this session started. `f060cea` added
`evals/history/a7bd28c-s3vectors-full.json` and `replay_history.py` began
reporting a gating finding:

    FRAGILE  q14: agent answers disagree across runs —
             2cea737=FAIL a7bd28c=PASS e26d8ef=FAIL
             both failures on: missing required: '101.13(h)'

It read like a determinism finding about the answer layer. It was not.

**`sme-eval-triage` classed the two failures (a) SYSTEM; the question stands and
was not touched.** 21 CFR 101.65(a)(2) requires a 'healthy' claim to meet
§ 101.13 *"with the exception of § 101.13(h) when the nutrient content claim is
made in accordance with paragraph (d)"* — and paragraph (d) **is** the 'healthy'
paragraph, most recently amended by 89 FR 106162, the rule itself. So
`101.13(h)` is not one defensible citation among several; it is the only
exception the section states. Both failing answers did worse than omit it: they
**invented** a carve-out at § 101.13(b)(2)(ii) — one calling it a disclosure
statement, the other a 10% DV "jelly bean" rule. (b)(2) is the definition of an
implied nutrient content claim and is neither. Both self-flagged
`pending_review` at confidence 0.75.

**The defect was in the instrument.** `replay_history.py` pooled every recorded
agent answer *regardless of commit* and flagged any mixed set, so a question
that failed, was fixed, and now passes read as a gating defect. q14's cards span
the commit that wired `crossref_agent` into the verdict prompt — the single
feature q14 measures, and the fix that moved the set 16/20 → 18/20. History is
append-only, so the pre-fix cards never age out: **CI would have stayed red
forever, and every future fix to a failing question would repeat it.**

Ruled by the human seat: **FRAGILE is now directional.** `pass → fail` still
gates — that is how q05 passed at `2cea737` and failed at `e26d8ef` on identical
tokens. `fail → pass` reports as `IMPROVED`. A `fail → pass → fail` sequence
contains a `pass → fail` and still gates, so `IMPROVED` cannot launder an
oscillating question.

Direction is a claim about **time**, which exposed a second defect one line up:
`recorded()` promised "oldest card first" while sorting by filename, i.e.
alphabetically by sha. That is load-bearing rather than cosmetic — q14's cards
sort `2cea737, a7bd28c, e26d8ef` by name against `FAIL, FAIL, PASS` in time, so
by name the sequence reads `FAIL → PASS → FAIL`: a `pass → fail` transition that
never happened, and the gate would still be red. Cards now sort by `at`.

Five mutations checked, five caught. **CI is green** (`746 passed`, `0 skipped`).

**The n=1 caveat is discharged.** `sme-eval-triage` would not treat one green
card as proof of a fix, so a confirming run was recorded:
`evals/history/4296f04-s3vectors-full.json` — 18/20, same corpus
(`b70879d76cea`), **q14 passes again**. The sequence is now
`FAIL FAIL PASS PASS`.

One thing it flagged and nobody acted on, deliberately: q14's literal binds
notation, so a correct answer written as "§ 101.13 applies except its paragraph
(h)" would not contain the substring `101.13(h)`. That did **not** fire here —
neither failing answer used any (h) notation — and loosening the token without
first closing the hedge path in the `except/carve` group would turn q14 into a
question both wrong answers pass. Hardening candidate for the SME seat, not a
fix for this failure.

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
- **The CDK pin does not cover its own transitives.** `aws-cdk-lib==2.263.0` is
  now in `requirements-dev.txt` so CI runs the twenty infra tests it was
  silently skipping — but it pulls eight unnamed packages, three of which float.
  One is **`jsii`**, the Python-to-Node bridge that runs the bundled JavaScript
  doing asset staging, which is exactly what the allowlist tests exercise. A
  jsii release can move staging behaviour under a frozen `aws-cdk-lib` pin, and
  then CI tests something the laptop does not — the drift `requirements-dev.txt`
  exists to end. Only two jsii versions satisfy the range today, so the exposure
  is this week's, not the constraint's. Pinning transitives is a dependency
  decision and is **not taken**; `security-reviewer` M1.
- **The deploy's CDK version is constrained by nothing.** `infra/requirements.txt`
  is installed by no automated path — `cdk deploy` runs whatever is in the
  operator's venv. So the floor is advisory, and `test_the_dev_pin_is_not_below_the_deploy_floor`
  only stops the test pin dropping below it; it cannot make CI and a deploy
  agree. `security-reviewer` L6.
- **`dropped_citations` was recorded as `[]` on every response without ever
  being measured** — `src/api/api.py:_shape` did not emit the field the shim has
  emitted since q03, so the artifact read "nothing was dropped" where nothing
  was asked. The field is now in `_shape` (the two mappings are meant to be the
  same one), but **the recorded artifact predates that**: its
  `dropped_citations: []` entries mean *not measured*, not *none dropped*.
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

## Tier B answered nothing, and the card said 5/5 — measured 2026-08-19

With the hot tier up, `run_evals.py --subset retrieval` scored 5/5 against the
deployed API and was reported as the AOSS half of Phase 5. It was not evidence
of anything.

All five answers came back `cache: hit`. They were served from response-cache
entries the **Tier A** run had written minutes earlier, inside the 1h TTL. The
collection's own `SearchRequestRate` settles it independently:

| window (UTC) | AOSS search requests | what ran |
|---|---|---|
| 03:01 | **2** | the "5/5 Tier B" run — five questions |
| 03:07–03:08 | **16** | the same five, cache bypassed |
| 03:14–03:15 | **16** | the recorded card, `e9ba788-aoss-retrieval.json` |

Five questions cost AOSS sixteen searches when they actually reach it. Two is
what "the hot tier is up and the cache answered" looks like.

**The instrument, not the system.** Re-run honestly, Tier B passes 5/5 on the
same corpus fingerprint (`b70879d76cea`, 49 documents) — the card is
`evals/history/e9ba788-aoss-retrieval.json`, `cache_statuses: ["bypass"]`.
SPEC/04's clause is met on both tiers. What was broken was the only thing that
could have told the difference.

### Why it was possible

SPEC/04 parity control 1 already requires both tier runs to bypass the response
cache. It was written for `make demo-parity` — and demo-parity is not the
command that writes the scorecards. `run_evals.py` had **no cache handling of
any kind**, while `record()` names every card `{sha}-{tier}-{subset}.json` and
every progress claim in this repo is a delta against those files. A tier in a
filename, and nothing forcing the tier to have done the work.

This is the milestone's recurring defect, for the fourth time: *an instrument
that measures something adjacent to the claim reads exactly like one that
measures the claim.* Adjacent here is one cache lookup away.

Fixed in `e9ba788`: `ask()` bypasses both ways, the per-question record keeps
what the server said it did, and `--record` **refuses** rather than warns —
under a green 5/5 a warning is not read. `miss` counts as a violation and not
only `hit`, because on a run that asked for a bypass it means the cache was
consulted anyway; the control is already broken and the next question is the
one that comes back a hit.

The first cut of the rule was too broad and an existing test caught it. A
transport error leaves no response to carry a cache status, which is not the
same as an answer of unknown provenance — the guard was refusing to record
partially-failed runs, which is precisely what `tests/test_scorecard_audit.py`
exists to pin.

### What is still not measured

The card records `tier` from `GET /health`, which reports what SSM is
**configured** to, not what answered. The router falls back to `s3vectors` on
any AOSS error and reports it only through `retrieve_traced` — which
`graph/nodes.py:221` discards and the API never surfaces. So a broken AOSS
collection would still produce `/health: aoss`, a green card filed under
`-aoss-`, and every answer served by Tier A.

`router.py`'s own docstring names this failure ("a silent fallback is how two
S3 Vectors runs get reported as two-tier coverage"); the guard exists in the
in-process harness and not on the deployed path. The card now states the limit
as `tier_source` rather than leaving it implied. Closing it means carrying the
`Resolution` through the graph onto the response — which SPEC/04's UI clause
needs anyway for the tier indicator that must visibly flip.

Corroborated for this run by the AOSS metric above, which is the strongest
evidence available without that change.

## A cold Lambda served the wrong tier for 60 seconds — measured 2026-08-19

Found by disbelieving an observation. After deploying the answering-tier change,
the API reported `tier: s3vectors` while SSM plainly held the AOSS endpoint and
the collection was `ACTIVE`. The full sequence against the deployed stack:

| time (UTC) | container | `/health` |
|---|---|---|
| 02:58 | fresh | `s3vectors` |
| 03:00 | same, now warm | `aoss` |
| 03:05 | fresh again, redeploy replaced it | `s3vectors` |

`router._cache` seeded `at` to `0.0` and guarded the refresh with
`now - at > _TTL`, so the first call in a process asks `time.monotonic() > 60`
— **a question about how long the machine has been up**, not about how stale
the value is. On a laptop `monotonic()` is thousands of seconds, so the lookup
always fired and the code read as correct; every test in this repo ran that way.
In a Lambda microVM the clock starts near zero at boot, so for the first minute
of every container's life `active_endpoint()` returned the seeded `None`
**without consulting SSM at all**, and the router served S3 Vectors while SSM
held an AOSS endpoint — silently, with no `fallback_reason`, because nothing
failed.

`GET /health` reads the same function, so the endpoint whose entire job is to
report which tier is live was structurally unable to notice.

**This is the third form of the same M04 defect and the worst of the three.**
The first two produced a false *scorecard*; this one produced false *routing* on
real user questions. `reset_cache()` had the identical clock dependency — it
cleared `at` to `0.0`, so on a cold process the next call would hand back the
endpoint it was called to forget, which is exactly `make demo-parity`'s tier
flip.

Fixed with an explicit `fetched` flag, which no clock origin can fool. Five
tests, seeded with the module's own import-time cache state so they exercise the
real cold start rather than one invented to fail; all five fail against the
unfixed code with "SSM was never consulted".

Verified by prediction, on the deployed stack: a fresh container now reports
`aoss` on its first request, where before the fix it reported `s3vectors` for a
full minute.

## Which tier answered is now on the response — measured 2026-08-19

`graph/nodes.py` called the untraced `router.retrieve` and discarded the
`Resolution`, so the only statement anywhere about which tier answered was
thrown away and the API reported `active_tier()` instead — an SSM read of what
the system is **configured** to. Both `_shape` mappings now carry `tier` and
`fallback_reason`, and `run_evals` takes the card's tier from what answered,
recording `tier_source` so the weaker claim can never pass for the stronger one.

Demonstrated against real code rather than argued. With SSM pointing at a
collection that does not answer:

    active_tier()  (configured) : aoss
    response tier  (observed)   : s3vectors
    fallback_reason             : AossError: refusing to sign a request to ...
    chunks returned             : 8

The fallback still protects availability — the answer comes back — it simply
cannot hide any more. Before this, that run produced a green card filed under
`-aoss-`.

### Phase 5, Tier B, on evidence

`evals/history/8a0cdea-aoss-retrieval.json`:

| field | value |
|---|---|
| `tier` / `tier_source` | `aoss` / **observed (router Resolution)** |
| per-question tier | `aoss` ×5 |
| `cache_statuses` | `["bypass"]` |
| `fallbacks` | `[]` |
| result | **5/5** |

Corroborated independently by the collection's own `SearchRequestRate`: **16
search requests** inside the run's window, against the 2 that the false card
produced. Two unlike instruments — the system's self-report and an AWS counter
it does not write — agreeing.

**Not closed:** `router.hydrate` has its own silent AOSS→S3V fallback on the
crossref lane, so one response can still span two tiers without saying so. The
`tier` field describes the main retrieval call. Recorded, not fixed.

## The internet-facing role's wildcard grants — closed 2026-08-19

`QueryFn` is the only role in this account driven by **anonymous requests**:
SPEC/04 declares `/query` unauthenticated and CloudFront serves it publicly. It
held three `Resource: "*"` grants carrying `# TODO: scope`, deferred to SPEC/05.
Security review pulled them forward — the risk changed character the day the
role stopped being reachable only by credential-holders.

| grant | was | now |
|---|---|---|
| `bedrock:InvokeModel` | `*` | 2 inference profiles + their foundation models in 3 regions + Titan |
| `s3vectors:QueryVectors\|GetVectors` | `*` | the vector bucket and its `index/chunks` |
| `aoss:APIAccessAll` | `*` (every collection in the account) | `collection/*` in this account and region |

Every ARN was read off the live resource rather than inferred. Two would have
been wrong by analogy: **s3vectors ARNs carry region and account** and use
`bucket/NAME`, not the plain-S3 `arn:aws:s3:::name` shape; and a **cross-region
inference profile is not what Bedrock authorises** — it evaluates `InvokeModel`
against the foundation model in whichever region it routes to, so granting only
the profile denies intermittently, by region, and not in the regions a smoke
test happens to hit.

### The review found the justification was false

`core_stack` justified the remaining `collection/*` breadth by citing the AOSS
data access policy as "the control that actually admits the request". It wasn't:
that policy put the reindex role and the query role in **one principal list**
with `aoss:*` at collection and index level. The internet-facing role could
`DeleteIndex` and `WriteDocument` on the corpus index the cited deadlines are
drawn from — corpus poisoning, reachable from the same role that feeds untrusted
Federal Register text to an LLM.

`search_stack.py` already contained the argument against this. An earlier review
made exactly this point about the human operator, gave it its own read-only
statement, and wrote that "a *new* widening must not ride out on an existing
TODO". The same fix applies: the reindex role keeps `aoss:*`, the query role
gets `DescribeIndex` + `ReadDocument` at index level, which is all
`aoss_tier.py` issues. **An existing test pinned the wrong state**, asserting
the query role *keeps* `aoss:*`; it now asserts the opposite.

### And a bug the scoping itself introduced

The policy resolved `config.MODEL_*` in the **synth** process — the operator's
shell — while the function resolved them again from its own environment, which
set none of them. They agreed only when the deployer had nothing exported, and
`config.py` invites the divergence in a comment ("Raise MODEL_VERDICT to Opus
4.7 once account model access is granted"). Export it, deploy, and the policy
grants 4.7 to a function still invoking 4.6 — `AccessDenied` on the verdict node
of every anonymous query. Under `Resource: "*"` that was impossible; **the
narrowing created it.** Now pinned into the function's environment so the two
are the same string by construction.

Verified by running: `MODEL_FAST`, `MODEL_VERDICT` and `EMBED_MODEL` are on the
deployed function and each appears in the grant, and `--subset retrieval` is
**5/5** against the deployed API — which exercises the Bedrock, Titan and S3
Vectors grants together.

**Not verified:** the AOSS grant and the data access split. The hot tier was
destroyed before both changes, so the narrowed collection ARN and the read-only
statement have not met a live collection. The next `make up` settles it, and
until then this is stated rather than claimed.

**Raised, not done:** the `aoss` grant could be pinned to the real collection id
by moving it into the ephemeral search stack, which would also make it vanish
with `make down`. Separately, the janitor's nightly OCU guard **does not work at
all** — it calls `delete_stack` with no `RoleARN` while holding only
`DeleteStack` and `DescribeStacks`, so it reports `delete-initiated` and lands in
`DELETE_FAILED`. Correctness rather than security, and the TODO's wording implies
it works in a degraded way when it does not work at all.


## Phase 3 — the demo page — measured 2026-08-19

`ui/index.html` and `ui/verdict.js`, served from the existing S3 + CloudFront
distribution (`DemoUrl`), calling the API same-origin at `/api/*`. Static, no
dependencies, no build step. Everything in the table below was read off the
deployed page in a real browser against the deployed stack, not from a test.

| SPEC/04 UI clause | how it is met | observed |
|---|---|---|
| question box | textarea, ⌘/Ctrl+Enter to send | ✅ |
| one button per entry in `evals/scenarios.json` | the page **fetches** `scenarios.json`, which the stack writes from the canonical file at synth | 3 buttons, ids `healthy-claim` `red-no-3` `needs-review` |
| verdict table with citation links | `product / trigger / required_change / real_deadline / confidence / citations` | the full Nordvale row |
| confidence badges | coloured at **0.7**, which is `config.CONFIDENCE_HITL_THRESHOLD` — not a number invented here | `0.97` green |
| "needs human review" state | `needs_input` / `pending_review`, with the reason | ✅ `needs-review` |
| active-tier indicator that visibly flips | **from the response**, see below | ✅ |
| cache-state label, exactly one of four | **from the response** `cache` | `bypass`, `miss` and `hit` all observed |
| cache-bypass control | checkbox → `no_cache: true` | ✅ |
| retrieval latency readout | **from the response** `retrieval_ms` | 256 ms Tier A |
| cross-tier comparison panel, explicit equal / differs | citations as **sets**, `real_deadline` **exactly** | see the panel section |

### The readout had nothing to read, so the measurement was added

SPEC/04's Tier B latency criterion is a conjunction and the artifact half was
met at Phase 4. The other half — "the UI readout is populated from a real
per-query measurement through the deployed API on both tiers" — had no field to
read. `Resolution` carried `tier` and `fallback_reason` and no timing, so the
only number a browser could produce was **its own round trip**: 10.5 s on this
question, of which retrieval is 256 ms. **97% of it is Bedrock.** Printing that
under the words "retrieval latency" would have been an instrument measuring
something adjacent to the claim — the fifth instance in this milestone, in the
readout whose whole purpose is to compare two retrieval tiers.

So `retrieve_traced` now times its whole self and carries `elapsed_ms` out on
the `Resolution` → `retrieval_ms` on the state → `retrieval_ms` on **both**
`_shape` mappings. That is deliberately the **same span** `make demo-parity`
records for the artifact — it times `router.retrieve`, which is
`retrieve_traced` plus a tuple index — so the two are one quantity from two
vantages, which is what SPEC/04 means by "different instruments". The timing
wraps the call rather than sitting at each `return`, so the fallback path is
timed by construction; on a fallback the number spans both legs and
`fallback_reason` is on the same response to say why it is large.

The browser's stopwatch is still shown, in its own box, labelled `round trip ·
client stopwatch, incl. generation`. Two numbers, two labels, and neither
borrows the other's meaning.

### Every instrument reads the field that describes its own request

The tier badge, the cache label and the latency readout all come from the
`/query` **response body**. `/health` is on the page too — in the header,
labelled `configured tier`, with a tooltip saying it reports what SSM holds and
not what answered — and the badge shows `≠ configured` when the two disagree.
That disagreement is the information; substituting one for the other is the
defect. A tier badge sourced from `/health` would have been structurally unable
to notice the cold-start bug recorded above, where `/health` said `s3vectors`
for the first sixty seconds of every container's life while SSM held an AOSS
endpoint.

**A cache hit is rendered as provenance, never as a live reading.** On a hit the
API returns the STORED body, so `tier`, `fallback_reason` and `retrieval_ms`
describe the request that populated the cache — possibly the other tier, up to
an hour ago. Observed, on the deployed page:

    RESPONSE CACHE     hit          stored answer replayed — nothing was retrieved
    TIER THAT ANSWERED s3vectors    stored — the tier that answered when this was cached
    RETRIEVAL LATENCY  259 ms       stored — measured when this answer was cached
    ROUND TRIP         170 ms

That 170 ms is also **SPEC/04's "a cached repeat query returns < 500 ms"**,
measured for the first time in a browser through CloudFront rather than with
`curl` — the vantage the clause is about.

### The panel's judgement is in a file that can be run

`ui/verdict.js` holds what the cross-tier panel decides — citation URLs, which
responses may become a tier observation, and the equal/differs verdict — and
`tests/ui_verdict_spec.js` drives it under node. The page **calls** it rather
than keeping a copy, and a test asserts that: a tested `verdict.js` beside a
page with its own duplicate would be a suite pinning a function the demo never
runs, which is this milestone's defect class wearing a green check.

It refuses two things, and the first is the whole control:

1. **A cache hit is not recorded as a tier observation.** Nothing was
   retrieved, and filing the stored body under `tier` would file one tier's
   answer under the other's name — the panel would then report `equal` by
   construction and be measuring the response cache. This is SPEC/04 parity
   control 1, in the browser, and it is not hypothetical: the Tier B scorecard
   recorded above read 5/5 having reached AOSS zero times, exactly this way.
   Observed live, on a `hit`: *"This response was served from the cache, so it
   is not evidence about any tier."*
2. **A response with no tier is not recorded.** A `needs_input` run never
   reached retrieval.

And it reports three caveats beside the verdict rather than folding them into
it, because each says what the verdict is *evidence of* rather than whether the
two sides matched: `sameTier` (a determinism observation, not a cross-tier one —
the defect engineering review found in Phase 4's `compare()`), `vacuous`
(agreement about nothing, the artifact's guard 4), and a cache note when either
side is not `bypass` — a `miss` counts, not only a `hit`, because on a request
that asked for a bypass it means the cache was consulted anyway.

Observations are keyed by the **sha-256 of the question and profile**, not by
scenario id, for the reason the artifact records `input_sha256`: "scenario 1" is
not a stable subject. They live in `localStorage` because the tier flip takes a
`make up` — twenty minutes, during which a viewer reloads the page — and the
panel renders whatever is retained as soon as a scenario is selected, before
anything is asked, so the retention can be checked without spending a Bedrock
call to find out.

### Citation links, checked against the live sites

Three notations, all named by the regulatory-domain skill, each URL shape
verified by following it rather than inferred:

| citation | link | resolves to |
|---|---|---|
| `89 FR 106064` | `federalregister.gov/citation/89-FR-106064` | the healthy final rule |
| `2024-29957` | `federalregister.gov/d/2024-29957` | **the same document** |
| `21 CFR 101.65(d)(2)` | `ecfr.gov/current/title-21/section-101.65#p-101.65(d)(2)` | eCFR emits exactly that anchor id |

**Anything unrecognised is rendered as plain text, never as a guessed link.** A
citation a reader cannot follow is a visible limit; a link that quietly lands on
the wrong document is the failure this product exists to expose. Sixteen hostile
inputs were probed during security review, including `javascript:` and `data:`
payloads — all returned `null`.

**Every citation the three scenarios actually produce was followed**, not just
the three shapes: `89 FR 106064`, `90 FR 10592`, `90 FR 4628`, `91 FR 50475`,
`2024-29957`, `2025-03118`, `21 CFR 74.303`, `21 CFR 80.32(h)`,
`21 CFR 101.65(d)(2)` — all 200, and both eCFR paragraph anchors
(`id="p-80.32(h)"`, `id="p-101.65(d)(2)"`) are present in the live pages.
`91 FR 50475` resolves to *Micro-Tracers, Inc.; Response to Objections* — the
stay-lift document ADR-0007 is about.

One first-pass observation withdrawn: `91 FR 50475` returned **503** on the
first check and was about to be written up as a limit of the corpus. It was
transient — 200 on retry, which is why it is stated here as measured twice
rather than once. A single failed request is not a finding.

### What the page deliberately does not do

**It never prints the `resume_token`.** A `needs_input` response carries one — a
bearer capability bound to that thread — and the page says a capability was
minted and shows only the `thread_id`. This page is screenshotted into this
directory. There is no resume control: SPEC/04's UI list requires the review
**state** to render, not a resume round trip, and `make test` already gates the
resume contract including its four byte-identical refusals.

### The screenshots

`milestones/M04/screenshots/`, taken by a headless Chrome against
`DemoUrl` over the DevTools Protocol.

**Not `--virtual-time-budget`.** The first attempt used it and produced a page
reporting a **10 ms round trip for a request that really took eleven seconds** —
the flag advances a virtual clock and `performance.now()` inside the page
follows it. A screenshot filed as evidence of a latency readout must not contain
a fabricated latency, so the driver runs in real wall-clock and polls the page
for a completion signal instead. Caught by disbelieving the number, which is how
every real finding in this milestone was found.

A second harness defect, same class: the driver killed Chrome after capturing,
so `localStorage` never flushed its leveldb and the cross-tier panel came back
empty on the next run — *which reads exactly like a page that never stored
anything*. It closes the browser now and waits for it to exit. Verified by
prediction: a 30-byte Local Storage log before, 1248 bytes after, and the panel
showing the retained Tier A observation on a cold browser start.

| file | shows |
|---|---|
| `01-healthy-claim-and-cross-tier-equal.png` | **both Done-when clauses in one page**: the full Nordvale table answered live against the deployed stack (`s3vectors`, `bypass`, retrieval **302 ms** against a 14.05 s round trip), and beneath it the cross-tier panel — retained `aoss` beside live `s3vectors`, both `bypass`, verdict **EQUAL** |
| `02-needs-human-review.png` | the `needs_input` state, its reason, and a minted capability that is not displayed |
| `03-cache-hit.png` | `cache: hit`, a **178 ms** round trip, and tier and latency both labelled `stored` |

All three are the SAME deployed build, re-taken after the engineering review
below changed what the page says. Evidence assembled from two different builds
would be a small version of the thing this milestone keeps finding.

**One limitation, named rather than left to be inferred.** No screenshot shows
the tier badge reading `aoss` *on this build*: the page was corrected after the
hot tier came down, and re-shooting it costs another `make up`. The panel's
retained `aoss` side is from the live Tier B run, and the Tier B badge itself is
recorded in the table above and in the response body it was read from. A
screenshot of the earlier build showing `aoss` exists and is deliberately **not**
committed, because it carries the sentence F1 retracted.

### Tests

`tests/ui_verdict_spec.js` (18 assertions, run by
`tests/test_ui_verdict.py`) covers the panel's judgement; `tests/test_ui_verdict.py`
covers the wiring — that the page loads the judgement it is tested on, that the
buttons come from the canonical scenarios file, and that the PM/SME commentary
in that file is not published to an anonymous distribution.
`tests/test_retrieval_latency.py` covers the measurement, in the router, in the
node and on both `_shape`s.

**The rendering itself is not unit-tested**, deliberately: there is no DOM in
this suite, adding one would be a dependency, and asserting that a `<td>` exists
pins the template rather than the behaviour. The rendering's evidence is the
screenshots above — SPEC/04: "a browser procedure with no record is rehearsal,
not a criterion."

**31 mutations re-introduced, 31 caught** — 7 for the latency measurement, 14
for the UI judgement, 4 for the asset allowlist below, and 6 for the page's
rendering (the engineering-review section names those six).

### Security review of Phase 3

`security-reviewer` on the diff: **no HIGH**, one MEDIUM and three LOWs, each
reproduced by running.

**MEDIUM, fixed.** `s3deploy.Source.asset(UI_SRC)` carried no allowlist. The UI
bucket is the one bucket served to **anonymous callers with no IAM in the way** —
the reader needs only the distribution URL, which is a `CfnOutput` — and
`infra/asset_policy.py` was written this milestone for exactly this class and
had been applied to Lambda code and not here. Measured against a `ui/` seeded
with plausible strays:

    ['.env', '__pycache__/x.pyc', 'index.html', 'notes.md', 'verdict.js']

Now `asset_policy.UI_ASSET_EXCLUDE`, an explicit two-file allowlist rather than
`!*.{html,js}` — a scratch `index.old.html` or a vendored script should not
publish itself — carried with `ASSET_IGNORE_MODE`, because `exclude` without its
mode stages the opposite of what it reads as.

**And the test for it was green with the fix deleted.** Four mutations, the
first pass caught one. `test_the_stack_applies_that_allowlist_to_the_ui_bucket`
synthesised the real stack over the real `ui/`, which holds two files and has
nothing to leak, so removing the allowlist from the stack entirely changed
nothing it could see. That is the *same* vacuous-green shape `security-reviewer`
found in the first version of the Lambda-asset test — reproduced one milestone
later, in the test written to close its sibling finding. It now redirects the
stack's own `UI_SRC` at a planted tree, the way `stub_layer` redirects
`LAYER_SRC`. Four mutations, four caught, including one proving `ignore_mode` is
load-bearing here too.

**LOW, fixed.** The one path that renders a body wholesale — the `>= 400` banner
— now redacts first. No error path returns a `resume_token` today (both 4xx
bodies are `{detail, trace_id}`; the token is minted only on a 200), so this
changes nothing now. It is there because "never print the capability" was
resting on an invariant held in `api.py` rather than in the page.

**LOW, recorded.** The scenario projection is a top-level whitelist, so a
reviewer note nested inside a `company_profile` would publish. Harmless today;
a recursive projection needs a schema for a field whose shape is the PM seat's
to choose.

**LOW, declined — for the human seat.** No `ResponseHeadersPolicy` (CSP,
`nosniff`) on the distribution. Defence-in-depth with no sink found: every
model-generated string goes through `textContent` or `createTextNode`, every
`innerHTML` is a static literal or passes `escapeHtml`, and `citationUrl`
returns only literal `federalregister.gov` / `ecfr.gov` prefixes concatenated
with digit-only captures. A meaningful CSP would also mean moving the page's
inline script into its own file. Named rather than left to be found.


## The tier flip, in the browser — measured 2026-08-19

`make up`, then the same question through the deployed page on the same browser
profile that already held the Tier A observation, then `make down`. The hot tier
was up for about twenty-five minutes.

**And it is down**, checked four ways rather than on the exit code — the janitor's
nightly OCU guard does not work (see below), so `make down` is the only thing
that stops the billing and "it said destroyed" is not the same as "it is gone":
the stack does not exist, `list-collections` returns nothing,
`/regdelta/search/endpoint` is `ParameterNotFound`, and `/api/health` reports
`s3vectors` again.

### `/health` before and after, and why it is the weaker claim

| when | `GET /api/health` | what answered a `/query` |
|---|---|---|
| hot tier down | `s3vectors` | `s3vectors` |
| hot tier up | `aoss` | `aoss` |

SPEC/04's Done-when says "`/health` reports the correct tier before and after
`make up`", and it does. The page shows it in the header as `configured tier`
and takes its **badge** from the response, because those two answer different
questions and this milestone has already recorded the case where they disagreed
for sixty seconds of every container's life.

### Tier B, through the deployed API, cache bypassed

    tier             'aoss'
    fallback_reason  None
    cache            'bypass'
    retrieval_ms     897.6
    status           'ok'
    citations        ['89 FR 106064', '90 FR 10592']
    deadlines        ['2028-02-25']

**This is what settles the two IAM changes** that were left stated rather than
claimed when the hot tier came down last session. A wrong `aoss:APIAccessAll`
scope, or a data-access split that did not actually admit the query role, both
surface the same way: `AossError` in `fallback_reason`, `tier: s3vectors`, and
an answer served by Tier A. Neither happened. Verified live:

- **`aoss:APIAccessAll` narrowed from `*` to `collection/*`** in this account
  and region — the internet-facing role reached the collection.
- **The data-access split**: the reindex role keeps `aoss:*`, the query role has
  `aoss:DescribeIndex` + `aoss:ReadDocument` at **index level only**. Those two
  permissions are all `src/retrieval/aoss_tier.py` issues, and they are
  sufficient — the query returned eight chunks and a cited answer. The
  internet-facing role no longer holds `DeleteIndex` or `WriteDocument` on the
  corpus index the cited deadlines are drawn from.

The stack itself is the other half of the evidence: `HydrateOnDeploy` completed,
so the reindex role's `aoss:*` still works for the writer it was kept for.

### The panel: EQUAL

`milestones/M04/screenshots/04-cross-tier-equal.png`.

| | previous tier | current tier |
|---|---|---|
| tier | `s3vectors` | `aoss` |
| at | 05:30:35Z | 11:12:39Z |
| cache | `bypass` | `bypass` |
| `citations[]` as a set | `89 FR 106064`, `90 FR 10592` | `89 FR 106064`, `90 FR 10592` |
| every `real_deadline` | `2028-02-25` | `2028-02-25` |

> **EQUAL** — citations agree as sets and every real_deadline matches exactly —
> s3vectors vs aoss. The answer did not change when the infrastructure did.

No caveat fired: two different tiers, both `bypass`, and not vacuous. The two
observations are 5h42m apart across a real `make up`, and the second was
retained from a **cold browser start** — the panel had been closed and reopened
in between, which is the reload the twenty-minute flip makes inevitable.

This is the UI counterpart of `make demo-parity`, and it agrees with the
artifact: `answer-parity-3966b47.json` recorded the same citation set and the
same date for `healthy-claim` on both tiers, from the in-process harness. Two
unlike instruments, same answer.

### The latency readout on both tiers — the criterion's UI conjunct, closed

| tier | `retrieval_ms`, deployed | round trip | artifact median (laptop, in-process) |
|---|---|---|---|
| A — S3 Vectors | 256 / 270 / 294 ms | 10.5 s | 354.1 ms |
| B — AOSS | 464 / 897.6 ms | 11.3 s | 889.3 ms |

SPEC/04: "the UI readout is populated from a real per-query measurement through
the deployed API on **both tiers**". It is, and the numbers above are individual
measurements displayed on the page, not a summary.

**Read them for what they are.** These are n=1 per row, from a Lambda in-region
rather than a laptop, and the two Tier B numbers differ by a factor of two —
which is exactly why the criterion puts the gating median and p95 in the
artifact and leaves the page reporting. What the deployed vantage does add is
that it agrees in **direction** with the artifact: Tier B slower on both
instruments. That was the open question the artifact's own caveat named — "a
production vantage could move the ratio and has not been measured" — and it did
not move it. It remains a report, not a claim (ADR-0012), and **no target is set
here either**.

Retrieval is **2.5–8%** of what a viewer waits through. That ratio is the whole
argument for the readout existing: the browser's own stopwatch, printed under
the words "retrieval latency", would have been a number about Bedrock.

### Two harness defects, same shape as everything else this milestone

Both in the screenshot driver, neither in the product, both recorded because
they are the same defect class and both would have produced *plausible*
evidence.

1. **`--virtual-time-budget` fakes the clock.** The first screenshot showed a
   **10 ms round trip for a request that took eleven seconds** — the flag
   advances a virtual clock and `performance.now()` follows it. A screenshot
   filed as evidence of a latency readout, containing a fabricated latency. The
   driver now runs in real wall-clock over the DevTools Protocol.
2. **The wait predicate matched a static heading.** The first cross-tier attempt
   waited for the text `CROSS-TIER`, which is the panel's `<h2>` and is on the
   page before anything is asked, so it captured 0.5 s after load and produced a
   screenshot of four em dashes that could have been filed as "the panel". It
   waits for text only the *finished* comparison emits.

Neither cost anything but time, and both are the milestone's recurring lesson
pointed at the instrument rather than the system: *ask what the instrument
cannot see.*


## Engineering review of Phase 3 — and what it found in the panel

`eng-code-reviewer`, fresh context, on the Phase 3 diff. It cleared the question
that mattered most and then found two things worth more than the clearance.

**Cleared, by reading both sides.** `Resolution.elapsed_ms` is the same span
`measure_latency` records — `retrieve_traced` brackets `_resolve`,
`measure_latency` brackets `router.retrieve`, and the delta is one
`dataclasses.replace` and a tuple index. Both include the Titan embedding, the
engine round trip and `_finish`; both run k=8. They are **independent
stopwatches over that span** — the artifact does not read `retrieval_ms` — so
this change does not make the artifact circular. Also cleared: the cache-hit
provenance end to end, the `at`-string sort (both are `toISOString`, so
lexicographic is chronological), and the hosting tests' non-vacuity.

### F1 — the panel made a causal claim its own data cannot support

On `equal` it printed:

> citations agree as sets and every real_deadline matches exactly — s3vectors vs
> aoss. **The answer did not change when the infrastructure did.**

The second sentence asserts that infrastructure was the only variable. Nothing
on the page checked that. `evals/run_demo_parity.py` refuses precisely this
comparison when the two halves recorded a different `documents_sha` — *"Only the
infrastructure may differ between them"* — because the daily poller once moved
the corpus from 4 to 34 documents unattended between two halves. The `/query`
response carries no corpus fingerprint, so the panel has nothing to check it
with. And it was not hypothetical: the first committed evidence screenshot
showed that sentence under two observations **5h42m apart**.

SPEC/04 asks for an explicit equal / differs verdict. It does not ask for a
cause, and the verdict was never the problem. The panel now states the verdict,
reports **how far apart the two sides are**, and says which instrument does gate
the corpus:

> The two sides are 0h 22m apart. This panel compares two answers; it cannot
> check that only the infrastructure changed between them — the corpus is not
> pinned here. `make demo-parity` is what gates that, by refusing any comparison
> whose halves recorded a different documents_sha.

### F2 — control 1's enforcement was in the one file no test executed

`ui_verdict_spec.js` proves `observationFrom` **returns** `ok: false` on a cache
hit. Nothing proved the page **acts** on it. The reviewer named two one-line
mutations that left every assertion in the diff green and the file parsing:

| mutation | what ships |
|---|---|
| `if (taken.ok) {` → record unconditionally | a cache hit filed under `tier`; the panel then compares one tier's stored answer against the other tier's name and reports `equal` by construction — **SPEC/04 control 1 defeated in the browser**, the same substitution that made a Tier B scorecard read 5/5 having reached AOSS zero times |
| `const ms = body.retrieval_ms` → `const ms = roundTripMs` | the browser's own stopwatch under the words "retrieval latency" — **the exact defect `retrieval_ms` was added to prevent**, undone in the render |

Two changes close it. The decisions moved **into** `ui/verdict.js`
(`latencyReadout`, `cacheReadout`, `uncitedRows`), so the page renders what they
return and `roundTripMs` is not in scope for that box at all. And
`tests/ui_dom_spec.js` now **runs the page** — a real headless browser against
scripted API responses over a temporary local http server, reading the rendered
text back. Real `fetch`, real same-origin paths, real `localStorage`, and
127.0.0.1 is a secure context so `crypto.subtle` works.

Its sequence is the test: Tier A bypassed, then Tier B **as a cache hit carrying
deliberately different citations and a different deadline**, then Tier B
bypassed and agreeing. If the page recorded the hit, the middle step reports a
comparison instead of refusing one — visibly, as `differs`.

**Six mutations, six caught**, including both of the reviewer's. It skips with a
stated reason if no browser is found (exit 64 → pytest skip), never passes.

**And it runs in CI rather than skipping there**, which is the question worth
asking about any test that can skip — this repo has already had twenty infra
tests skipping silently in CI while passing locally. Measured on the gate:
`842 passed, 1 warning`, **zero skipped**, against `841 passed, 1 skipped`
locally, where the one skip is `test_dev_requirements.py` asserting the CI
environment and not a laptop's. Chrome is on the GitHub-hosted runner, so the
page is actually driven on every PR and F2's closure is enforced by the gate.

On the reviewer's direct question about
`test_the_page_uses_the_judgement_it_is_tested_on`: its verdict was "not
theatre; a smaller test than it reads as", and that is right. It catches "the
page kept its own copy", which is real, and nothing more. The module docstring
no longer puts the weight of the rendering on it.

### F3, F4, F5, F6 — four ways the page said nothing when it should have spoken

- **F3.** The cache note's fallback branch read `"answered fresh and stored"`
  for every non-`hit`/`bypass`/`disabled` value. A `miss` on a **paused** run is
  not stored — `response_cache.cacheable()` refuses any body carrying a resume
  capability — so the note asserted a write that never happened. It now says
  which, from `status`.
- **F4.** `saveStore` swallowed every exception, so a browser in private mode or
  over quota lost the previous tier and the panel rendered the same "ask a
  question" hint it shows when nothing was ever asked. A retention failure and a
  fresh start were indistinguishable — and the demo beat depends on retention
  across a `make up` and a page reload. It returns a boolean now and the panel
  says the write was refused.
- **F5.** `crypto.subtle` is undefined outside a secure context; the rejection
  was unhandled in both callers, so on a plain `http://<lan-ip>` the answer and
  instruments rendered normally while the panel silently never updated. Caught
  and reported. Deployed exposure was nil (CloudFront is `REDIRECT_TO_HTTPS`);
  it is listed because the failure mode was silence, the same as F4.
- **F6.** The "no citations" guard fired only on the **response-level** list, so
  a single uncited row inside an otherwise cited `ok` answer rendered a blank
  cell and said nothing. Under this repo's rule that is a bug, not a style
  issue. `uncitedRows` finds them and the page names them.

The reviewer's process note — that `milestones/` was absent from the diff under
review — was true when it read the tree and is not now: the pack and the
screenshots are committed at `e739c35`, which landed while it was running.
