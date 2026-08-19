# ADR-0013: An instrument reads the field that describes its own claim — the demo page's rule, and why it is enforced by a browser

- Status: **accepted 2026-08-19 by the human seat.** Drafted at M04 close at
  that seat's request — it asked for "the demo page's instrument rule" to be
  written down — and accepted as drafted, with the `m04` tag moved to include
  it so the ADR sits inside the tree it describes rather than after it.
  Drafting was engineering's; the ruling is the human seat's (ADR-0005: there is
  one seat here, and what makes a ruling sound is evidence a reader can
  falsify, not a signature).

  **Landed with this ADR:** the removal of `latencyReadout`'s unused
  `roundTripMs` parameter (`ui/verdict.js`), found while writing the Decision
  section — the rule's twelfth instance, and the only one caught by stating the
  rule rather than by running something.
- Date: 2026-08-19
- Milestone: M04
- Basis: eleven recorded instances in `milestones/M04/README.md`, each
  reproduced by running rather than argued. What makes this sound is that every
  claim below is falsifiable against a file in git or a test that fails when the
  rule is broken — not a signature (ADR-0005).
- Relates to: SPEC/04's UI section (the readouts this governs); ADR-0012 (which
  made the latency readout "reported, not a claim"); ADR-0002 (the control whose
  recordability this rule's absence broke); ADR-0011 (the corpus fingerprint,
  which is the same rule applied to scorecards).
- Scope note: this ADR is about **reporting surfaces** — the demo page first,
  because that is where the human seat asked for it and where a wrong reading is
  seen by a viewer rather than by an operator. M04 found the identical defect in
  scorecards and in gate artifacts, and those instances are cited as evidence
  that the rule is not page-specific. **It does not retrofit rules onto
  `evals/` or `milestones/` beyond what M04 already changed.**

## Context

M04 built the first surface in this project that *reports on itself to a
viewer*: a tier badge, a cache label, a retrieval-latency readout and a
cross-tier comparison panel, all rendered next to an answer.

Building it, the milestone hit one defect eleven times, in eleven costumes. The
full census is in `milestones/M04/README.md`; the shape is always the same:

> **An instrument that measures something adjacent to the claim reads exactly
> like one that measures the claim.**

Three instances are enough to fix the pattern:

- **`/health` is not what answered.** It calls `router.active_tier()`, an SSM
  read reporting what the system is **configured** to. The router falls back to
  S3 Vectors on any AOSS error. The two agree right up until the case anyone
  would want to know about. A cold Lambda served the wrong tier for the first
  sixty seconds of every container's life, and `/health` — the endpoint whose
  entire job is to report the live tier — was **structurally unable to notice**,
  because it read the same fooled cache.
- **A cache hit is not this request.** `/query` returns the STORED body on a
  hit, so `tier`, `fallback_reason` and `retrieval_ms` all describe the request
  that populated the cache, possibly on the other tier, up to an hour earlier.
  A Tier B scorecard read **5/5 having reached AOSS zero times** exactly this
  way.
- **The round trip is not retrieval.** A `/query` miss is 10–13 s end to end and
  is Bedrock-dominated; retrieval is ~300–900 ms of it, 3–8%. A client stopwatch
  under the words "retrieval latency" is a number about generation wearing a
  retrieval label — in the readout whose only purpose is to compare two
  retrieval tiers.

The decisive observation is *where the last instances were found*: **in the
instruments built during this milestone to catch the first ones.** An
asset-allowlist test that passed with its own fix deleted. A screenshot showing
a 10 ms round trip for an eleven-second request. A cache-control guard, added to
stop a card that measured the cache, which silently made the M00b control
unrecordable for three days. The defect is not a property of careless code. It
is the default, and it survives being understood.

## Decision

**Every readout on a reporting surface reads the field of the response it
labels. Where the surface can show two sources that may disagree, it shows
both, labelled, and never resolves the disagreement silently.**

Four parts, all currently implemented and tested:

### 1. The badge reads the response, not the endpoint

The tier indicator reads `tier` off the `/query` response body
(`src/api/api.py:293`, carried from `router.Resolution` through
`graph.nodes.retrieval_agent`), never `active_tier()`. `ui/app.js:284` is
`const tier = body && body.tier;` and that is the whole of it.

`/health` **is** displayed — in the header, labelled `configured tier`, with a
tooltip saying it reports what SSM holds and not what answered. When the two
disagree the badge says so (`ui/app.js:296-297`, `≠ configured — /health says
…`). **The disagreement is the information.** A surface showing one number
could not have reported the cold-start bug; a surface showing the observed one
only would hide a misconfiguration.

### 2. A stale field is rendered as provenance, never as a live reading

On `cache: hit` nothing was retrieved, so `tier` and `retrieval_ms` are
historical. Both are dimmed and prefixed `stored`
(`ui/verdict.js:234-237`, rendered at `ui/app.js:311-322`), and the panel
**refuses to record the response as a tier observation at all**
(`ui/verdict.js:105`). That refusal is
SPEC/04's parity control 1 enforced in the browser: without it the panel reports
`equal` by construction and is measuring the response cache.

### 3. An absence is shown as an absence

A run that never retrieved — `needs_input`, or rejected — carries `tier: null`
and `retrieval_ms: null`, and the page prints "no retrieval happened" rather
than a default. `null` and `0` are distinguished explicitly (`=== null ||
=== undefined`, never falsiness): a real 0 ms is a measurement and must not read
as "not measured".

