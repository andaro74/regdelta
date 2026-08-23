# SPEC/08 — The UI Surface, Against The Deployed Stack

## The claim

**The demo page, as served by CloudFront, renders SPEC/04's verdict table and
its human-review pause correctly when the answers come from the real stack —
and never prints the resume capability.**

Three assertions in one sentence, and the middle clause is the whole milestone.
Everything this repository knows about the page today it knows from a page
talking to a script. `tests/ui_dom_spec.js` drives the real `ui/` in a real
browser and reads the rendered text back, which is why it caught the two M04 F2
mutations — but every `/query` it answers is a constant written in that file.
`tests/test_api.py` drives the real `src/api/api.py` in-process with the graph
stubbed. **Between the two of them, the deployed artifact is never touched:
neither would notice if CloudFront served last week's `app.js`, if `/api/*`
stopped proxying, if the Lambda layer lost `fastapi` again, or if the graph's
real answer stopped carrying February 25, 2028.**

That last one is not hypothetical framing. It is the M04 defect class in its
purest form — "verified end-to-end" that never invoked the deployed function —
and this file exists because the page is the one component that still has it.

## The control

The rule for this file, taken from `evals/scenarios.json`'s grounding rule and
applied to tests instead of scenarios: **a spec earns its place by naming a
failure that reaches production and that no existing check can see. A spec that
catches nothing new is out, and the ones ruled out are listed below by name so
the omission is a decision rather than an oversight.**

Layer naming, used throughout and recorded in the artifact as `layer`:

| | what runs | what answers | what it cannot see |
|---|---|---|---|
| **L1** | `tests/test_api.py` | a stubbed graph, in-process | any browser; any deployed byte |
| **L2** | `tests/ui_dom_spec.js` | a scripted local http server | the real API, the real answer, the real distribution |
| **L3** | **this milestone** | **the deployed stack** | **nothing in the path — that is the point** |

### Spec 1 — `healthy-claim`

Clicks the canned `healthy-claim` button, then asserts on the rendered result:

- **every** `td.deadline` in `#result` reads `2028-02-25` — and there is at
  least one;
- `89 FR 106064` and `90 FR 10592` both appear in the rendered `Citations`
  list;
- **no `td` in any verdict row renders the em dash**;
- **no verdict row's confidence cell reads `no confidence`**;
- **`#result` carries no `a verdict row carries no citation` banner**;
- `#i-tier` reads one of `aoss | s3vectors`;
- `#i-cache` reads one of `hit | miss | bypass | disabled`;
- `#configured-tier` reads one of `aoss | s3vectors`.

**Three assertions carry the word "full", and it takes three because the page
renders an absent field three different ways.** SPEC/04's browser clause is
"renders the **full** Nordvale table", and a check on the deadline and the
citations discharges a narrower sentence than that one. `renderResult` builds a
row six ways and only some of them go through `td()`:

| field | how it is built | absent renders as | carried by |
|---|---|---|---|
| `product`, `trigger`, `required_change` | `td()` | `—` | the em-dash assertion |
| `real_deadline` | `td(r.real_deadline \|\| "—")` | `—` | the `2028-02-25` assertion, which is stronger |
| `confidence` | `confidenceBadge()` | **`no confidence`** | its own assertion |
| `citations` | `citesCell()` | **an empty cell** | the uncited-row banner |

So "no cell renders the em dash" does **not** say every `answer_rows` field
came back populated — the first draft of this paragraph said exactly that, and
two of the six columns falsify it. `confidenceBadge` writes the words
`no confidence` for a `null`, and `citesCell` on an empty list writes a `<td>`
holding an empty `div.cites`. Neither is an em dash and neither would have been
caught. **`pm-spec-reviewer` N8, and it is the B2 defect again**: a stated
mechanism the page does not implement, in the amendment written to close B2's
sibling.

The two gaps are closed with the page's own instruments rather than with new
selectors. `V.uncitedRows` already renders a banner reading
`a verdict row carries no citation` — CLAUDE.md's "an answer without citations
is a bug, not a style issue", implemented — and asserting its absence is
behaviour, not template. **It is also stronger than "the list is not empty"**:
it filters on `!(row.citations || []).some(c => normCite(c))`, so a row citing
strings that do not normalise to an FR document number or a CFR section fires
it too. The table above undersells it by saying "an empty cell"; an
unparseable one counts. Same for `no confidence`, which is a rendered
judgement about the answer.

