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
| 3 — UI | not started |
| 4 — `make demo-parity` + Tier B latency | **done** for the artifact; the latency criterion's **UI conjunct is outstanding** (see below) |
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
silently, 713 tests in CI against 733 locally.

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

**The latency criterion is a conjunction and only half of it is met.** SPEC/04
gates on the artifact recording median and p95 **and** on "the UI readout
populated from a real per-query measurement through the deployed API on both
tiers". The artifact half is done; the UI half is Phase 3 and is not started, so
this criterion must not be read as closed at milestone close. Raised by
`eng-code-reviewer`, which found the phase table said "done" against a
conjunction.

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
