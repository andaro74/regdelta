/*
 * The demo page's judgement, exercised without a browser.
 *
 * Driven by tests/test_ui_verdict.py through node — the same node that
 * `import aws_cdk` already starts a child process of, so this needs nothing
 * the suite did not already require.
 *
 * WHAT IS AND IS NOT COVERED HERE. This file exercises `ui/verdict.js`: the
 * citation URLs, which responses may become a tier observation, and the
 * equal/differs verdict with its three caveats. It does NOT exercise the
 * rendering — no DOM, and asserting that a <td> exists would be the kind of
 * test that pins the template rather than the behaviour. The rendering's
 * evidence is a screenshot of the deployed page against the deployed stack,
 * which is what SPEC/04 gates on: "a browser procedure with no record is
 * rehearsal, not a criterion."
 */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

const V = require(path.join(__dirname, "..", "ui", "verdict.js"));

let ran = 0;
const failures = [];

function test(name, fn) {
  ran += 1;
  try {
    fn();
  } catch (e) {
    failures.push(name + "\n    " + String(e.message || e).split("\n").join("\n    "));
  }
}

// ───────────────────────────────────────────────────────────── citation links
test("volume-and-page FR citations link to federalregister.gov", () => {
  assert.equal(V.citationUrl("89 FR 106064"),
    "https://www.federalregister.gov/citation/89-FR-106064");
  assert.equal(V.citationUrl("90 FR 4628"),
    "https://www.federalregister.gov/citation/90-FR-4628");
});

test("FR document numbers link to federalregister.gov too", () => {
  // SPEC/04 and the domain skill both name the doc number as a citation in its
  // own right; the `needs-review` scenario cites two of them and nothing else
  // in that shape.
  assert.equal(V.citationUrl("2024-29957"),
    "https://www.federalregister.gov/d/2024-29957");
  assert.equal(V.citationUrl("2025-03118"),
    "https://www.federalregister.gov/d/2025-03118");
});

test("CFR sections link to ecfr.gov, with the paragraph anchor when given", () => {
  assert.equal(V.citationUrl("21 CFR 74.303"),
    "https://www.ecfr.gov/current/title-21/section-74.303");
  assert.equal(V.citationUrl("21 CFR 80.32(h)"),
    "https://www.ecfr.gov/current/title-21/section-80.32#p-80.32(h)");
  assert.equal(V.citationUrl("21 CFR 101.65(d)(2)"),
    "https://www.ecfr.gov/current/title-21/section-101.65#p-101.65(d)(2)");
});

test("the section symbol and stray whitespace are typography, not identity", () => {
  assert.equal(V.citationUrl("21 CFR § 101.65"),
    "https://www.ecfr.gov/current/title-21/section-101.65");
  assert.equal(V.citationUrl("  89   FR  106064 "),
    "https://www.federalregister.gov/citation/89-FR-106064");
});

test("anything unrecognised gets no link rather than a guessed one", () => {
  // A guessed link that lands on the wrong document is the failure this
  // product exists to expose. The page renders these as plain text.
  for (const junk of ["see the preamble", "", null, undefined,
                      "21 CFR", "FR 106064", "101.13(h)",
                      "https://evil.example/#89 FR 106064"]) {
    assert.equal(V.citationUrl(junk), null, "linked something it should not: " + junk);
  }
});

// ───────────────────────────────────────────── what may become an observation
const OK_BODY = {
  tier: "s3vectors",
  cache: "bypass",
  status: "ok",
  retrieval_ms: 354.1,
  citations: ["89 FR 106064"],
  answer_rows: [{ real_deadline: "2028-02-25", citations: ["90 FR 10592"] }],
};

test("a bypassed answer is recorded under the tier that answered", () => {
  const t = V.observationFrom(OK_BODY, "2026-08-18T10:00:00Z");
  assert.equal(t.ok, true);
  assert.equal(t.observation.tier, "s3vectors");
  assert.equal(t.observation.retrieval_ms, 354.1);
});

test("A CACHE HIT IS REFUSED — the control the whole panel rests on", () => {
  // On a hit the API returns the STORED body, so `tier` names whichever tier
  // answered when it was cached — possibly the other one, up to an hour ago.
  // Recording it would file Tier A's answer under Tier B and the panel would
  // report `equal` by construction, measuring the response cache. An M04
  // scorecard read 5/5 for Tier B exactly this way, having reached AOSS zero
  // times.
  const hit = Object.assign({}, OK_BODY, { cache: "hit", tier: "aoss" });
  const t = V.observationFrom(hit, "2026-08-18T10:00:00Z");
  assert.equal(t.ok, false);
  assert.match(t.refusal, /cache/i);
});