**And the em dash is not a completeness check even where it applies.**
`evals/history/e26d8ef-s3vectors-full.json` records four real verdict rows
whose `real_deadline` is the literal string `"none"`, which renders as the word
and not as an em dash, and two whose `citations[]` is empty. A field can arrive
unpopulated in more than one way, and this file's assertions cover the ways the
page distinguishes.

**Two absences no assertion here catches, declared rather than found later.**
`td()` tests `text === ""` exactly, so a field arriving as `" "` renders a
visually blank cell with **no em dash** and passes — the one absence the page
does not distinguish either, which is why it is a limitation and not a hole in
the assertion. And `confidence: 0` renders `0.00` rather than `no confidence`,
correctly: zero is a value, not an absence. Named because `Confidence 0.0` is
the q05 parse-failure signature from `milestones/M07/eval-gate-flake-gap.md`,
and a future reader of a red run should not have to do that archaeology twice.

**Grounded, not bet.** `evals/scenarios.json`'s rule is that a demo asserts
already-established behaviour, and q01's recorded answer at `e26d8ef` is a
single verdict row with all six fields populated
(`evals/history/e26d8ef-s3vectors-full.json`). The shape these three assertions
expect is the shape that question has already produced, so a red run against
them is a change in the system rather than a discovery about it.
`pm-spec-reviewer` N11.

None of the three pins a column, an order or a heading, which is what the
"ruled out" section below declines. Without them, the Relation-to-SPEC/04
section retires a broader criterion than the one M08 actually checks
(`pm-spec-reviewer` N1).

**`#configured-tier` is asserted against the tier values for the same reason
`#i-tier` is.** `refreshHealth()` sets `CONFIGURED_TIER = j.tier || "unknown"`,
so the element has a third state — neither a tier nor `unavailable` — and
"reads a tier rather than `unavailable`" would leave an author free to accept
or reject `unknown`. That is the ambiguity the paragraph below rules out for
`td.deadline`, three lines after ruling it out. `pm-spec-reviewer` N5.

The quantifiers are part of the pre-registration, not prose. "`td.deadline`
reads `2028-02-25`" is ambiguous between any-row and every-row, and "the
citations are present" is ambiguous between the row cell, the response-level
list, and anywhere in the DOM. SPEC/04's parity gate is explicit for the same
reason — "every `real_deadline`, exactly", "as sets" — and the ambiguity is
exactly the room an author needs to satisfy a criterion by narrowing it.
`pm-spec-reviewer` M8.

**`#i-tier` is asserted against the tier VALUES, and the first draft of this
line was not.** It said "`#i-tier` is not the em dash", which is **passed by
the exact body it exists to reject**: `ui/app.js`'s `renderInstruments` writes
`"none"` — not an em dash — when the response carried no `tier`, and the em
dash survives only from `clearInstruments()`, i.e. only when
`renderInstruments` never ran at all. A criterion green against its own target
case, caught by `pm-spec-reviewer` (B2) before a line of it was written.

**What it catches that L1 and L2 cannot:**

1. **Deployed-asset skew.** `s3deploy.BucketDeployment` puts `ui/` in the
   bucket at deploy time. L2 reads `ui/` off the disk. A page that was never
   redeployed, or a file the `UI_ASSET_EXCLUDE` allowlist dropped, is green at
   L2 and broken at the URL in the README. `test_ui_verdict.py` checks the
   allowlist *contains* each referenced file; it does not check the bucket
   *has* it.
2. **The `/api/*` proxy, at runtime.** The page is same-origin by construction
   because CloudFront proxies `/api/*` to the HTTP API. That behaviour is
   pinned at the **synthesized template** by `tests/test_api_hosting.py` —
   caching disabled, headers forwarded, the origin a `CustomOriginConfig` on
   `execute-api` and not the bucket — and a template test cannot see whether
   the *deployed* distribution matches the template it synthesized. **Nothing
   exercises the route at runtime.** At L2 the same paths are answered by a
   test server that cannot misroute. `#configured-tier` carries this for
   nothing: `refreshHealth()` fires on every ask, `GET /api/health` costs no
   Bedrock tokens, and `unavailable` is what the page renders when the proxy
   does not answer.
