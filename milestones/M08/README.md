# M08 — The UI Surface, Against The Deployed Stack. **RED, and recorded red.**

- Spec: SPEC/08-ui-surface.md   Branch: `m08-ui-surface`   Scorecard commit: `940af83`
- ADRs touched: none. Not tagged, no PR opened, no CI workflow changed.
- Sessions: 1 Claude Code session.
- Dependency added: `@playwright/test` (Chromium only), isolated in `ui-tests/`
  with its own `package.json` and lockfile. Ruled on by the seat before any
  code was written. Resolved to 1.62.1.

## Scorecard

| run | suite | surface | layer | passed | total | cache |
|-----|-------|---------|-------|--------|-------|-------|
| `940af83` run 2 | playwright | web | L3 | **1** | **2** | hit, miss |
| `940af83` run 1 | playwright | web | L3 | 1 | 2 | miss, miss |

`evals/history/940af83-playwright.json` carries run 2 and supersedes run 1
(`evals/history/superseded/940af83-playwright.run1.json`); the `supersedes`
trail on the live card is where the execution count is countable rather than
promised. Both stamped `dirty: true` — **provisional**, because `ui-tests/` is
itself uncommitted and `--allow-dirty` is the only way the recorder runs at all
before that lands. Tier `s3vectors` both times, observed off the page's
instrument strip. Corpus on run 2: 52 documents, `35a293e17117`. No `make up`,
no OCU billed, no fallback observed.

**Delta vs baseline (M00b): unchanged, and it should be.** M08 adds a test
layer and moves no answer-quality number. A milestone that added a browser
suite and reported a score improvement would be reporting a coincidence.

## Runs, as run

**Two executions against the deployed URL, of a pre-registered budget of three.**

| # | what | verdict |
|---|------|---------|
| control | `APP_URL=https://127.0.0.1:9` — fail-closed probe, spends nothing | **2 failed, 0 skipped** |
| 1 | `make ui-tests` against the deployed distribution | **1 passed, 1 failed** — and the failing spec aborted before its last assertion |
| 2 | the same, after the instrument repair in finding 3 | **1 passed, 1 failed**, every assertion reached |

**Run 2 is not a retry.** The suite changed between them, and it changed in the
direction that makes a red run report *more*, not less: run 1's failing spec
died at its third assertion and never executed its fourth, so the capability
scan — the security-relevant one — had never run anywhere. Run 2's purpose was
to execute an assertion that had never executed. The deadline assertion failed
again, identically, which is the tell that this was not a walk toward green.

**The control probe is not one of the three**: it never reaches the deployed URL
and spends no Bedrock tokens. It exercises **one of Done-when 2's four
conditions** — URL unreachable. Browser missing, page does not load, and
scenario button absent are argued from the code and were not measured.

## What you can demo at this point (2-3 min)

1. **`make ui-tests`.** A real Chromium opens the deployed demo, clicks the
   canned `healthy-claim` button with the bypass box untouched, and reads the
   rendered page back. The verdict row's deadline is `2028-02-25` — q01's trap,
   rendered in a browser by the deployed stack. **This is the first check in the
   repository that any of that is true of the deployed artifact.**
   `tests/ui_dom_spec.js` asserts the same date against a constant it ships
   itself and is green against a stack that is entirely down.
2. **Then watch the second spec fail, and read why.** The `needs-review`
   scenario pauses correctly and never prints the resume capability — and it
   *also* renders a full verdict row with a deadline and a confidence of 0.95.
   The page says a human must review this and asserts an answer in the same
   card. That is finding 1.
3. **`make ui-record`.** The run becomes
   `evals/history/940af83-playwright.json`, carrying the failing assertion in
   full, the observed tier, both cache labels, and a `supersedes` trail naming
   the earlier run. Then note what it does *not* do: `make replay-history` and
   the golden-set readers ignore it, because its per-item array is `specs` and
   not `questions`.

