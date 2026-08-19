/*
 * The demo page's behaviour. Split out of index.html so the page can be served
 * under a Content-Security-Policy: `script-src 'self'` blocks an inline
 * <script>, and the point of the split is to make that directive usable rather
 * than to weaken it with 'unsafe-inline'.
 *
 * The panel's JUDGEMENT is not here — it is ui/verdict.js, which node can drive
 * directly (tests/ui_verdict_spec.js). This file is the rendering, and what
 * checks it is tests/ui_dom_spec.js, which runs the real page in a real browser.
 */
"use strict";

// Loaded above. A page that renders before verdict.js arrives would throw on
// the first answer rather than quietly comparing nothing, which is the way
// round that milestone wants.
const V = globalThis.RegDeltaVerdict;

const API = "/api";

function citationNode(raw) {
  const url = V.citationUrl(raw);
  if (!url) {
    const s = document.createElement("span");
    s.className = "nolink";
    s.textContent = raw;
    return s;
  }
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = raw;
  return a;
}

// ────────────────────────────────────────────────────── confidence badges
//
// The boundary at 0.7 is not a design choice made here: it is
// `config.CONFIDENCE_HITL_THRESHOLD`, the value below which `hitl_gate` routes
// an answer to a human. A badge drawing its line somewhere else would colour
// answers green that the system itself sent for review.
const HITL_THRESHOLD = 0.7;

function confidenceBadge(value) {
  const span = document.createElement("span");
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    span.className = "pill flat";
    span.textContent = "no confidence";
    return span;
  }
  const v = Number(value);
  span.className = "pill " + (v < HITL_THRESHOLD ? "bad" : v < 0.9 ? "warn" : "ok");
  span.textContent = v.toFixed(2);
  span.title = v < HITL_THRESHOLD
    ? `below the ${HITL_THRESHOLD} HITL threshold — this routes to human review`
    : `at or above the ${HITL_THRESHOLD} HITL threshold`;
  return span;
}

// ───────────────────────────────────────────────────────────── scenarios
let SCENARIOS = [];
let CURRENT_PROFILE = {};
let CURRENT_SCENARIO = null;