3. **The deployed function actually answering.** M04 shipped a query Lambda
   that replied "No module named 'fastapi'" to every invoke, invisible because
   every end-to-end run drove the graph in-process. This spec's answer arrives
   through the deployed function or the assertion fails.
4. **The trap surviving into the browser.** `2028-02-25` with both FR numbers
   is q01's ruling rendered by the demo. At L2 that string is a constant in
   the test file: `ui_dom_spec.js` is **green against a stack that is entirely
   down**, and would stay green if the graph started moving the compliance
   date. **On a run recorded `hit` this is weaker, and the cost posture says
   how much weaker** — a hit replays a body stored up to an hour ago, so it
   evidences the deployed path plus a ≤1h-old answer, not the graph's current
   one.
5. **`#i-tier` names a real tier.** This is not a cosmetic check: it asserts
   that the run *reached retrieval*, i.e. that a 200 came back from a request
   that actually retrieved something (or, on a hit, from one that did). A 200
   whose body never reached retrieval renders `none` — exactly the shape a
   broken router returns, and exactly what a "not the em dash" assertion would
   have let through.
6. **`#i-cache` on-contract, measured off the deployed API.** SPEC/04 says the
   field is exactly one of four values. L1 exercises each of the four in its
   own test, in-process, and never asserts *set membership* at all. Nothing
   asserts anything about it against what Lambda returns, and `V.cacheReadout`
   renders an off-contract value as the violation it is rather than coercing
   it — a rendering nothing has ever seen fire against a real response.

   **A fifth constant exists.** `response_cache.py` defines
   `UNCACHEABLE = "uncacheable"`; `src/api/api.py` never emits it today, so a
   four-value assertion is correct as written. If it starts being emitted,
   **that is a SPEC/04 contract change and must be read as one** — not as an
   L3 flake to be widened away. Recorded here so the next reader of a red run
   has the disambiguation in hand.

### Spec 2 — `needs-review`

Clicks the `needs-review` button and asserts, **in this order**:

1. `#result` contains `NEEDS HUMAN REVIEW`;
2. `#result` contains `resume capability was minted`;
3. **then, and only after both hold**, `#result` contains no `td.deadline`,
   and the serialized DOM contains nothing matching the resume token's format.

**The ordering is load-bearing.** Both negatives are trivially true *before the
response arrives* — an empty `#result` has no deadline cell and no token in it.
Asserted unordered they are green against a page that never answered, which is
green by construction, which is the shape this repository has already found
four times. `pm-spec-reviewer` M7.

**What it catches that L1 and L2 cannot:**

1. **The pause has no browser coverage at all today.** Every one of
   `ui_dom_spec.js`'s four scripted responses is `status: "ok"`. The
   `needs_input | pending_review` branch of `renderResult` — SPEC/04's required
   "needs human review" state, and the only reason the `needs-review` scenario
   exists — has never been rendered by any test, at any layer. This is not
   "L3 does it better"; it is the first check of any kind.
2. **The deployed graph really pauses.** `hitl_gate`, the confidence threshold
   and the DynamoDB checkpointer all live in the deployed function. L1 stubs
   the graph and asserts that a *stubbed* pause produces a token. Whether the
   real graph pauses on the real question is a different claim.
3. **`resume capability was minted` proves the token reached the browser.**
   That sentence is rendered only when `body.resume_token` is truthy. So the
   assertion is not "the page said something reassuring" — it is *the token was
   present in the response and the page declined to display it*. A page that
   printed the token would satisfy a "does it pause" check equally well.
4. **The token is absent from the DOM, not merely from the visible text.** The
   check runs against the serialized DOM, so a token in a `title`, a `data-`
   attribute, an `href` or a hidden node fails it. The format is **derived from
   `src/api/resume_token.py`, not transcribed**: `secrets.token_urlsafe(32)` is
   43 characters of `[A-Za-z0-9_-]` with no padding, so the pattern is a
   43-character run of that class with no such character on either side. If the
   token length or alphabet changes in `src/`, this assertion must be
   re-derived — and this file says so out loud rather than leaving a magic
   number in a test. The pattern correctly excludes what else the page renders:
   a uuid4 `thread_id` is 36 characters and a sha256 hex digest is 64. **A
   match must be reported with its surrounding node**, not as a bare boolean:
   any unrelated 43-character run would fail the suite, and under the
   red-closes-red ruling below a spurious red is expensive enough that it has
   to be diagnosable rather than a mystery.