**On a `hit`, the green half proves less.** Run 1 answered `healthy-claim` on a
`miss`; run 2 got a `hit`. SPEC/08's cost posture says the trap claim — that the
graph's *current* answer still carries `2028-02-25` — is supported only on a
`miss`, because a hit replays a body stored up to an hour ago. **Run 1 supports
it; run 2 supports the deployed path and a stored answer.** Both facts are on
the cards.

## What broke

### 1. THE FINDING — a paused run asserts an answer anyway

`needs-review.spec.ts` failed on this assertion, quoted verbatim from the
shipped file:

```ts
await expect.soft(
  result.locator("td.deadline"),
  "a paused run rendered a deadline — a pause means no answer is being asserted",
).toHaveCount(0, { timeout: 5_000 });
```

Received 1, expected 0, on both runs. What the deployed stack returned, read off
the page (thread id redacted):

- `status: needs_input`, review reason **"no product or label claim to apply a
  rule to"** — correct, and exactly what `evals/scenarios.json` says this
  scenario exists to demonstrate.
- `a resume capability was minted for thread <redacted> and is deliberately not
  displayed here` — the token reached the browser (that sentence renders only
  when `body.resume_token` is truthy) and the page withheld it.
- **And a complete verdict row**: product "All products bearing a 'healthy'
  claim", `real_deadline` **2028-02-25**, confidence **0.95**, three citations.
- **And prose that invents the asker**: *"Yes, you are affected... Because your
  company makes a 'healthy' claim"* — for a `company_profile` of `{}`.

**The mechanism, from source rather than from a third run.** `hitl_gate`
(`src/graph/nodes.py:810`) runs *after* synthesis: `profile_sufficient` false
returns `("needs_input", …)`, but `verdict_rows`, `answer`, `citations` and
`confidence` are already in state by then. `_shape` (`src/api/api.py:294`)
copies `answer_rows` onto the body unconditionally. `renderResult`
(`ui/app.js`) renders the pause banner and then the table. So the gate is a
post-hoc **label**, not a suppression, at every one of the three layers.

**Why this is a real defect and not a strict test.** `ui/app.js` states the
invariant itself, in the comment above the branch that renders the pause:
"Both mean no answer is being asserted." `evals/scenarios.json` says the same
about this scenario in stronger terms — a question about whether something
applies to the asker, with no asker in it, "cannot be answered for that asker
at any confidence". The deployed system answers it at 0.95.

**Disposition is a seat call and is NOT made here.** Three candidate owners,
not interchangeable:

| owner | change | cost |
|---|---|---|
| the graph | do not synthesise rows once `profile_sufficient` is false | cheapest run; loses the draft a reviewer might want |
| the API (`_shape`) | withhold `answer_rows` when status is `needs_input` | the reviewer's draft survives in the checkpoint |
| the page | render the pause and suppress the table | the API still hands an unasserted answer to any caller |

SPEC/04 is silent on which, which is why this is written up rather than fixed.

**And the golden set is green on it, by one word.** `q10` is the question
behind this scenario. It gates on `expect_status_any: [pending_review,
needs_input]`, which the run satisfies, plus one guard:
`must_not_contain: ["you must comply by"]`. The deployed answer says **"you must
comply with the new criteria"** and puts **2028-02-25** in a `real_deadline`
cell. The guard was written at exactly this defect and misses it on phrasing —
the `check_discrimination` blind spot this repo already knows about: three
questions were written on 2026-08-15 in a phrasing the model does not use.

**This is SME-seat territory and it stops here.** `evals/golden_questions.json`
is not edited by this milestone. What the seat is owed is a triage of whether
q10's guard should assert on `answer_rows` at all — a question about the
instrument, not about this change.

### 2. FINDING — the deployed answer cited authority the sources did not carry