### 4. The rule is enforced by driving the page, not by reviewing it

`tests/ui_dom_spec.js` runs the real page in a real headless browser against
scripted responses and reads the rendered text back. It catches, among others,
the mutation `const tier = CONFIGURED_TIER` — the badge sourced from `/health`,
which is this milestone's defect in its purest form and which **every other test
in the repo passes through unnoticed**.

This part is not decoration. `ui/verdict.js` holds the page's judgement so it
can be exercised without a browser, and that alone proved insufficient: it
showed what the functions *return* while the page's *use* of them stayed
untested, and two one-line edits — `if (taken.ok)` → `if (true)`, and
`const ms = body.retrieval_ms` → `const ms = roundTripMs` — left every
assertion in the diff green.

*Applied to itself while this ADR was being written:* `latencyReadout` still
carried an unused `roundTripMs` parameter, which made that second mutation a
one-word edit **inside the tested function** rather than in the page. Removed.
A seam that accepts the wrong source as an argument is a seam that invites it.

## Alternatives considered

- **Read `/health` for the badge.** One request, one number, no plumbing —
  and structurally unable to report a fallback or the cold-start bug. This was
  the original design and is the reason `retrieval_tier` had to be threaded out
  of the router at all.
- **Show only the observed tier and drop `/health`.** Rejected: a viewer then
  cannot see that the system is configured for a tier that is not answering,
  which is precisely the state a demo of a two-tier system should surface.
- **Time the fetch in the browser and label it "retrieval latency".** Free, no
  server change. Rejected: 92–97% of that number is Bedrock, so it cannot
  distinguish the tiers it is displayed to compare. This is the alternative that
  forced `retrieval_ms` to be built, which is the largest single cost this rule
  has imposed.
- **State the rule in CLAUDE.md and rely on review.** Rejected on ADR-0012's own
  words: *a rule with no check is decoration.* Eleven instances in one milestone,
  several of them written by someone who had just finished fixing the previous
  one, is the evidence that understanding the rule does not enforce it.
- **Assert the rendered strings from Python, without a browser.** Rejected:
  that pins the template rather than the behaviour, which is the shape of test
  this milestone already found green in a clean checkout.

## Consequences

**Easier.** A viewer can trust each readout to describe the request in front of
them. The disagreement cases — fallback, stale cache, no retrieval — are visible
rather than smoothed, which is what makes the tier-switch demo a demonstration
rather than an assertion.

**Harder, and this is the real cost.** *Adding a readout now means adding a
field to the response*, not computing one client-side. `retrieval_ms` had to be
measured in `router.retrieve_traced`, carried on `Resolution`, threaded through
`RegDeltaState` and added to **both** `_shape` mappings before the UI could show
a number at all. Any future readout — token counts, per-node timings, cost —
pays the same toll.

**A new kind of test in this repo.** `ui_dom_spec.js` needs node and a
Chrome-family browser. Both are present in CI (it runs there rather than
skipping: 859 passed, 0 skipped) and node was already a hard dependency via
`aws_cdk`. It skips with a stated reason where no browser exists, and reports
that as a skip rather than a pass.

**Two mappings to keep in step.** `src/api/api.py:_shape` and
`evals/serve_local.py:_shape` must carry the same fields, or the golden set and
the deployed API measure different things — the failure that made
`dropped_citations` read as "nothing was dropped" where nothing had been asked.
One test pins them together.

**What this does not settle.** `router.hydrate` has its own silent AOSS →
S3 Vectors fallback on the crossref lane, so one response can still span two
tiers while `tier` describes only the main retrieval call. Recorded, not fixed.

**Revisit when** a surface needs a readout whose honest source genuinely does
not exist server-side. The rule then forces the choice into the open — build the
measurement, or label the proxy as a proxy — which is the outcome it is for.

## What this ADR does NOT amend

- **SPEC/04's UI section.** It already lists the readouts and their required
  vocabulary (ADR-0012 Ruling 2). This ADR records *why they are wired the way
  they are*, and adds no criterion.
- **`/health` itself.** Reporting the configured tier is its correct job. The
  defect was ever treating that as the answering tier.
- **The gate artifacts.** `make demo-parity`'s controls and
  `run_evals`'s guards were fixed within M04 on this same reasoning; this ADR
  cites them as evidence and does not re-legislate them.
- **The golden set.** Untouched, as always (ROLES.md).

## Evidence

- `milestones/M04/README.md`, "What broke / what I'd redo" — the eleven
  instances, with the note that the last five are in instruments built to catch
  the first six.
- `tests/ui_dom_spec.js` — 15 checks against the real page; the
  `tier = CONFIGURED_TIER` mutation is caught here and nowhere else.
- `tests/ui_verdict_spec.js` — 27 assertions on the judgement, including that a
  cache hit is refused as a tier observation.
- `milestones/M04/screenshots/01-healthy-claim-and-cross-tier-equal.png` — the
  four readouts live on the deployed distribution: `aoss` observed, `bypass`,
  **390 ms** retrieval against a **11.73 s** round trip, in two labelled boxes.
- `milestones/M04/answer-parity-3966b47.json` — the artifact whose instrument is
  the in-process counterpart of the page's readout, and the reason ADR-0012 says
  the readout reports rather than claims.