async function loadScenarios() {
  const box = document.getElementById("scenarios");
  try {
    const r = await fetch("scenarios.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    SCENARIOS = data.scenarios || [];
  } catch (e) {
    // LOUD, not silent. "One button per entry" is a SPEC/04 clause; a page
    // that quietly renders zero buttons when the file is missing satisfies it
    // vacuously, which is this milestone's whole defect class.
    box.innerHTML = "";
    box.appendChild(banner("bad", "scenarios.json did not load",
      String(e) + " — the scenario buttons below are missing, not absent by design."));
    return;
  }
  box.innerHTML = "";
  if (!SCENARIOS.length) {
    box.appendChild(banner("bad", "scenarios.json contained no scenarios",
      "SPEC/04 requires one button per entry; there are no entries."));
    return;
  }
  for (const s of SCENARIOS) {
    const b = document.createElement("button");
    b.className = "scenario";
    b.innerHTML = `<span class="sid">${escapeHtml(s.id)}</span>`;
    const label = document.createElement("span");
    label.className = "slabel";
    label.textContent = s.label || s.question;
    b.appendChild(label);
    b.onclick = () => { selectScenario(s); ask(); };
    box.appendChild(b);
  }
}

function selectScenario(s) {
  CURRENT_SCENARIO = s;
  CURRENT_PROFILE = s.company_profile || {};
  document.getElementById("question").value = s.question;
  renderProfileLine();
  showRetained();
}

// What is already retained for the question now in the box, shown WITHOUT
// asking anything. The tier flip takes a `make up` — twenty minutes, during
// which a viewer will reload the page — and a panel that only appears after
// the next answer cannot be checked in the meantime. It also makes the
// retention itself visible: if localStorage lost the previous tier, this says
// so before a Bedrock call is spent finding out.
async function showRetained() {
  const question = document.getElementById("question").value.trim();
  if (!question) return renderCompare(null, null);
  try {
    renderCompare(loadStore()[await inputKey(question, CURRENT_PROFILE)] || null, null);
  } catch (e) {
    renderCompare(null, keyFailure(e));
  }
}

// `crypto.subtle` is undefined outside a secure context, so on a plain
// `http://<lan-ip>` the key cannot be computed and every caller of it rejects.
// Unhandled, that left the answer and the instruments rendering normally while
// the panel silently never updated — the same silence as F4, and the reason
// both are called out. CloudFront is REDIRECT_TO_HTTPS so the deployed page is
// never in this state; a local dev server on a LAN address is.
// `eng-code-reviewer`, M04 F5.
function keyFailure(e) {
  return "The comparison panel is unavailable: this page cannot compute the "
       + "question key (" + String(e && e.message || e) + "). `crypto.subtle` "
       + "needs a secure context — use https, localhost, or the deployed "
       + "distribution.";
}

function renderProfileLine() {
  const line = document.getElementById("profile-line");
  const keys = Object.keys(CURRENT_PROFILE || {});
  line.innerHTML = "company profile: ";
  const pill = document.createElement("span");
  if (!keys.length) {
    pill.className = "pill flat";
    pill.textContent = "none";
    line.appendChild(pill);
    line.appendChild(document.createTextNode(
      " — a question about whether something applies to the asker, with no asker in it"));
  } else {
    pill.className = "pill ok";
    pill.textContent = CURRENT_PROFILE.company || "supplied";
    line.appendChild(pill);
    const rest = document.createElement("code");
    rest.style.fontSize = "11.5px";
    rest.textContent = " " + JSON.stringify(CURRENT_PROFILE);
    line.appendChild(rest);
  }
}

// ─────────────────────────────────────────────────────────────── /health
//
// SHOWN, AND LABELLED FOR WHAT IT IS. `/health` calls `router.active_tier()`,
// an SSM read: it reports what the system is CONFIGURED to, which is not what
// answered. It is on the page because the difference between the two is worth
// seeing — the M04 cold-start bug had `/health` reporting `s3vectors` for the
// first 60 seconds of every container's life while SSM held an AOSS endpoint,
// and a page showing only one number could not have said so.
let CONFIGURED_TIER = null;

async function refreshHealth() {
  const box = document.getElementById("configured-tier");
  try {
    const r = await fetch(API + "/health", { cache: "no-store" });
    const j = await r.json();
    CONFIGURED_TIER = j.tier || "unknown";
    box.innerHTML = "configured tier: ";
    const p = document.createElement("span");
    p.className = "pill flat";
    p.textContent = CONFIGURED_TIER;
    p.title = "GET /health — what SSM is configured to, NOT what answered";
    box.appendChild(p);
  } catch (e) {
    CONFIGURED_TIER = null;
    box.textContent = "configured tier: unavailable";
  }
}

// ─────────────────────────────────────────────────────────── the request
let BUSY = false;

async function ask() {
  if (BUSY) return;
  const question = document.getElementById("question").value.trim();
  if (!question) return;
  const bypass = document.getElementById("bypass").checked;

  BUSY = true;
  const btn = document.getElementById("ask");
  btn.disabled = true;
  document.getElementById("result").innerHTML =
    '<div class="card"><span class="spinner"></span> asking… '
    + '<span class="hint">a cache miss runs the full graph and takes ~10-13s</span></div>';
  clearInstruments();
  refreshHealth();

  const t0 = performance.now();
  let body, httpStatus, transportError = null;
  try {
    const r = await fetch(API + "/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        question,
        company_profile: CURRENT_PROFILE,
        // The body flag, which the API reads alongside the
        // `x-regdelta-no-cache` header `make demo-parity` uses. Either is
        // explicit; there is no way to bypass by accident and none to bypass
        // by default.
        no_cache: bypass,
      }),
    });
    httpStatus = r.status;
    body = await r.json();
  } catch (e) {
    transportError = e;
  }
  // Stopped after the body is parsed, so this is the whole round trip a viewer
  // waited through — not just time-to-first-byte.
  const roundTripMs = performance.now() - t0;

  BUSY = false;
  btn.disabled = false;

  if (transportError) {
    document.getElementById("result").innerHTML = "";
    document.getElementById("result").appendChild(
      banner("bad", "the request did not complete", String(transportError)));
    return;
  }
  renderInstruments(body, roundTripMs, httpStatus);
  renderResult(body, httpStatus, question);
  try {
    await recordAndCompare(question, CURRENT_PROFILE, body);
  } catch (e) {
    renderCompare(null, keyFailure(e));
  }
}