5. **No `td.deadline` on a paused run.** SPEC/04: a pause means *no answer is
   being asserted*. A page that rendered both the pause banner and a deadline
   row would be asserting one anyway, and would pass every other check here.

### Ruled out — specs that catch nothing new

Named rather than silently omitted:

- **Layout, colour, element structure.** `tests/test_ui_verdict.py` already
  declines these in terms: asserting a `<td>` exists pins the template rather
  than the behaviour. Every selector this file *does* use is read as a
  statement about the answer rather than the markup — `td.deadline` present and
  absent are *a deadline is being asserted / is not*; "no cell renders the em
  dash" is *`product`, `trigger` and `required_change` came back populated*;
  `no confidence` and the uncited-row banner are the page's own rendered
  judgements about the answer. Nothing here asserts a column order, a heading,
  or a class that is not load-bearing.
- **The cross-tier comparison panel and its equal/differs verdict.** L2 covers
  the judgement (`ui_verdict_spec.js`) and the page's use of it
  (`ui_dom_spec.js`, four scripted responses including the cache-hit refusal
  that is SPEC/04 control 1). Reaching it at L3 requires a `make up`, which is
  OCU billing and a ~20-minute window, to re-check a decision already covered
  twice. **Out of scope, below.**
- **Citation link URLs.** `ui_verdict_spec.js` drives `V.citationUrl` directly.
- **The CSP the distribution sends.** `tests/test_api_hosting.py` pins
  `core_stack.CSP` byte-identical to the copy `ui_dom_spec.js` serves. A
  browser at L3 would fail obscurely on a policy mismatch rather than reporting
  one, which is a worse instrument than the one that exists.
- **The four `/resume` refusals.** L1's
  `test_all_four_refusals_are_byte_identical`. Byte-identical bodies are a
  diff, not a rendering, and driving them through a browser would weaken the
  comparison rather than strengthen it.
- **The bypass control.** `ui_dom_spec.js` measures the checkbox default and
  both URL flags off the request body the page actually sent. At L3 the same
  check would cost Opus tokens to learn nothing. See the cost posture.

## Scope

1. `ui-tests/` — a self-contained Playwright project with its own
   `package.json`, `@playwright/test` and **Chromium only**, no other
   dependency. `playwright.config.ts`: `baseURL` from `APP_URL` defaulting to
   the deployed distribution, timeout 60s, **retries 0**, trace
   `retain-on-failure`, a json reporter to `ui-tests/results/playwright.json`.
2. The two specs above, and nothing else.
3. `ui-tests/record_verdict.py` — turns the json report into one record at
   `evals/history/<sha>-playwright.json`. Three properties, each with a reason:
   - **Refuses to write from a dirty tree**, on `run_evals.py --record`'s
     reasoning: `git_sha()` reports HEAD whether or not the tree matches it, so
     recording dirty files a measurement under a commit that cannot reproduce
     it. `--allow-dirty` is the same escape hatch `run_evals.py`,
     `run_retrieval.py` and `run_demo_parity.py` all carry, and it stamps the
     card `dirty: true`, i.e. **provisional**. It is not decoration: while
     `ui-tests/` is itself uncommitted, it is the only way this command runs at
     all.
   - **Supersedes rather than overwrites.** A second run at the same sha
     archives the first under `evals/history/superseded/` and carries a
     `supersedes` trail on the live card — the behaviour `run_evals.record()`
     already implements via `_peek_trail` / `_archive`, and which
     `tests/test_m04_instrument_threads.py` justifies in one sentence:
     "re-running until green is exactly the behaviour this makes visible."
     **A milestone whose headline ruling is "the suite is not re-run until it
     goes green" must not ship a recorder that makes re-running invisible.**
     The trail is also where the pre-registered execution budget below becomes
     a countable number rather than a promise. `pm-spec-reviewer` B3.
   - **Records `passed`/`total` faithfully, including zero.**
4. `make ui-tests` and `make ui-record`. `make ui-tests` runs
   `evals/check_opus_headroom.py --questions 2` first and refuses on a non-zero
   exit, exactly as `make smoke` and `make evals` do — two being the number of
   specs, pinned by Scope 5. The suite spends Opus tokens against a
   non-adjustable cap; the repository owns a refusal instrument for that, and a
   cost posture with no instrument is prose. `pm-spec-reviewer` M12.