test("a run that never retrieved is refused — there is no tier on it", () => {
  const paused = { status: "needs_input", cache: "bypass", tier: null, answer_rows: [] };
  const t = V.observationFrom(paused, "2026-08-18T10:00:00Z");
  assert.equal(t.ok, false);
  assert.match(t.refusal, /retriev/i);
});

test("citations are the union of the response list and every row's", () => {
  const t = V.observationFrom(OK_BODY, "t");
  assert.deepEqual(t.observation.citations, ["89 FR 106064", "90 FR 10592"]);
});

test("real_deadline is a multiset over every row, sorted", () => {
  const two = Object.assign({}, OK_BODY, {
    answer_rows: [{ real_deadline: "2028-02-25" }, { real_deadline: "2027-01-15" }],
  });
  assert.deepEqual(V.observationFrom(two, "t").observation.deadlines,
    ["2027-01-15", "2028-02-25"]);
});

// ────────────────────────────────────────────────────────────────── the verdict
function obs(tier, citations, deadlines, cache) {
  return {
    tier: tier, at: "2026-08-18T10:00:00Z", cache: cache || "bypass",
    status: "ok", citations: citations, deadlines: deadlines,
    retrieval_ms: 1, fallback_reason: null, trace_id: null,
  };
}

test("equal when citations agree as SETS and deadlines match exactly", () => {
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064", "90 FR 10592"], ["2028-02-25"]),
    // Same set, different order — order is not a property this system fixes.
    obs("aoss", ["90 FR 10592", "89 FR 106064"], ["2028-02-25"]));
  assert.equal(r.verdict, "equal");
  assert.equal(r.vacuous, false);
  assert.equal(r.sameTier, false);
  assert.equal(r.cacheNote, null);
});

test("a citation present on one tier only is a DIFFERS, and is named", () => {
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064", "90 FR 10592"], ["2028-02-25"]),
    obs("aoss", ["89 FR 106064"], ["2028-02-25"]));
  assert.equal(r.verdict, "differs");
  assert.deepEqual(r.onlyInPrev, ["90 FR 10592"]);
  assert.deepEqual(r.onlyInCur, []);
});

test("a deadline that changed is a DIFFERS even when citations agree", () => {
  // The signature failure of this product: the effective date moved and the
  // compliance date did not. A tier disagreeing about that is a bug.
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064"], ["2028-02-25"]),
    obs("aoss", ["89 FR 106064"], ["2025-04-28"]));
  assert.equal(r.verdict, "differs");
  assert.equal(r.citationsEqual, true);
  assert.equal(r.deadlinesEqual, false);
});

test("a row appearing on one tier only is caught — deadlines are a multiset", () => {
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064"], ["2028-02-25"]),
    obs("aoss", ["89 FR 106064"], ["2028-02-25", "2028-02-25"]));
  assert.equal(r.verdict, "differs");
});

test("agreement about nothing is marked VACUOUS", () => {
  // Two empty citation lists are equal and say nothing. Three "agree" verdicts
  // must not read as three scenarios' worth of evidence — the artifact's
  // guard 4, in the browser.
  const r = V.compareObservations(obs("s3vectors", [], [""]), obs("aoss", [], [""]));
  assert.equal(r.verdict, "equal");
  assert.equal(r.vacuous, true, "empty strings counted as content");
});

test("a tier compared against itself is flagged, not reported as agreement", () => {
  // Engineering review found exactly this in the Phase 4 gate's compare(): an
  // artifact whose `aoss` half had resolved to s3vectors passed as perfect
  // agreement. It is not being rebuilt here.
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064"], ["2028-02-25"]),
    obs("s3vectors", ["89 FR 106064"], ["2028-02-25"]));
  assert.equal(r.sameTier, true);
});

test("a side that did not bypass the cache is flagged — including a miss", () => {
  // `miss` counts, not only `hit`: on a request that asked for a bypass it
  // means the cache was consulted anyway, so the control is already broken.
  const r = V.compareObservations(
    obs("s3vectors", ["89 FR 106064"], ["2028-02-25"], "miss"),
    obs("aoss", ["89 FR 106064"], ["2028-02-25"], "bypass"));
  assert.notEqual(r.cacheNote, null);
  assert.match(r.cacheNote, /miss/);
});