// ────────────────────────────────────────────────────────── instruments
function clearInstruments() {
  for (const id of ["i-tier", "i-cache", "i-retrieval", "i-roundtrip"]) {
    document.getElementById(id).textContent = "—";
    document.getElementById(id).parentElement.classList.add("dim");
  }
}


function renderInstruments(body, roundTripMs, httpStatus) {
  const cache = body && body.cache;
  const servedFromCache = cache === "hit";

  // -- cache. SPEC/04: exactly one of hit | miss | bypass | disabled. Anything
  //    else is rendered as the unexpected value it is, not coerced into one of
  //    the four — a label that always reads as a legal value cannot report a
  //    contract violation.
  const cEl = document.getElementById("i-cache");
  cEl.textContent = cache === undefined || cache === null ? "—" : String(cache);
  cEl.parentElement.classList.toggle("dim", cache === undefined || cache === null);
  const cNote = document.getElementById("i-cache-note");
  const cr = V.cacheReadout(body);
  cNote.textContent = cr.note;
  if (cr.offContract) {
    cNote.textContent = "";
    const pill = document.createElement("span");
    pill.className = "pill bad";
    pill.textContent = "off-contract";
    cNote.appendChild(pill);
    cNote.appendChild(document.createTextNode(" " + cr.note));
  }

  // -- tier. From the response. On a hit it describes the STORED answer.
  const tEl = document.getElementById("i-tier");
  const tNote = document.getElementById("i-tier-note");
  const tier = body && body.tier;
  if (!tier) {
    tEl.textContent = "none";
    tEl.parentElement.classList.add("dim");
    tNote.textContent = "this run never reached retrieval";
  } else {
    tEl.textContent = tier;
    tEl.parentElement.classList.remove("dim");
    if (servedFromCache) {
      tNote.innerHTML = '<span class="pill warn">stored</span> the tier that answered when this was cached';
    } else if (body.fallback_reason) {
      tNote.innerHTML = '<span class="pill bad">fell back</span> ' + escapeHtml(String(body.fallback_reason).slice(0, 90));
    } else if (CONFIGURED_TIER && CONFIGURED_TIER !== tier) {
      tNote.innerHTML = '<span class="pill warn">≠ configured</span> /health says ' + escapeHtml(CONFIGURED_TIER);
    } else {
      tNote.textContent = "observed on this response, not /health";
    }
  }

  // -- retrieval latency. Absent on a run that never retrieved; historical on
  //    a hit. Neither is a number about this request's retrieval, and neither
  //    is displayed as though it were.
  // WHICH NUMBER GOES HERE IS DECIDED IN verdict.js, not here. The page
  // renders what it returns and computes nothing — `roundTripMs` is not in
  // scope for this box at all, which is the point (M04 F2).
  const rEl = document.getElementById("i-retrieval");
  const rNote = document.getElementById("i-retrieval-note");
  const lr = V.latencyReadout(body);
  rEl.textContent = lr.value === null ? "—" : fmtMs(lr.value);
  rEl.parentElement.classList.toggle("dim", !!lr.dim);
  rNote.textContent = "";
  if (lr.stored) {
    const pill = document.createElement("span");
    pill.className = "pill warn";
    pill.textContent = "stored";
    rNote.appendChild(pill);
    rNote.appendChild(document.createTextNode(" "));
  }
  rNote.appendChild(document.createTextNode(lr.note));

  const rt = document.getElementById("i-roundtrip");
  rt.textContent = fmtMs(roundTripMs);
  rt.parentElement.classList.remove("dim");
}

function fmtMs(ms) {
  const n = Number(ms);
  if (!isFinite(n)) return "—";
  return n >= 1000 ? (n / 1000).toFixed(2) + " s" : Math.round(n) + " ms";
}