5. A unit test pinning the pre-registered literals as present in `ui-tests/`:
   `2028-02-25`, `89 FR 106064`, `90 FR 10592`, `td.deadline`,
   the em dash itself (U+2014, `—`), `no confidence`,
   `a verdict row carries no citation`, `#i-tier`,
   `#i-cache`, `#configured-tier`, `aoss`, `s3vectors`,
   `hit`/`miss`/`bypass`/`disabled`, `NEEDS HUMAN REVIEW`,
   `resume capability was minted`. It also pins the token pattern's length and
   character class to `resume_token._TOKEN_BYTES` — derived, not transcribed,
   which is the whole point of Spec 2's fourth justification — and pins
   `--questions N` in `make ui-tests` to the number of specs, on the reasoning
   the Makefile already states for `make smoke` and `make evals`: the count is
   declared rather than derived so that changing the set shows up as a diff
   instead of silently loosening the guard.

   **What this catches is DELETION of a pre-registered literal, and nothing
   more.** An assertion weakened while its literal survives — parked in a
   comment, or left in a second assertion that no longer gates — passes it, and
   `hit`, `miss`, `aoss` and `#i-cache` are short enough to appear
   incidentally. The claim it replaced said "weakening an assertion is a red
   `unit` job", which is more than a presence test can see. **Two instruments,
   two failure modes, neither pretending to be the other**: this one catches
   the deletion, and Done-when 6's verbatim README quotation plus the amendment
   rule below are what stand against the weakening. `pm-spec-reviewer` N9(b).

   **This list has now been the defect it exists to prevent three times, the
   third in the diff that recorded the second.** Draft one pinned six literals
   from a draft that predated the B2 fix, so `#i-tier` could have been reverted
   to the em-dash form with `unit` green. Draft two added the standing rule
   below **and added N1's em-dash assertion without adding its literal** — a
   verbatim recurrence, one paragraph under its own record of it. Draft three
   then added `no confidence` and the uncited-row banner **and still did not
   add the em dash**, leaving the one Spec 1 assertion with no pinned literal
   inside the paragraph whose subject is that exact omission.
   `pm-spec-reviewer` N3, N6, N9(a), N12. Three recurrences of one omission,
   each caught by a reviewer and none by the author, is the argument for the
   sentence below being mechanical rather than remembered. **When an assertion is added
   to Spec 1 or Spec 2, its literals are added here in the same diff**, and the
   two recurrences above are why that sentence is not decoration.
6. `milestones/M08/README.md`, recording the runs **as run**.

`tests/ui_dom_spec.js` is not modified. It is the L2 control, and this
milestone's numbers are meaningless without it: L3 alone cannot distinguish
"the page is wrong" from "the stack is wrong", and L2 is the instrument that
tells those apart.

### The record

The same fields the existing `evals/history/` cards carry — `sha`, `dirty`,
`at`, `tier`, `tier_source`, `cache_statuses`, `fallbacks`, `passed`, `total`,
`wall_s`, `corpus`, `mode`, `subset` — plus `suite: "playwright"`,
`surface: "web"`, `layer: "L3"`, `app_url`, and `fail_closed: true`.

Two deliberate departures, stated because both would otherwise be found later
as bugs:

- **The per-item array is `specs`, not `questions`.**
  `evals/replay_history.py` globs `history/*.json` and treats any card with a
  `questions` key as a golden-set card. A UI card wearing that key would be
  read by the golden-set tooling as a set of questions with no answers. The
  card must be **inert to the golden-set tooling**: it is not a golden run, it
  gates nothing in `unit`, and it must not appear in a pass-rate history.
  `run_evals.previous_card()` globs `*-{tier}-{subset}.json`, which
  `<sha>-playwright.json` does not match — that one is already safe by naming,
  and this makes the other safe by naming too.
- **`tier` and `cache_statuses` are OBSERVED, not asserted** — read off the
  page's instrument strip, which reads them off the response body. This is the
  page's own honest-instrument rule applied to the artifact, and `tier_source`
  records that provenance so a later reader cannot mistake it for a configured
  tier. **`corpus` is best-effort**: this card makes no corpus claim, and
  records `available: false` rather than failing when the deployed environment
  cannot be resolved from the laptop.