Observed on both runs: the page raised its `citations dropped during synthesis`
banner. The model reached for **21 CFR 101.65(d)**, **21 CFR 101.13(b)(2)(ii)**
and **21 CFR 101.65(a)(2)**, none of which the retrieved passages supported.

Filed as its own finding rather than as a bullet under finding 1, because it is
a different defect with a different owner: finding 1 is about *what the API
returns on a pause*, this is about *what the model claims*. CLAUDE.md rules that
an answer without citations is a bug rather than a style issue, and `verdict`'s
filter is what turned these into a banner instead of into three citations a
reader would have trusted — so **the guard worked**; what is unreported is
whether three dropped citations on a canned demo scenario is acceptable.

No spec asserts `dropped_citations` is empty. SPEC/08 does not pre-register it,
so the suite is not in breach — **but this milestone found the event and did not
gate on it**, and that is the honest statement. Owner: SME seat, alongside q10.
`eng-code-reviewer` M11.

### 3. The instrument was defective, and run 1's write-up claimed a measurement that never happened

**This is the milestone's own defect class, in its own postmortem, and it is
the most useful thing here.**

`playwright.config.ts` sets `timeout: 60_000` and `expect: { timeout: 55_000 }`.
Spec 2's third assertion is a *negative* (`toHaveCount(0)`), so when violated it
polls for the full 55 s. The two positives above it had already spent ~15 s of
round trip. 15 + 55 > 60, so the test timeout fired mid-assertion and
**everything after that line was dead code — deterministically, whenever that
assertion failed.** The capability scan is the line after it.

So on run 1, `tokenLikeNodes()` never executed. The first draft of this README
nonetheless read *"the token … appears nowhere in the serialized DOM"* and
called the security half passed. That sentence was true — a human read it out of
the trace — and **it was not established by the instrument.** An instrument
measuring the thing next to the claim, in the file whose subject is that defect.
Caught by `eng-code-reviewer` H1/H2 and `security-reviewer` H3.

The repair loosens nothing: `expect.soft` keeps the red and lets the scan below
it run, and a 5 s timeout removes no waiting the assertion needs, because the
two auto-retrying positives have already proved the page rendered. **On run 2
the capability scan executed and passed** — the card shows one error on that
spec, the soft deadline failure, and a 22.8 s duration rather than a 60 s
timeout. That claim now rests on a check that ran.

### 4. Why there is no run 3

Two of three used. The remaining question a third run could answer — whether
the failure reproduces — is the k=3 flake question SPEC/08 explicitly defers
rather than answers with three runs. The mechanism is established from source,
and both runs agree.

## Review findings, and what was done

`eng-code-reviewer` and `security-reviewer` ran on the diff. Several were
mutations that left every check green while destroying the property — the M04 F2
exercise, repeated on this milestone's own instruments. All fixed in-diff:

| finding | the edit that survived the suite | fix |
|---|---|---|
| sec H1 | the capability scan redacted the *match* and printed `outerHTML` beside it, which contains the match in full — and `record_verdict.py` copies failure messages verbatim into a **committed** card | redact the match **and** the window |
| sec H2 | `trace: retain-on-failure` writes the `/api/query` body — a **live** `resume_token`, good for `CHECKPOINT_TTL_DAYS = 30` — to disk on every run, and this README listed the trace as an evidence artifact | traces deleted; no longer listed as evidence; see the warning below |
| sec M1 | the scan ran in the page's own JS context via `page.evaluate`, where `RegExp`, `Node` and `Element.prototype.attributes` are page-overridable — the page could forge `[]` from the only security assertion in the suite | scan `page.content()` in Node; also covers comment nodes and `<template>`, which the DOM walk skipped (`eng` M9) |
| eng H3 / sec M3 | `make ui-record` re-derived `APP_URL` from the config, so a loopback run recorded as `layer: "L3"` against the deployed URL | each spec attaches the URL its own process visited; the recorder refuses if they disagree |
| eng H4 | a spec file that fails to transpile leaves no failing spec, only a smaller total: 1-of-2 became **1/1 PASS** | cross-check the runner's own tally, refuse on report-level errors; `tests/test_ui_record_verdict.py` drives `parse()` |
| eng H5 | `git mv needs-review.spec.ts needs-review.ts` + `--questions 1` → the finding disappears, `unit` green | pin the collected filenames; the literal pins now read `*.spec.ts` only |
| eng H6 | `{${length}}` → `{${length + 1}}` disabled the token scan silently; the old guard looked for a *literal* `[A-Za-z0-9_-]{43}`, which an interpolated form never contains | recompute the derivation in Python and drive it against 50 real minted tokens, uuid4s and a sha256 |
| eng M7 | `await page.locator("#bypass").check()` doubles Opus spend and stays green — `bypass` is a legal cache state | pinned: no `.check()`, no `no_cache`, and each spec asserts the box is unticked |
| eng M8 | reorder Spec 2's negatives above its positives → they pass vacuously against an empty `#result` and **today's genuine red reports green** | pinned by source-order index |
| eng M10 | `corpus` was permanently `{"available": false}` — `ui-record` had no `RESOLVE_ENV` | added (lenient form); run 2's card records 52 documents |
| sec L1, L3, L5 | `APP_URL` interpolated into the recipe; `ui-tests/` outside ruff's scope; the operator's home directory in the committed card | `export APP_URL`; `make lint` covers `ui-tests`; repo root stripped from recorded traces |

**A trace from this suite holds a live bearer capability.** `needs-review` fails
deterministically while finding 1 stands, so every run mints a token and
Playwright writes the `/api/query` response body into `trace.zip`. `ui-tests/`
gitignores `test-results/`, `results/`, `playwright-report/` and `blob-report/`,
and `security-reviewer` verified nothing outside `ui-tests/` re-catches them —
but **do not attach or share a trace from this suite**, and delete
`ui-tests/test-results/` after reading one. Both runs' traces were deleted; the
tokens they held should be treated as burned.

`tests/test_ui_surface_pins.py` also now scans every **tracked** file under
`evals/history/`, `milestones/M08/` and `ui-tests/` for anything token-shaped,
so "the gitignore was enough" is checked rather than argued.

### Not fixed — a spec amendment, not a test edit

`eng-code-reviewer` L12: Spec 1 does not assert `status: "ok"`. Given finding 1,
a `healthy-claim` run that *paused* would render the pause banner **and** the
table and pass every assertion in that spec. Not pre-registered, so the suite is
not in breach — but a green Spec 1 does not establish "the deployed graph
answered", only "the deployed stack rendered this table". Adding
`await expect(result).not.toContainText("NEEDS HUMAN REVIEW")` is a **SPEC/08
amendment through `pm-spec-reviewer`**, and under Done-when 6 it is not
something this session adds on its own.

### What the spec got wrong before any code was written

Four `pm-spec-reviewer` passes, and **every blocker after the first was
introduced by the fix for the previous one**:

- **B2** — the assertion the seat asked for, "`#i-tier` is not an em dash", is
  passed by the exact body it exists to reject: `app.js` renders `"none"`.
- **N1** — the fix for B4 discharged SPEC/04's "renders the **full** Nordvale
  table" using a check on two columns.
- **N8** — that fix covered three of six columns: `confidence` is a badge
  writing `no confidence`, and an empty `citations[]` renders an empty cell.
  Both verified against real recorded rows in `e26d8ef-s3vectors-full.json`.
- **N12** — the pin list that exists to stop assertions being weakened failed to
  include a newly added literal **three times**, the third inside the paragraph
  recording the second.

None was caught by the author. That, plus the mutations above, is the argument
for `tests/test_ui_surface_pins.py` being mechanical rather than remembered, and
for the routing rule that sends work to a fresh seat.

## Evidence artifacts

