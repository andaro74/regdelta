/*
 * The demo page's JUDGEMENT, separated from its rendering.
 *
 * WHY THIS IS ITS OWN FILE. SPEC/04's cross-tier comparison panel is the live
 * tier-switch demo moment: it is the thing that shows the answer not changing
 * when only the infrastructure does. That makes it the worst place in this
 * milestone for an instrument that measures something adjacent to the claim —
 * the defect M04 has now found four times. Everything here is pure and takes a
 * response body in and a verdict out, so it can be exercised directly
 * (tests/ui_verdict_spec.js) instead of being argued about from the page.
 *
 * `index.html` loads this with <script src>; node loads it with require. Same
 * file, no build step, no bundler, no dependency.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RegDeltaVerdict = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ───────────────────────────────────────────────────────── citation links
  //
  // Three notations appear in this corpus and the regulatory-domain skill names
  // all three: "89 FR 106064" (volume + page), "2024-29957" (FR document
  // number) and "21 CFR 101.65(d)(2)" (CFR section, optionally a paragraph).
  //
  // Each URL shape was checked against the live sites rather than inferred:
  // /citation/89-FR-106064 and /d/2024-29957 both redirect to the same
  // healthy-rule document, and ecfr.gov/current/title-21/section-101.65 emits
  // paragraph anchors in the form id="p-101.65(d)(2)".
  //
  // ANYTHING UNRECOGNISED RETURNS null and the page renders it as plain text. A
  // citation a reader cannot follow is a visible limit; a guessed link that
  // lands on the wrong document is the failure this product exists to expose.
  function citationUrl(raw) {
    const c = String(raw || "").replace(/§/g, " ").replace(/\s+/g, " ").trim();
    let m;
    if ((m = /^(\d{1,3})\s+FR\s+(\d{1,7})$/i.exec(c)))
      return "https://www.federalregister.gov/citation/" + m[1] + "-FR-" + m[2];
    if ((m = /^(\d{4})-(\d{3,6})$/.exec(c)))
      return "https://www.federalregister.gov/d/" + m[1] + "-" + m[2];
    if ((m = /^(\d{1,2})\s+CFR\s+(\d+\.\d+)((?:\([^()\s]+\))*)$/i.exec(c)))
      return "https://www.ecfr.gov/current/title-" + m[1] + "/section-" + m[2]
           + (m[3] ? "#p-" + m[2] + m[3] : "");
    return null;
  }

  // Whitespace and § only, deliberately. `make demo-parity` runs the full
  // `shared.citations.extract_citations` normaliser and IS the gate; this panel
  // is what a viewer sees, and it prints both sides in full, so a difference it
  // reports for a notational reason is one a reader can see through. Erasing
  // differences here would be the worse failure — the artifact's own
  // `normalise_citation` carries that argument, having once compared two tiers
  // equal by dropping a secondary reference.
  function normCite(c) {
    return String(c || "").replace(/§/g, " ").replace(/\s+/g, " ").trim();
  }

  // The union of the response-level list and every verdict row's, as a set.
  // SPEC/04 says "every `citations[]` entry" and both carry one; a row citation
  // absent from the top-level list is still a citation the reader is shown.
  function citationsOf(body) {
    const raw = [].concat((body && body.citations) || []);
    for (const row of (body && body.answer_rows) || []) {
      raw.push.apply(raw, (row && row.citations) || []);
    }
    const seen = [];
    for (const c of raw.map(normCite)) {
      if (c && seen.indexOf(c) === -1) seen.push(c);
    }
    return seen.sort();
  }

  // Every `real_deadline`, sorted — a MULTISET, not a set. Row order is not a
  // property this system fixes, so asserting it would report disagreements that
  // are not ones; a multiset still catches a row appearing, vanishing, or
  // changing its date, which is what "every real_deadline, exactly" means.
  function deadlinesOf(body) {
    return ((body && body.answer_rows) || [])
      .map(r => String((r && r.real_deadline) || "").replace(/\s+/g, " ").trim())
      .sort();
  }

  // ──────────────────────────────────────────── what may become an observation
  //
  // TWO REFUSALS, and the panel means nothing without the first.
  //
  // 1. A CACHE HIT IS NOT EVIDENCE ABOUT A TIER. On a hit `/query` returns the
  //    STORED body, so `tier`, `fallback_reason` and `retrieval_ms` describe
  //    the request that populated the cache — possibly the other tier, up to an
  //    hour ago. Recording it under `tier` would file the other tier's answer
  //    under this tier's name and the panel would report `equal` by
  //    construction, measuring the response cache. That is SPEC/04's parity
  //    control 1, and it is not hypothetical: an M04 Tier B scorecard read 5/5
  //    having reached AOSS zero times, exactly this way.
  //
  // 2. A RESPONSE WITH NO TIER IS NOT RECORDED. A `needs_input` or rejected run
  //    never reached retrieval, so there is no tier to attribute it to and no
  //    citations that came from one.
  function observationFrom(body, at) {
    if (!body || typeof body !== "object") {
      return { ok: false, refusal: "no response body to record." };
    }
    if (body.cache === "hit") {
      return {
        ok: false,
        refusal: "This response was served from the cache, so it is not evidence "
               + "about any tier — nothing was retrieved for it. Tick “bypass "
               + "the response cache” and ask again.",
      };
    }
    if (!body.tier) {
      return {
        ok: false,
        refusal: "This run never reached retrieval, so there is no tier to "
               + "record it under.",
      };
    }
    return {
      ok: true,
      observation: {
        tier: body.tier,
        at: at,
        cache: body.cache === undefined ? null : body.cache,
        status: body.status || null,
        citations: citationsOf(body),
        deadlines: deadlinesOf(body),
        retrieval_ms: body.retrieval_ms === undefined ? null : body.retrieval_ms,
        fallback_reason: body.fallback_reason || null,
        trace_id: body.trace_id || null,
      },
    };
  }

  // ──────────────────────────────────────────────────────────── the verdict
  //
  // Citations AS SETS, `real_deadline` EXACTLY — SPEC/04's words. Confidence
  // may differ and prose may differ; neither is looked at here.
  //
  // The three caveats are returned rather than folded into the verdict, because
  // each one is a statement about what the verdict is EVIDENCE OF, not about
  // whether the two sides matched:
  //
  //   sameTier   — a tier compared against itself reported as perfect agreement
  //                is a defect engineering review found in the Phase 4 gate's
  //                `compare()`. This is a determinism observation, not a
  //                cross-tier one.
  //   vacuous    — two empty citation lists are equal and say nothing. Same
  //                guard, same name, as the artifact's guard 4, and for the
  //                same reason: three "agree" verdicts must not read as three
  //                scenarios' worth of evidence.
  //   cacheNote  — `bypass` on both sides is control 1. A `miss` counts as a
  //                violation too, not only a `hit`: on a request that asked for
  //                a bypass it means the cache was consulted anyway, so the
  //                control is already broken and a hit is the next question.
  function compareObservations(prev, cur) {
    const citationsEqual = sameSet(prev.citations, cur.citations);
    const deadlinesEqual = sameList(prev.deadlines, cur.deadlines);
    const everything = [].concat(prev.citations, cur.citations,
                                 prev.deadlines, cur.deadlines);
    return {
      verdict: citationsEqual && deadlinesEqual ? "equal" : "differs",
      citationsEqual: citationsEqual,
      deadlinesEqual: deadlinesEqual,
      onlyInPrev: prev.citations.filter(c => cur.citations.indexOf(c) === -1),
      onlyInCur: cur.citations.filter(c => prev.citations.indexOf(c) === -1),
      vacuous: !everything.some(v => String(v || "").trim()),
      sameTier: prev.tier === cur.tier,
      // HOW FAR APART THE TWO SIDES ARE, and it is reported rather than used,
      // because this panel CANNOT establish that only the infrastructure
      // changed between them. `make demo-parity` gates that claim by refusing
      // any comparison whose halves recorded different `documents_sha` — the
      // daily poller moved the corpus 4 -> 34 documents unattended once
      // already. The response body carries no corpus fingerprint, so the page
      // has nothing to check it with. An earlier version of this panel printed
      // "The answer did not change when the infrastructure did" under two
      // observations 5h42m apart: SPEC/04's equal/differs verdict, which is
      // what it is asked for, with a causal claim appended that nothing here
      // tested. `eng-code-reviewer`, M04 F1.
      gapSeconds: gapSeconds(prev.at, cur.at),
      cacheNote: (prev.cache !== "bypass" || cur.cache !== "bypass")
        ? prev.tier + "=" + prev.cache + ", " + cur.tier + "=" + cur.cache
        : null,
    };
  }

  function gapSeconds(a, b) {
    const ta = Date.parse(a), tb = Date.parse(b);
    if (!isFinite(ta) || !isFinite(tb)) return null;
    return Math.round(Math.abs(tb - ta) / 1000);
  }

  function sameSet(a, b) {
    const A = unique(a), B = unique(b);
    return A.length === B.length && A.every(x => B.indexOf(x) !== -1);
  }
  function sameList(a, b) {
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }
  function unique(list) {
    const out = [];
    for (const x of list) if (out.indexOf(x) === -1) out.push(x);
    return out;
  }

  // ────────────────────────────────────────────────── what the readouts show
  //
  // THESE LIVE HERE BECAUSE THE PAGE WAS DECIDING THEM INLINE AND NOTHING
  // COULD REACH THAT DECISION. `eng-code-reviewer` M04 F2 named the exact
  // mutation: `const ms = body.retrieval_ms` -> `const ms = roundTripMs` puts
  // the browser's own stopwatch under the words "retrieval latency", which is
  // the defect the whole measurement was added to prevent, and every assertion
  // in the diff stayed green. Returning the decision from here makes it
  // reachable; `tests/ui_dom_spec.js` then checks the page renders what it
  // returns.

  function latencyReadout(body, roundTripMs) {
    const ms = body ? body.retrieval_ms : undefined;
    const tier = body ? body.tier : undefined;
    // `=== null || === undefined`, never falsiness: a legitimate 0 is a
    // measurement and must not read as "not reported".
    if (ms === null || ms === undefined) {
      return { value: null, dim: true,
               note: tier ? "not reported by this response"
                          : "no retrieval happened" };
    }
    if (body.cache === "hit") {
      // Historical. Nothing was retrieved for THIS request.
      return { value: ms, dim: true, stored: true,
               note: "measured when this answer was cached" };
    }
    return { value: ms, dim: false,
             note: "server, router.retrieve — reported, not a claim" };
  }

  function cacheReadout(body) {
    const cache = body ? body.cache : undefined;
    if (cache === undefined || cache === null) {
      return { value: null, dim: true,
               note: "hit · miss · bypass · disabled" };
    }
    if (CACHE_STATES.indexOf(cache) === -1) {
      return { value: cache, dim: false, offContract: true,
               note: "not one of hit · miss · bypass · disabled" };
    }
    const NOTES = {
      hit: "stored answer replayed — nothing was retrieved",
      bypass: "cache suppressed for this request",
      disabled: "response cache is off by configuration",
      // NOT "answered fresh and stored". A `miss` on a paused run is NOT
      // stored — `response_cache.cacheable()` refuses any body carrying a
      // resume capability — so the note asserted a write that never happened.
      // `eng-code-reviewer`, M04 F3.
      miss: "answered fresh",
    };
    let note = NOTES[cache];
    if (cache === "miss") {
      note += (body.status === "ok") ? " and stored"
            : " — not stored: a paused answer carries a resume capability";
    }
    return { value: cache, dim: false, note: note };
  }

  // A verdict row that asserts a change and cites nothing. "An answer without
  // citations is a bug, not a style issue" — and the page's existing guard
  // fires only on the RESPONSE-level list, so a single uncited row inside an
  // otherwise cited `ok` answer rendered a blank cell and said nothing.
  // `eng-code-reviewer`, M04 F6.
  function uncitedRows(body) {
    return ((body && body.answer_rows) || [])
      .map((row, i) => ({ row: row || {}, i: i }))
      .filter(r => !((r.row.citations || []).some(c => normCite(c))))
      .map(r => r.row.product || ("row " + (r.i + 1)));
  }

  // The four legal values of `cache`, per SPEC/04. Exported so the page can
  // report an off-contract value AS off-contract rather than coercing it into
  // one of the four — a label that always reads as a legal value cannot report
  // a contract violation.
  const CACHE_STATES = ["hit", "miss", "bypass", "disabled"];

  return {
    citationUrl: citationUrl,
    normCite: normCite,
    citationsOf: citationsOf,
    deadlinesOf: deadlinesOf,
    observationFrom: observationFrom,
    compareObservations: compareObservations,
    latencyReadout: latencyReadout,
    cacheReadout: cacheReadout,
    uncitedRows: uncitedRows,
    CACHE_STATES: CACHE_STATES,
  };
});