test("SPEC/04's four cache states, and only those", () => {
  assert.deepEqual(V.CACHE_STATES, ["hit", "miss", "bypass", "disabled"]);
});

// ─────────────────────────────────────────────────────────── the readouts
//
// These moved out of the page because nothing could reach them there
// (`eng-code-reviewer`, M04 F2). `tests/ui_dom_spec.js` checks the page renders
// what they return; these check what they return.
test("the latency readout is retrieval_ms, never the round trip", () => {
  const r = V.latencyReadout(OK_BODY);
  assert.equal(r.value, 354.1);
  assert.equal(r.dim, false);
  assert.match(r.note, /router\.retrieve/);
});

test("a legitimate 0 ms is a measurement, not an absence", () => {
  // `=== null || === undefined`, never falsiness. A 0 rendered as "—" would
  // report "not measured" for something that was.
  const r = V.latencyReadout(Object.assign({}, OK_BODY, { retrieval_ms: 0 }));
  assert.equal(r.value, 0);
  assert.equal(r.dim, false);
});

test("a run that never retrieved reports no latency and says why", () => {
  const r = V.latencyReadout({ status: "needs_input", tier: null });
  assert.equal(r.value, null);
  assert.match(r.note, /no retrieval happened/);
});

test("a cache hit's latency is marked stored, not presented as live", () => {
  const r = V.latencyReadout(Object.assign({}, OK_BODY,
    { cache: "hit", retrieval_ms: 999 }));
  assert.equal(r.stored, true);
  assert.equal(r.dim, true);
  assert.match(r.note, /when this answer was cached/);
});

test("a miss on a PAUSED answer does not claim it was stored", () => {
  // `response_cache.cacheable()` refuses any body carrying a resume
  // capability, so "answered fresh and stored" was false for every paused
  // run. `eng-code-reviewer`, M04 F3.
  const paused = V.cacheReadout({ cache: "miss", status: "needs_input" });
  assert.doesNotMatch(paused.note, /and stored/);
  assert.match(paused.note, /not stored/);
  assert.match(V.cacheReadout({ cache: "miss", status: "ok" }).note, /and stored/);
});

test("a cache value outside the contract is reported as off-contract", () => {
  // A label that always reads as a legal value cannot report a violation.
  const r = V.cacheReadout({ cache: "warm" });
  assert.equal(r.offContract, true);
  assert.equal(r.value, "warm");
  for (const legal of V.CACHE_STATES) {
    assert.notEqual(V.cacheReadout({ cache: legal, status: "ok" }).offContract, true);
  }
});

test("an uncited verdict row is found even inside a cited answer", () => {
  // The page's other guard fires only on the response-level list, so a single
  // uncited row rendered a blank cell and said nothing. `eng-code-reviewer` F6.
  const mixed = {
    citations: ["89 FR 106064"],
    answer_rows: [
      { product: "granola bar", citations: ["89 FR 106064"] },
      { product: "frosting", citations: [] },
      { product: "sprinkles", citations: ["  "] },
    ],
  };
  assert.deepEqual(V.uncitedRows(mixed), ["frosting", "sprinkles"]);
  assert.deepEqual(V.uncitedRows(OK_BODY), []);
});

test("the panel reports how far apart the two sides are", () => {
  // It cannot check that only the infrastructure changed — the response body
  // carries no corpus fingerprint and the poller moves the corpus unattended.
  // So it reports the gap and names `make demo-parity` as what does gate it.
  // `eng-code-reviewer`, M04 F1.
  const a = obs("s3vectors", ["89 FR 106064"], ["2028-02-25"]);
  const b = Object.assign({}, obs("aoss", ["89 FR 106064"], ["2028-02-25"]),
                          { at: "2026-08-19T15:42:00Z" });
  a.at = "2026-08-19T10:00:00Z";
  assert.equal(V.compareObservations(a, b).gapSeconds, 5 * 3600 + 42 * 60);
});

test("an unparseable timestamp yields no gap rather than a wrong one", () => {
  const a = Object.assign({}, obs("s3vectors", [], [""]), { at: "not a date" });
  assert.equal(V.compareObservations(a, obs("aoss", [], [""])).gapSeconds, null);
});

// ──────────────────────────────────────────────────────────────────── report
if (failures.length) {
  console.error(failures.length + " of " + ran + " failed:\n");
  for (const f of failures) console.error("  FAIL " + f + "\n");
  process.exit(1);
}
console.log(ran + " passed");
