/*
 * The demo page, RUN — in a real browser, against scripted API responses.
 *
 * WHY THIS EXISTS. `tests/ui_verdict_spec.js` proves what `ui/verdict.js`
 * returns. It cannot prove the page acts on it, and `eng-code-reviewer` (M04,
 * F2) named two mutations that no assertion in the diff could reach:
 *
 *   · `if (taken.ok) { … }`  ->  record unconditionally
 *       A cache hit is then filed under `tier`, so the second tier's panel
 *       compares one tier's stored answer against the other's name and reports
 *       `equal` by construction. That is SPEC/04 parity control 1 defeated in
 *       the browser — the same substitution that made a Tier B scorecard read
 *       5/5 having reached AOSS zero times.
 *
 *   · `const ms = body.retrieval_ms`  ->  `const ms = roundTripMs`
 *       The browser's own stopwatch printed under the words "retrieval
 *       latency": a number about Bedrock wearing a retrieval label, which is
 *       the exact defect the whole `retrieval_ms` measurement was added to
 *       prevent.
 *
 * Both are one-line edits in `ui/index.html` that leave every other test green
 * and the file parsing. So this drives the page itself and reads the rendered
 * text back.
 *
 * NO STUBBING INSIDE THE BROWSER. A local http server serves `ui/` and answers
 * `/api/*` from a script, so the page's real `fetch`, its real same-origin
 * paths and its real localStorage are exercised. 127.0.0.1 is a secure context,
 * so `crypto.subtle` works, which is what the panel keys observations with.
 *
 * WHAT IT DOES NOT DO. Assert layout, colours or element structure — that is
 * pinning a template. It asserts what a viewer reads.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const UI = path.join(__dirname, "..", "ui");

// ───────────────────────────────────────────── the scripted API, in one place
const CITES = ["89 FR 106064", "90 FR 10592"];

function answer(over) {
  return Object.assign({
    thread_id: "t-1",
    answer: "The compliance date did not move.",
    answer_rows: [{
      product: "strawberry-frosted granola bar",
      trigger: "Updated 'healthy' definition",
      required_change: "Meet 21 CFR 101.65(d)",
      real_deadline: "2028-02-25",
      confidence: 0.97,
      citations: CITES.slice(),
    }],
    citations: CITES.slice(),
    confidence: 0.97,
    status: "ok",
    review_reason: "",
    dropped_citations: [],
    tier: "s3vectors",
    fallback_reason: null,
    retrieval_ms: 111,
    trace_id: "trace-1",
    cache: "bypass",
  }, over || {});
}

// Each /query in order. The sequence is the test.
const RESPONSES = [
  // 1. Tier A, bypassed. A real observation.
  answer({ tier: "s3vectors", cache: "bypass", retrieval_ms: 111 }),
  // 2. Tier B, but a CACHE HIT — and deliberately carrying DIFFERENT citations
  //    and a different deadline, so that recording it would be visible as a
  //    `differs` verdict rather than hiding inside an agreement.
  answer({
    tier: "aoss", cache: "hit", retrieval_ms: 999,
    citations: ["21 CFR 74.303"],
    answer_rows: [{
      product: "p", trigger: "t", required_change: "c",
      real_deadline: "1999-01-01", confidence: 0.9,
      citations: ["21 CFR 74.303"],
    }],
  }),
  // 3. Tier B, bypassed, agreeing. The tier-switch demo moment.
  answer({ tier: "aoss", cache: "bypass", retrieval_ms: 222 }),
  // 4. The hot tier is still CONFIGURED — /health says aoss below — and it
  //    failed, so S3 Vectors answered. This is the case the `tier` field
  //    exists for: the router falls back silently and by design, and before
  //    that resolution was carried onto the response a card filed under
  //    `-aoss-` could have reached AOSS zero times.
  //    `cache: "miss"` because step 4 loads WITHOUT `&bypass=1` — it doubles
  //    as the default-state probe, and the page's request says no_cache:false.
  answer({
    tier: "s3vectors", cache: "miss", retrieval_ms: 333,
    fallback_reason: "AossError: refusing to sign a request to a collection "
                   + "that does not answer",
  }),
];

const SCENARIOS = {
  scenarios: [{
    id: "healthy-claim",
    label: "'Healthy' claim — did the deadline move?",
    question: "The effective date of the new 'healthy' claim rule was delayed. "
            + "Did the compliance deadline change?",
    company_profile: { company: "Nordvale Foods" },
  }],
};

// A delay long enough that a round trip measured by the page cannot be
// mistaken for the `retrieval_ms` values above, in either direction.
const API_DELAY_MS = 1200;

// THE DEPLOYED POLICY, sent by the test server on every response.
//
// Without it this spec proved "the page works" and not "the page works under
// the policy", which are two claims — and the second is the one the split into
// index.html + app.css + app.js was for. `security-reviewer` raised it.
//
// Kept byte-identical to `core_stack.CSP` by
// `tests/test_api_hosting.py::test_the_dom_spec_serves_the_policy_the_stack_sends`,
// because a copy that drifts is a test passing under a policy nobody deploys.
const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; "
          + "connect-src 'self'; img-src 'self'; base-uri 'none'; "
          + "form-action 'none'; frame-ancestors 'none'";

// WHAT /health REPORTS, which is a different question from what answered.
// `make up` moves `/regdelta/search/endpoint`, so a real flip moves both — and
// the interesting cases are the ones where they DISAGREE, which is why this is
// scriptable rather than constant.
let healthTier = "s3vectors";

let served = 0;

// WHAT THE PAGE ACTUALLY SENT, one entry per /api/query request. The mock
// used to ignore request bodies, which left the whole bypass control — the
// checkbox default, `&cache=1`, `&bypass=1` — outside every assertion:
// eng-code-reviewer showed the suite stayed green with the `&bypass=1`
// handler deleted. The scripted `cache:` labels above say what the server
// CLAIMS; this array is what the page ASKED FOR, and the checks compare it
// per step so the two narratives cannot drift apart again.
const ASKED = [];

function startServer() {
  // `.css` IS LOAD-BEARING. A stylesheet served as text/plain is rejected by
  // the browser in standards mode, and the page then renders unstyled — which
  // here means the instrument labels lose `text-transform: uppercase` and every
  // assertion below reads a differently-cased string. The first run after the
  // page was split into index.html + app.css + app.js failed exactly that way.
  const types = { ".html": "text/html", ".js": "text/javascript",
                  ".css": "text/css", ".json": "application/json" };
  const server = http.createServer((req, res) => {
    const url = req.url.split("?")[0];
    const json = (code, obj, delay) => setTimeout(() => {
      const body = JSON.stringify(obj);
      res.writeHead(code, { "content-type": "application/json",
                            "content-security-policy": CSP,
                            "x-content-type-options": "nosniff" });
      res.end(body);
    }, delay || 0);

    if (url === "/api/health") return json(200, { status: "ok", tier: healthTier });
    if (url === "/api/query") {
      const body = RESPONSES[Math.min(served, RESPONSES.length - 1)];
      served += 1;
      // Record what the page sent before answering. A parse failure is
      // recorded as one rather than dropped — a missing entry would make the
      // per-step indices below silently assert about the wrong request.
      let sent = "";
      req.on("data", c => { sent += c; });
      req.on("end", () => {
        let parsed;
        try { parsed = JSON.parse(sent); } catch (e) { parsed = { unparseable: sent }; }
        ASKED.push(parsed);
        json(200, body, API_DELAY_MS);
      });
      return;
    }
    if (url === "/scenarios.json") return json(200, SCENARIOS);

    const name = url === "/" ? "index.html" : url.slice(1);
    const file = path.join(UI, name);
    if (!file.startsWith(UI) || !fs.existsSync(file)) {
      res.writeHead(404); return res.end("no");
    }
    res.writeHead(200, { "content-type": types[path.extname(file)] || "text/plain",
                         "content-security-policy": CSP,
                         "x-content-type-options": "nosniff" });
    res.end(fs.readFileSync(file));
  });
  return new Promise(r => server.listen(0, "127.0.0.1", () => r(server)));
}

// ──────────────────────────────────────────────────────────────── the browser
function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  return candidates.find(c => { try { return fs.existsSync(c); } catch (e) { return false; } });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let id = 0;
    const waiting = new Map();
    ws.addEventListener("message", ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id && waiting.has(msg.id)) {
        const { ok, bad } = waiting.get(msg.id);
        waiting.delete(msg.id);
        msg.error ? bad(new Error(JSON.stringify(msg.error))) : ok(msg.result);
      }
    });
    ws.addEventListener("error", reject);
    ws.addEventListener("open", () => resolve({
      send(method, params) {
        return new Promise((ok, bad) => {
          const n = ++id;
          waiting.set(n, { ok, bad });
          ws.send(JSON.stringify({ id: n, method, params: params || {} }));
        });
      },
      close: () => ws.close(),
    }));
  });
}

async function main() {
  const chromePath = findChrome();
  if (!chromePath) {
    console.log("SKIP: no chrome found (set CHROME_PATH)");
    process.exit(64);            // the python wrapper turns 64 into a skip
  }

  const server = await startServer();
  const origin = "http://127.0.0.1:" + server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "regdelta-dom-"));
  const port = 9800 + (process.pid % 150);
  const chrome = spawn(chromePath, [
    "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + profile,
    "--remote-debugging-port=" + port, "--remote-allow-origins=*",
    "about:blank",
  ], { stdio: ["ignore", "ignore", "ignore"] });

  let cdp;
  let ran = 0;
  const failures = [];
  try {
    let target = null;
    for (let i = 0; i < 80 && !target; i++) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/json/list`);
        target = (await r.json()).find(t => t.type === "page");
      } catch (e) { /* not up */ }
      if (!target) await sleep(250);
    }
    if (!target) throw new Error("chrome did not open a page target");
    cdp = await connect(target.webSocketDebuggerUrl);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");

    const text = async () => (await cdp.send("Runtime.evaluate", {
      expression: "document.body.innerText", returnByValue: true })).result.value;

    async function load(url, until, ms) {
      await cdp.send("Page.navigate", { url });
      const t0 = Date.now();
      while (Date.now() - t0 < (ms || 30000)) {
        await sleep(200);
        const t = await text();
        if (t && until(t)) return t;
      }
      throw new Error("timed out waiting for the page; last text:\n"
                      + (await text() || "").slice(0, 1500));
    }

    const check = (name, fn) => {
      ran += 1;
      try { fn(); } catch (e) {
        failures.push(name + "\n    " + String(e.message || e).split("\n").join("\n    "));
      }
    };

    // ---- 1. Tier A answers. The readout must be the SERVER's number.
    //      `&bypass=1` because the checkbox now defaults to UNTICKED (the
    //      demo URL is public; a bypassed ask spends real Opus tokens), and
    //      this step's scripted response says `cache: "bypass"` — the URL has
    //      to ask for what the script claims was served.
    let t = await load(origin + "/?scenario=healthy-claim&run=1&bypass=1",
                       x => x.includes("2028-02-25"));

    check("&bypass=1 ticks the box and the request says so", () => {
      assert.equal(ASKED.length, 1, "expected exactly one /api/query so far");
      assert.equal(ASKED[0].no_cache, true,
        "&bypass=1 did not reach the request body as no_cache: true");
    });

    // The stylesheet has to have applied before anything below is meaningful:
    // the labels these assertions match are uppercased by CSS, so an unstyled
    // page would fail them for a reason that has nothing to do with the page's
    // behaviour — and a *rewritten* assertion would then pass against a page
    // whose stylesheet never loaded.
    check("the stylesheet loaded", () => {
      assert.match(t, /RETRIEVAL LATENCY/,
        "labels are not uppercased — app.css did not apply, so nothing below "
        + "is testing what it reads as");
    });

    check("the retrieval readout shows retrieval_ms, not the round trip", () => {
      assert.match(t, /RETRIEVAL LATENCY\s*\n\s*111 ms/,
        "expected the server's 111 ms under RETRIEVAL LATENCY");
      assert.doesNotMatch(t, /RETRIEVAL LATENCY\s*\n\s*1\.\d\d s/,
        "the round trip is being printed as retrieval latency");
    });
    check("the round trip is shown separately, and is the real one", () => {
      assert.match(t, /ROUND TRIP\s*\n\s*1\.\d\d s/,
        "expected a ~1.2 s round trip in its own box");
    });
    check("the tier badge is the tier that answered", () => {
      assert.match(t, /TIER THAT ANSWERED\s*\n\s*s3vectors/);
    });
    check("the cache label is the response's", () => {
      assert.match(t, /RESPONSE CACHE\s*\n\s*bypass/);
    });
    check("the verdict table renders the row", () => {
      assert.match(t, /2028-02-25/);
      assert.match(t, /89 FR 106064/);
    });
    check("one tier only, so no verdict yet", () => {
      assert.match(t, /THE ONLY TIER SEEN SO FAR: S3VECTORS/);
      assert.doesNotMatch(t, /\bEQUAL\b|\bDIFFERS\b/);
    });

    // ---- 2. A CACHE HIT on the other tier. Control 1, in the browser.
    t = await load(origin + "/?scenario=healthy-claim&run=1&cache=1",
                   x => x.includes("not recorded as a tier observation")
                     || x.includes("EQUAL") || x.includes("DIFFERS"));

    check("&cache=1 un-ticks the box and the request says so", () => {
      assert.equal(ASKED[1] && ASKED[1].no_cache, false,
        "&cache=1 did not reach the request body as no_cache: false");
    });
    check("A CACHE HIT IS REFUSED AS A TIER OBSERVATION", () => {
      assert.match(t, /not recorded as a tier observation/);
      // The hit carried aoss, different citations and a different date. If the
      // page recorded it, the panel would now be reporting a comparison.
      assert.doesNotMatch(t, /\bEQUAL\b|\bDIFFERS\b/,
        "the page compared against a cache hit — control 1 is not enforced");
      assert.doesNotMatch(t, /CURRENT TIER: AOSS/);
      assert.match(t, /THE ONLY TIER SEEN SO FAR: S3VECTORS/);
    });
    check("the hit's stale tier and latency are labelled stored", () => {
      assert.match(t, /TIER THAT ANSWERED\s*\n\s*aoss\s*\n\s*stored/);
      assert.match(t, /RETRIEVAL LATENCY\s*\n\s*999 ms\s*\n\s*stored/);
    });

    // ---- 3. Tier B for real. The tier-switch demo moment.
    //      `make up` has happened: the SSM parameter moved, so /health moves too.
    healthTier = "aoss";
    t = await load(origin + "/?scenario=healthy-claim&run=1&bypass=1",
                   x => x.includes("EQUAL") || x.includes("DIFFERS"));

    check("the tier-switch ask was bypassed, as its scripted response claims", () => {
      assert.equal(ASKED[2] && ASKED[2].no_cache, true,
        "step 3's request did not carry no_cache: true");
    });

    check("THE TIER INDICATOR FLIPS — aoss, live, not stored", () => {
      // SPEC/04's UI clause is "an active-tier indicator that visibly flips
      // across `make up` / `make down`". Step 1 pinned `s3vectors` live and
      // step 2 pinned `aoss` STORED; this is the fourth combination and the
      // one the clause is actually about — the hot tier answering, read off
      // the response body rather than off /health.
      //
      // It is also, deliberately, what the one screenshot missing from
      // milestones/M04/ would have shown. A photograph would have covered one
      // moment on one build for the price of a ~20-minute `make up`; this
      // covers the behaviour on every build, for nothing.
      assert.match(t, /TIER THAT ANSWERED\s*\n\s*aoss\s*\n\s*observed on this response/,
        "the badge does not report the hot tier as freshly observed");
      assert.doesNotMatch(t, /TIER THAT ANSWERED\s*\n\s*aoss\s*\n\s*stored/,
        "a freshly answered response is being labelled as a cached one");
      assert.match(t, /RESPONSE CACHE\s*\n\s*bypass/);
      // And the readout is this tier's own measurement, not the previous
      // tier's 111 ms carried over.
      assert.match(t, /RETRIEVAL LATENCY\s*\n\s*222 ms/);
    });

    check("the panel reports EQUAL across the two tiers", () => {
      assert.match(t, /PREVIOUS TIER: S3VECTORS/);
      assert.match(t, /CURRENT TIER: AOSS/);
      assert.match(t, /\bEQUAL\b/);
      assert.doesNotMatch(t, /\bDIFFERS\b/);
    });
    check("the retained side survived two page loads", () => {
      // localStorage, across three navigations. The demo depends on it
      // surviving a reload during a ~20-minute `make up`.
      assert.match(t, /89 FR 106064[\s\S]*89 FR 106064/);
    });
    check("it does not claim only the infrastructure changed", () => {
      // SPEC/04 asks for equal/differs. It does not ask for a causal claim,
      // and this page cannot check the corpus did not move. (M04 F1.)
      assert.doesNotMatch(t, /did not change when the infrastructure did/);
      assert.match(t, /cannot check that only the infrastructure changed/);
      assert.match(t, /apart/);
    });
    check("each tier's own retrieval measurement is shown", () => {
      assert.match(t, /s3vectors 111 ms/);
      assert.match(t, /aoss 222 ms/);
    });

    // ---- 4. The hot tier is configured and broken. /health still says aoss.
    //      No `&bypass=1`, deliberately: this load is also the DEFAULT-STATE
    //      probe. The page loads with the checkbox as shipped, asks, and the
    //      request body says which way the default actually points.
    t = await load(origin + "/?scenario=healthy-claim&run=1",
                   x => x.includes("fell back") || x.includes("AossError"));

    check("the checkbox DEFAULTS to unticked, measured off the request", () => {
      assert.equal(ASKED[3] && ASKED[3].no_cache, false,
        "a plain page load sent no_cache: true — the bypass default "
        + "regressed to ticked, which spends Opus tokens on every visitor");
    });

    check("A SILENT FALLBACK IS MADE LOUD", () => {
      // The answer still comes back — availability is the point of the
      // fallback — but the page must not report the tier that was CONFIGURED.
      // `/health` says aoss here and s3vectors is what answered; reporting the
      // former is how two Tier A runs got scored as two-tier coverage.
      assert.match(t, /TIER THAT ANSWERED\s*\n\s*s3vectors/);
      assert.match(t, /fell back/);
      assert.match(t, /AossError/);
      assert.doesNotMatch(t, /TIER THAT ANSWERED\s*\n\s*aoss/,
        "the page is reporting the configured tier, not the one that answered");
    });
  } finally {
    try { if (cdp) cdp.close(); } catch (e) { /* closing */ }
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      const b = await connect((await r.json()).webSocketDebuggerUrl);
      await b.send("Browser.close");
      b.close();
    } catch (e) { /* fall through */ }
    for (let i = 0; i < 20 && chrome.exitCode === null; i++) await sleep(200);
    if (chrome.exitCode === null) chrome.kill();
    server.close();
  }

  if (failures.length) {
    console.error(failures.length + " failed:\n");
    for (const f of failures) console.error("  FAIL " + f + "\n");
    process.exit(1);
  }
  // COUNTED, not written down. The literal "12" was true when it was typed and
  // silently false two checks later — a tally that cannot go wrong is not a
  // measurement of anything.
  console.log(`the page behaves as rendered: ${ran} checks passed`);
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(3); });