// ───────────────────────────────────────────────────────────── the answer
function renderResult(body, httpStatus, question) {
  const out = document.getElementById("result");
  out.innerHTML = "";

  if (httpStatus >= 400) {
    // REDACTED BEFORE STRINGIFY. No error path the API has today returns a
    // `resume_token` — both 4xx bodies are `{detail, trace_id}` and the token
    // is minted only on a 200 — so this changes nothing now. It is here because
    // the "never print the capability" property was resting on an invariant
    // held in api.py rather than in the page, and this page gets screenshotted
    // into milestones/M04/. security-reviewer, M04.
    out.appendChild(banner("bad", "HTTP " + httpStatus,
      (body && (body.detail || JSON.stringify(redact(body)))) || ""));
    return;
  }

  const card = document.createElement("div");
  card.className = "card";

  const status = body.status || "unknown";

  // -- the "needs human review" state SPEC/04 requires. `needs_input` and
  //    `pending_review` are two doors into it: one asks the asker for more,
  //    the other stops for an SME. Both mean no answer is being asserted.
  if (status === "needs_input" || status === "pending_review") {
    const why = body.review_reason || "(no reason given)";
    const b = banner("warn", "NEEDS HUMAN REVIEW — status: " + status, why);
    if (body.resume_token) {
      // The token itself is a bearer capability bound to this thread. It is
      // never printed: this page is screenshotted into the repo.
      const p = document.createElement("div");
      p.className = "hint";
      p.style.marginTop = "8px";
      p.textContent = "a resume capability was minted for thread "
        + (body.thread_id || "?") + " and is deliberately not displayed here.";
      b.appendChild(p);
    } else if (body.resumable === false) {
      const p = document.createElement("div");
      p.className = "hint";
      p.style.marginTop = "8px";
      p.textContent = "not resumable: no checkpoint was written for this run.";
      b.appendChild(p);
    }
    card.appendChild(b);
  } else if (status !== "ok") {
    card.appendChild(banner("bad", "status: " + status, body.review_reason || ""));
  }

  // -- the verdict table
  const rows = body.answer_rows || [];
  if (rows.length) {
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr>"
      + "<th>Product</th><th>Trigger</th><th>Required change</th>"
      + "<th>Real deadline</th><th>Confidence</th><th>Citations</th>"
      + "</tr></thead>";
    const tb = document.createElement("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.appendChild(td(r.product));
      tr.appendChild(td(r.trigger));
      tr.appendChild(td(r.required_change));
      const d = td(r.real_deadline || "—");
      d.className = "deadline";
      tr.appendChild(d);
      const c = document.createElement("td");
      c.appendChild(confidenceBadge(r.confidence));
      tr.appendChild(c);
      tr.appendChild(citesCell(r.citations || []));
      tb.appendChild(tr);
    }
    table.appendChild(tb);
    card.appendChild(table);
  } else if (status === "ok") {
    card.appendChild(banner("bad", "no verdict rows",
      "status was ok and the table is empty — an answer with nothing in it."));
  }

  // -- prose, then the response-level citations
  if (body.answer) {
    const h = document.createElement("h2");
    h.style.marginTop = "18px";
    h.textContent = "Answer";
    card.appendChild(h);
    const p = document.createElement("div");
    p.className = "answer";
    p.textContent = body.answer;
    card.appendChild(p);
  }

  const cites = body.citations || [];
  const h2 = document.createElement("h2");
  h2.style.marginTop = "18px";
  h2.textContent = "Citations";
  card.appendChild(h2);
  if (cites.length) {
    card.appendChild(citesCell(cites, true));
  } else {
    // "An answer without citations is a bug, not a style issue." The page says
    // so rather than rendering an empty list that reads as tidy.
    card.appendChild(banner("bad", "no citations on this answer",
      "Every claim must carry an FR document number and/or a CFR section."));
  }

  // A ROW that cites nothing, inside an answer whose response-level list is
  // not empty — the guard above cannot see it. "An answer without citations is
  // a bug, not a style issue", and a blank cell said nothing at all.
  const uncited = V.uncitedRows(body);
  if (uncited.length && rows.length) {
    card.appendChild(banner("bad", "a verdict row carries no citation",
      "Every claim must carry an FR document number and/or a CFR section. "
      + "Uncited: " + uncited.join(", ")));
  }

  if ((body.dropped_citations || []).length) {
    card.appendChild(banner("warn", "citations dropped during synthesis",
      "The model reached for authority the retrieved sources did not carry: "
      + body.dropped_citations.join(", ")));
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = "trace_id " + (body.trace_id || "—")
    + " · status " + status
    + " · overall confidence " + (body.confidence ?? "—");
  card.appendChild(meta);

  out.appendChild(card);
}

function td(text) {
  const el = document.createElement("td");
  el.textContent = (text === null || text === undefined || text === "") ? "—" : String(text);
  return el;
}

function citesCell(list, asDiv) {
  const cell = document.createElement(asDiv ? "div" : "td");
  const box = document.createElement("div");
  box.className = "cites";
  for (const c of list) box.appendChild(citationNode(c));
  cell.appendChild(box);
  return cell;
}

// ══════════════════════════════════════════════ cross-tier comparison panel
//
// SPEC/04: retain the PREVIOUS tier's `citations[]` and every `real_deadline`
// beside the current tier's, and state an explicit equal / differs verdict
// computed on citations AS SETS and real_deadline EXACTLY. This is the live
// tier-switch demo moment: it shows the answer not changing when only the
// infrastructure does.
//
// FOUR REFUSALS, and they are the reason the panel means anything.
//
//  1. A CACHE HIT IS NOT RECORDED. On a hit nothing was retrieved and the body
//     is the stored one, so filing it under `tier` would file the OTHER tier's
//     answer under this tier's name. That is SPEC/04 control 1 — uncontrolled,
//     the two runs are minutes apart inside a 1h TTL and the panel reports
//     `equal` by construction, measuring the cache. It is not hypothetical: an
//     M04 Tier B scorecard read 5/5 having reached AOSS zero times, exactly
//     this way.
//  2. A RESPONSE WITH NO TIER IS NOT RECORDED. Nothing retrieved, nothing to
//     attribute.
//  3. THE TWO SIDES MUST BE DIFFERENT TIERS. A tier compared against itself
//     reported as perfect agreement is a defect engineering review found in
//     `compare()` at Phase 4; it is not being rebuilt here.
//  4. AGREEMENT ON NOTHING IS MARKED VACUOUS. Two empty citation lists are
//     equal and say nothing. Same rule, same name, as the artifact's guard 4.
//
// Observations are keyed by the QUESTION AND PROFILE, hashed — not by scenario
// id. "Scenario 1" is not a stable subject: reword the question and the key
// would silently follow it, which is the trap-census defect class the artifact
// records `input_sha256` to avoid. They live in localStorage because the tier
// flip takes a `make up` (~20 minutes) and a viewer will reload the page.
const STORE_KEY = "regdelta.crosstier.v1";

function loadStore() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); }
  catch (e) { return {}; }
}
// RETURNS WHETHER IT WORKED. It used to swallow the exception, so a browser
// in private mode or over quota lost the previous tier and the panel rendered
// the same "ask a question" hint it shows when nothing was ever asked — a
// retention failure and a fresh start are indistinguishable, and the demo beat
// depends on retention across a ~20-minute `make up` and a page reload.
// `eng-code-reviewer`, M04 F4.
function saveStore(s) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(s));
    return true;
  } catch (e) {
    STORE_ERROR = String(e && e.message || e);
    return false;
  }
}
let STORE_ERROR = null;