- `evals/history/940af83-playwright.json` — run 2, 1/2, provisional, with the
  trail naming run 1
- `evals/history/superseded/940af83-playwright.run1.json` — run 1
- `SPEC/08-ui-surface.md` — the pre-registration, written before any code
- `ui-tests/` — config, two specs, recorder
- `tests/test_ui_surface_pins.py`, `tests/test_ui_record_verdict.py` — 45 checks
- Playwright traces are **not** evidence artifacts here: they are gitignored,
  overwritten by the next run, and they hold a live capability (above).

## Pre-registration, as shipped

SPEC/08 Done-when 6 requires the as-shipped assertion beside the clause it
implements. Verbatim from `ui-tests/tests/`:

| SPEC/08 clause | as shipped |
|---|---|
| every `td.deadline` in `#result` reads `2028-02-25` — and there is at least one | `expect(seen.length, …).toBeGreaterThan(0)` then `expect(d.trim(), …).toBe(DEADLINE)` for every `d` |
| `89 FR 106064` and `90 FR 10592` both appear in the rendered `Citations` list | `await expect(citationList, …).toContainText(cite)` for both, where `citationList = result.locator(".card > div > .cites")` |
| no `td` in any verdict row renders the em dash | `expect(cell.trim(), …).not.toBe("—")` over `result.locator("table tbody td").allInnerTexts()` |
| no verdict row's confidence cell reads `no confidence` | `await expect(result.locator("table tbody td .pill", { hasText: "no confidence" }), …).toHaveCount(0)` |
| `#result` carries no `a verdict row carries no citation` banner | `await expect(result.locator(".banner b", { hasText: "a verdict row carries no citation" }), …).toHaveCount(0)` |
| `#i-tier` reads one of `aoss \| s3vectors` | `expect(TIERS, …).toContain(inst.tier)` |
| `#i-cache` reads one of `hit \| miss \| bypass \| disabled` | `expect(CACHE_STATES, …).toContain(inst.cache)` |
| `#configured-tier` reads one of `aoss \| s3vectors` | `expect(TIERS, …).toContain(inst.configuredTier)` |
| Spec 2, order: pause, then minted, then the negatives | `toContainText(PAUSE)` → `toContainText(MINTED)` → `expect.soft(...).toHaveCount(0, …)` → token scan, in file order, pinned by index |
| the serialized DOM contains nothing matching the resume token's format | `expect(hits, …).toEqual([])` where `hits = await tokenLikeNodes(page, resumeTokenPattern().source)` |

The token pattern is derived, not transcribed: `_page.ts` reads `_TOKEN_BYTES`
out of `src/api/resume_token.py`, checks that `mint()` still calls
`secrets.token_urlsafe` on it, and computes `ceil(n*4/3)` characters of
`[A-Za-z0-9_-]`. It throws rather than falling back to a literal 43, and
`tests/test_ui_surface_pins.py` recomputes the same derivation in Python and
drives it against 50 tokens the real `mint()` produced.

## What this milestone does NOT establish

- **`red-no-3` is not exercised at L3.** Two scenarios is not the demo.
- **Nothing about stability.** One browser, one OS, two runs. k=3 is deferred.
- **Nothing about Tier B**, concurrency or load. The hot tier stayed down.
- **Fail-closed is measured on one of four conditions**, not four.
- **On run 2's `hit`, not the freshness of the answer** — run 1's `miss` is what
  supports that half.
- **Spec 1 green does not establish `status: ok`** — see L12 above.
- **SPEC/04 debts survive**: the `milestones/M04/` screenshot (a json report is
  not a photograph), the `< 500ms` cached-repeat clause, and "/health reports
  the correct tier before and after `make up`" — no `make up` happened here.
- **SPEC/04's browser clause is NOT discharged.** Spec 1 is green, but SPEC/08
  settles this case in terms: "If M08 closes red, SPEC/04's browser clause
  stays open… a red close discharges nothing." It stays open.