And one field that is a claim rather than a label: **`layer` is `L3` only when
`APP_URL` is an https origin that is not loopback; anything else records
`L3-local`.** `APP_URL` is overridable by design, and "L3" asserts *what
answered*. A card reading `layer: "L3"` over `http://127.0.0.1:8000` would be
this project's signature defect — an instrument measuring the thing next to
the claim — filed as evidence. `app_url` is recorded either way, so the
downgrade is checkable against it. `pm-spec-reviewer` m14.

## Relation to SPEC/04

SPEC/04 already gates a sentence that overlaps this one, and leaving the
relationship implicit would silently change what an existing criterion means.
So, explicitly:

- **SPEC/04's browser clause — "the scenario with id `healthy-claim` renders
  the full Nordvale table in a browser against the deployed stack" — is
  DISCHARGED by a green Spec 1, and by nothing weaker.** The word "full" is
  carried by three assertions — the em-dash cells, the confidence cell, and the
  uncited-row banner — which are in Spec 1 *because* of this clause, and which
  it takes three of because the page renders an absent field three different
  ways (see Spec 1). Without them the discharge would retire a broader sentence
  than the one M08 checks, which is the same defect class as retiring a
  criterion by narrowing its subject. **If M08 closes red, SPEC/04's browser clause stays
  open** — this file normalises closing red, and a red close discharges
  nothing.
- **SPEC/04's "`/health` reports the correct tier before and after `make up`"
  is UNTOUCHED and still owed there.** `#configured-tier` at L3 evidences that
  the proxy answered and that `/health` named a real tier. It observes no
  **flip**: `make up` is out of scope this milestone, so the "before and after"
  half has nothing to compare. Named because M08 added a `/health`-derived
  assertion while excluding the command that clause turns on, and a reader
  could otherwise take Spec 1 to be partially paying it. `pm-spec-reviewer` N2.
- **SPEC/04's screenshot obligation survives, and is not converted into a test
  run.** SPEC/04 says "a browser procedure with no record is rehearsal, not a
  criterion", and `milestones/M04/` still lacks the screenshot;
  `tests/ui_dom_spec.js` records that debt in its own comments. A json report
  is a record of a different thing from a photograph of the rendered page, and
  M08 does not pay a debt in a currency the creditor did not name. **Still owed
  at SPEC/04.**
- **SPEC/04's "a cached repeat query returns < 500ms" is UNTOUCHED and remains
  owed there.** This file puts every latency assertion out of scope (below),
  which means it neither discharges that clause nor lowers its bar.

`pm-spec-reviewer` B4.

## Out of scope

- **CI wiring.** Nothing in `.github/workflows/` is touched this milestone. The
  suite is run by a person, from a laptop, against a URL.
- **The required-check decision.** Whether `ui-tests` becomes a required status
  check on `main`'s ruleset is **deferred**, and it is deferred for a measured
  reason rather than for convenience: `milestones/M07/skipped-check.txt`
  established that **a SKIPPED required status check does not block a merge**
  (PR #16, `mergeStateStatus: CLEAN` with `golden-set` SKIPPED and every other
  required check SUCCESS). A browser suite that costs Bedrock tokens will want
  an `if:` guard, and an `if:`-guarded required check is a check that reads
  CLEAN when it does not run. Adding this to the ruleset before deciding what
  its guard does would reproduce, knowingly, the hole that file documents.
- **A flake policy at k=3.** `milestones/M07/eval-gate-flake-gap.md` records
  what a gate meeting an unexplained failure without a ruled policy costs —
  **and, in its FOURTH observation, that the failure was a real product defect
  and not noise.** That file warns in terms against lifting its three candidate
  fixes out of it, and this deferral does not: it is cited for the cost of
  ruling before measuring, not for the framing it retracted. Which of the two a
  red L3 run is — a defect or variance — **cannot be known before one happens**,
  and that is exactly why k=3 is registered here and left unanswered. Defining
  "green at k=3" — best-of, all-of, or a register of admitted observations — is
  a seat decision informed by measurements this milestone does not yet have.
  M08 runs the suite **at most three times total** and records what it saw; it
  does not convert three runs into a policy.
- **The exhibit PR.** No pull request is opened at M08.
- **Resuming from the browser.** `ui/app.js` has no resume affordance at all —
  it renders the pause, says a capability was minted, and stops. M08 adds none.
  `POST /resume/{thread_id}` is exercised at L1 only. Named because a reader of
  Spec 2 could otherwise take the pause round trip to be covered; the "ruled
  out" entry above covers only the four *refusals*.