function canonical(value) {
  // Stable JSON: object keys sorted, so a profile differing only in insertion
  // order hashes the same. Mirrors `response_cache.key`'s reason for doing it.
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return "{" + Object.keys(value).sort()
    .map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
}

async function inputKey(question, profile) {
  const text = canonical({ p: profile || {}, q: question.replace(/\s+/g, " ").trim().toLowerCase() });
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function recordAndCompare(question, profile, body) {
  const key = await inputKey(question, profile);
  const store = loadStore();
  const entry = store[key]
    || { question: question, label: null, tiers: {} };
  entry.question = question;
  if (CURRENT_SCENARIO && CURRENT_SCENARIO.question === question) {
    entry.label = CURRENT_SCENARIO.label;
  }

  // The two refusals live in verdict.js and are exercised there. A cache hit
  // and a run that never retrieved are BOTH declined as tier observations —
  // see that file for why the first one is the whole control.
  const taken = V.observationFrom(body, new Date().toISOString());
  let refusal = taken.ok ? null : taken.refusal;
  if (taken.ok) {
    entry.tiers[taken.observation.tier] = taken.observation;
    store[key] = entry;
    if (!saveStore(store)) {
      refusal = "This tier was NOT retained: localStorage refused the write ("
              + STORE_ERROR + "). The comparison cannot survive the page "
              + "reload a `make up` requires.";
    }
  }
  renderCompare(entry, refusal);
}

function renderCompare(entry, refusal) {
  const box = document.getElementById("compare");
  box.innerHTML = "";

  if (refusal) {
    box.appendChild(banner("warn", "not recorded as a tier observation", refusal));
  }

  const tiers = Object.keys((entry && entry.tiers) || {});
  if (!tiers.length) {
    box.appendChild(hint("Ask a question with the cache bypassed; the answer is "
      + "retained here. Then run `make up` (or `make down`) and ask the same "
      + "question again — the panel compares the two tiers."));
    return;
  }

  const subject = document.createElement("div");
  subject.className = "hint";
  subject.style.marginBottom = "10px";
  subject.textContent = "subject: " + (entry.label ? entry.label + " — " : "")
    + '"' + entry.question + '"';
  box.appendChild(subject);

  if (tiers.length < 2) {
    box.appendChild(sideCard(entry.tiers[tiers[0]], "the only tier seen so far"));
    box.appendChild(hint("One tier only. The other side appears after a `make up` "
      + "or `make down` moves /regdelta/search/endpoint and the same question is "
      + "asked again with the cache bypassed."));
    return;
  }

  // Oldest first, so "previous" and "current" mean what they say after a flip.
  const ordered = tiers.map(t => entry.tiers[t])
                       .sort((x, y) => String(x.at).localeCompare(String(y.at)));
  const prev = ordered[ordered.length - 2];
  const cur = ordered[ordered.length - 1];

  const grid = document.createElement("div");
  grid.className = "compare";
  grid.appendChild(sideCard(prev, "previous tier"));
  grid.appendChild(sideCard(cur, "current tier"));
  box.appendChild(grid);

  const r = V.compareObservations(prev, cur);

  const line = document.createElement("div");
  line.className = "verdictline";
  const big = document.createElement("span");
  big.className = "big";
  big.textContent = r.verdict.toUpperCase();
  big.style.color = r.verdict === "equal" ? "var(--ok)" : "var(--bad)";
  line.appendChild(big);

  if (r.verdict === "equal") {
    // WHAT WAS OBSERVED, not what caused it. This sentence used to end "The
    // answer did not change when the infrastructure did", which asserts that
    // infrastructure was the only variable — and nothing on this page checked
    // that. See the gap line below. (M04 F1.)
    line.appendChild(hintSpan(
      "citations agree as sets and every real_deadline matches exactly — "
      + prev.tier + " vs " + cur.tier + "."));
  } else {
    const bits = [];
    if (!r.citationsEqual) {
      bits.push("citations — only in " + prev.tier + ": [" + r.onlyInPrev.join(", ")
        + "], only in " + cur.tier + ": [" + r.onlyInCur.join(", ") + "]");
    }
    if (!r.deadlinesEqual) {
      bits.push("real_deadline — " + prev.tier + ": [" + prev.deadlines.join(", ")
        + "] vs " + cur.tier + ": [" + cur.deadlines.join(", ") + "]");
    }
    line.appendChild(hintSpan(bits.join(" · ")
      + " — a citation or a date that changes when only the infrastructure "
      + "changed is a bug."));
  }
  box.appendChild(line);

  // The three caveats. Each says what the verdict is EVIDENCE OF, which is a
  // different question from whether the two sides matched — so each is shown
  // beside the verdict rather than folded into it.
  if (r.vacuous) {
    box.appendChild(banner("warn", "vacuous — the tiers agreed about nothing",
      "Neither side carried a citation or a deadline, so this verdict is not "
      + "evidence of comparability. Same guard as `make demo-parity`."));
  }
  if (r.sameTier) {
    box.appendChild(banner("bad", "same tier on both sides",
      "This is a determinism observation, not a cross-tier one."));
  }
  if (r.cacheNote) {
    box.appendChild(banner("warn", "one side did not bypass the cache",
      "Recorded cache states: " + r.cacheNote + ". SPEC/04's control 1 wants "
      + "`bypass` on both sides; a `miss` means the cache was consulted anyway."));
  }

  // THE CAVEAT THAT MAKES THE VERDICT READABLE. `make demo-parity` refuses a
  // comparison whose two halves recorded different `documents_sha`, because
  // the daily poller moves the corpus unattended — it once took it from 4 to
  // 34 documents between two halves. The response body carries no corpus
  // fingerprint, so this panel cannot make that check and must not imply it
  // did. It shows how far apart the two sides are and says which instrument
  // does gate it.
  const gap = document.createElement("div");
  gap.className = "hint";
  gap.style.marginTop = "10px";
  gap.textContent = "The two sides are "
    + (r.gapSeconds === null ? "an unknown interval"
       : r.gapSeconds < 90 ? r.gapSeconds + " s"
       : Math.floor(r.gapSeconds / 3600) + "h "
         + Math.round((r.gapSeconds % 3600) / 60) + "m")
    + " apart. This panel compares two answers; it cannot check that only the "
    + "infrastructure changed between them — the corpus is not pinned here. "
    + "`make demo-parity` is what gates that, by refusing any comparison whose "
    + "halves recorded a different documents_sha.";
  box.appendChild(gap);

  const lat = document.createElement("div");
  lat.className = "hint";
  lat.style.marginTop = "10px";
  lat.textContent = "retrieval latency, as measured on each side: "
    + prev.tier + " " + (prev.retrieval_ms === null ? "—" : fmtMs(prev.retrieval_ms))
    + " · " + cur.tier + " " + (cur.retrieval_ms === null ? "—" : fmtMs(cur.retrieval_ms))
    + " — two single measurements, reported. The gating numbers are median and "
    + "p95 over the probe set in milestones/M04/answer-parity-<sha>.json.";
  box.appendChild(lat);
}


function sideCard(obs, title) {
  const d = document.createElement("div");
  d.className = "side";
  const h = document.createElement("h3");
  h.textContent = title + ": " + obs.tier;
  d.appendChild(h);
  const when = document.createElement("div");
  when.className = "when";
  when.textContent = obs.at.replace("T", " ").replace(/\..*/, "Z")
    + " · cache " + obs.cache + " · status " + obs.status
    + (obs.fallback_reason ? " · FELL BACK" : "");
  d.appendChild(when);

  d.appendChild(subList("citations[] (as a set)", obs.citations));
  d.appendChild(subList("real_deadline (every row)", obs.deadlines.map(x => x || "(none)")));
  return d;
}

function subList(title, items) {
  const w = document.createElement("div");
  w.style.marginTop = "8px";
  const t = document.createElement("div");
  t.className = "when";
  t.textContent = title;
  w.appendChild(t);
  if (!items.length) {
    const e = document.createElement("div");
    e.className = "when";
    e.textContent = "(empty)";
    w.appendChild(e);
    return w;
  }
  const ul = document.createElement("ul");
  for (const i of items) {
    const li = document.createElement("li");
    li.textContent = i;
    ul.appendChild(li);
  }
  w.appendChild(ul);
  return w;
}

// ───────────────────────────────────────────────────────────────── helpers
function banner(kind, title, text) {
  const d = document.createElement("div");
  d.className = "banner " + kind;
  const b = document.createElement("b");
  b.textContent = title;
  d.appendChild(b);
  if (text) d.appendChild(document.createTextNode(text));
  return d;
}
function hint(text) {
  const d = document.createElement("div");
  d.className = "hint";
  d.textContent = text;
  return d;
}
function hintSpan(text) {
  const s = document.createElement("span");
  s.className = "hint";
  s.textContent = text;
  return s;
}
// Anything that is or could carry a bearer capability, stripped before a body
// is rendered wholesale. A whitelist would be safer still, but this is a
// diagnostic display of an unexpected shape and blanking it would defeat it.
function redact(body) {
  const copy = Object.assign({}, body);
  for (const k of ["resume_token", "token", "authorization"]) {
    if (k in copy) copy[k] = "[redacted]";
  }
  return copy;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ──────────────────────────────────────────────────────────────── startup
//
// `?scenario=<id>` selects one; adding `&run=1` asks it immediately. That is
// how the screenshot in milestones/M04/ is taken — a headless browser cannot
// click, and a screenshot procedure that needs a human hand is one nobody can
// reproduce. `&cache=1` un-ticks the bypass, for demonstrating a cache hit.
async function main() {
  document.getElementById("ask").onclick = ask;
  document.getElementById("question").addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask();
  });
  renderProfileLine();
  renderCompare(null, null);
  document.getElementById("question").addEventListener("change", showRetained);
  await Promise.all([loadScenarios(), refreshHealth()]);

  const q = new URLSearchParams(location.search);
  const wanted = q.get("scenario");
  if (wanted) {
    const s = SCENARIOS.find(x => x.id === wanted);
    if (s) {
      selectScenario(s);
      if (q.get("cache") === "1") document.getElementById("bypass").checked = false;
      if (q.get("run") === "1") ask();
    } else {
      document.getElementById("result").appendChild(
        banner("bad", "no such scenario: " + wanted,
          "scenarios.json defines: " + SCENARIOS.map(x => x.id).join(", ")));
    }
  }
}

main();