- **`red-no-3` at L3.** The third canned scenario is not exercised. Two
  scenarios is not the demo, and this is a declared exclusion rather than an
  oversight: `red-no-3` answers `ok` like `healthy-claim` does, so it would
  re-run Spec 1's shape against a second question for a second uncached graph
  run's worth of Opus tokens.
- **The cross-tier panel at L3**, and therefore **any `make up`** — see "ruled
  out" above. No OCU is billed this milestone.
- **Any assertion about latency.** ADR-0012 retired Tier B's latency claim; the
  page displays numbers, and displaying one is not asserting one. `wall_s` in
  the record is the suite's wall clock, which is a fact about the test run and
  not a claim about the system.
- **Firefox, WebKit, mobile viewports, and visual/screenshot diffing.**
  Chromium only, by the dependency ruling.
- **Authentication.** Unchanged from SPEC/04: `/query` is unauthenticated and
  `/resume` gets a bearer capability, not an identity.

## Cost posture

**The bypass control is never ticked, by any spec, under any flag.** An
uncached query costs ~5,881.8 Opus tokens — measured over 60 invocations from
CloudWatch on 2026-08-20 and recorded in
`milestones/M06/spec06-disposition-amendment.md` Finding 1, which is what
`make opus-headroom` consumes rather than produces — against `L-ED2BADF9`,
2,592,000 tokens/day, **`Adjustable: false`**: a cap that is not a bill but a
dead afternoon. A suite that bypassed on every run would spend the demo's own
headroom to re-measure a cache label.

**Cache hits are acceptable and must be labelled.** This is not a weakening.
The claim in this file is about *rendering and the path to it*, and a hit
travels the whole deployed path — CloudFront, the proxy, the function, the
page — while skipping only the graph. `#i-cache` records which happened, per
run, in the artifact, so a green suite that never ran the graph is **visible in
the record rather than hidden by it** — the M04 5/5-Tier-B lesson, applied to
this instrument before it can bite.

**But a hit is weaker in a second way, and the first draft of this paragraph
said it was weaker in only one.** It claimed "the one thing a hit cannot
support is a cross-tier observation, and this milestone makes none", which is
false as written. `response_cache.TTL_SECONDS` is 3600, so a hit also cannot
support the freshness half of the trap claim: on a `hit`, Spec 1 establishes
the deployed path plus a stored answer up to an hour old, and **only a run
recorded `miss` or `bypass` supports "the graph's current answer still carries
2028-02-25".** Since bypass is forbidden here, that means: **the trap claim is
established only on a run whose `#i-cache` read `miss`.** Both facts are on the
card, so which was established is readable from the record and not from this
prose. `pm-spec-reviewer` M6.

**`needs-review` costs on every run, and cannot be made not to.**
`response_cache.cacheable()` refuses to store any body carrying a `thread_id`
or a `resume_token` (`src/api/response_cache.py`), which is correct — a
capability must not be cached — and means the paused scenario is a guaranteed
miss. Budget it as one uncached graph run per execution of that spec.

**Pre-registered budget: at most three executions of the suite, total.** Worst
case ≈ 6 uncached runs ≈ 35,291 Opus tokens, ~1.4% of the daily cap. Stated in
advance so that "run it again" is a decision with a number attached rather than
a reflex — and countable after the fact, which is the difference between a
budget and an intention.

**What counts it is two things, not one.** The `supersedes` trail counts
re-runs **at one sha**, and this file's own criteria push the runs across
shas: Done-when 5 requires the README to record every execution, Scope 3
refuses to record from a dirty tree, and `git_dirty()` excludes
`evals/history/` but not `milestones/` — so writing up run 1 dirties the tree,
and run 2 is recorded either at a new sha (fresh trail, run 1 invisible to it)
or with `--allow-dirty`. **The budget is therefore counted from the set of
`evals/history/*-playwright.json` cards plus everything under
`evals/history/superseded/`, taken at M08's shas** — that set accumulates
across milestones, so an unbounded read of it counts M09's runs too.
`pm-spec-reviewer` N4 and N10(a).

**And it falsifies an under-stated count only for runs that were recorded.** An
execution that happened and was never recorded is invisible to both
instruments; Done-when 5's "as run" is a seat obligation, not a measurement.
Said out loud because the rest of this file holds instruments to exactly that
standard, and a budget count that quietly assumed otherwise would be the one
place it did not. `pm-spec-reviewer` N10(b).

## Done when

Pre-registered before any code is written, and **deliberately not "the suite is
green"** — see the ruling below.

1. **`make ui-tests` runs both specs against `APP_URL` in Chromium and writes
   `ui-tests/results/playwright.json`.** `APP_URL` defaults to the deployed
   distribution and is overridable by env.
2. **It fails closed.** There is no skip path. If the browser is missing, the
   URL is unreachable, the page does not load, or a scenario button is absent,
   the suite **fails** — it does not skip and does not pass. `ui_dom_spec.js`
   exits 64 for "no chrome found" and the python wrapper turns that into a
   SKIP, which is right *there* because chrome is not a declared dependency;
   here Chromium **is** one, and a skip would be a green check for a thing that
   did not run. `fail_closed: true` is recorded on the card as an assertion
   about this suite, checkable by breaking `APP_URL` on purpose.
3. **`make ui-record` writes `evals/history/<sha>-playwright.json`** with the
   fields above, **refuses on a dirty tree** (`--allow-dirty` stamps the card
   provisional), **supersedes rather than overwrites a card at the same sha**,
   and records `passed`/`total` faithfully **including a failing run**. A
   recorder that can only file victories is not evidence. Checkable by
   recording two runs at one sha and reading the trail.
4. **The card is inert to the golden-set tooling**: `evals/replay_history.py`
   and `run_evals.py`'s history readers ignore it. Checkable by running
   `make replay-history` with the card in the tree.
5. **`milestones/M08/README.md` records every execution as-run** — the count,
   each verdict, each observed `cache` label, and any failure with its
   assertion and its trace, under "what I can demo right now / delta vs
   baseline / what broke".
6. **The assertions in Spec 1 and Spec 2 above ARE the pre-registration, and
   the as-shipped suite is checked against them.** `milestones/M08/README.md`
   quotes the as-shipped assertion for each, verbatim, beside the clause of
   this file it implements; and a unit test pins the literals (Scope 5) so that
   weakening one turns `unit` red. Any difference between the two lists is a
   **SPEC/08 amendment through `pm-spec-reviewer`**, not a test edit.

   Without this, criterion 1 says only "runs both specs" and an author ships
   two files whose assertions are strictly weaker than this file's prose while
   satisfying every other criterion — a criterion whose subject can move
   without a diff, which is the trap-census defect class, reproduced inside the
   file that names it. `pm-spec-reviewer` B1, and it is the finding that made
   the ruling below mean anything: decoupling "green" from "done" removes the
   incentive to loosen an assertion only if the assertions are a fixed subject.

### The one that matters: a red result closes this milestone red

**If a spec fails, the failure is the finding. It is recorded as-run, the
assertion is not loosened, the suite is not re-run until it goes green, and the
repair is a follow-up with its own diff.**

This is stated as a criterion because the alternative is not hypothetical.
"Done when the suite passes" is a criterion an author satisfies by editing the
assertion, and this repository has already found four defects of the shape
*instrument adjusted until it agreed* — a parity gate that would have passed
comparing nothing, an asset-allowlist test green in a clean checkout,
"verified end-to-end" that never invoked the deployed function, and a 5/5
Tier B scorecard whose five answers were Tier A cache hits. A first-ever L3
check against a live stack is the single most likely place in this project for
a fifth, because it is the one place where the cheap repair — relax the string,
add a retry, widen the regex — is indistinguishable in the diff from the
correct one.

So the exit criterion is **the suite exists, runs against the deployed stack,
fails closed, and its result — whatever it is — is recorded**. Whether M08's
result is green is a finding about the system. Whether it is *recorded* is the
finding about the milestone.

### What this milestone does not establish

Stated so nobody reads more into a green suite than it holds:

- **Two scenarios is not the demo.** `red-no-3` is not exercised at L3 (out of
  scope, above).
- **On a `hit`, not the freshness of the answer.** See the cost posture: the
  trap claim is established only on a run whose `#i-cache` read `miss`.
- **One browser, one operating system, once or a few times.** Nothing here is
  a claim about stability, and the k=3 deferral above is exactly the admission
  that it is not.
- **Nothing about Tier B.** The hot tier stays down for the whole milestone.
- **Nothing about concurrency or load.** SPEC/06's, and still deferred there.
