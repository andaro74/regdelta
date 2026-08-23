/*
 * Shared helpers for the two L3 specs. No assertions live here — a helper that
 * asserts is a place an assertion can be weakened without appearing in either
 * spec's diff, and SPEC/08 Done-when 6 makes those two files the
 * pre-registration.
 */
import { Locator, Page, TestInfo } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { APP_URL } from "../playwright.config";

/**
 * The scenario button for a canned scenario, located by its ID.
 *
 * BY ID, NOT BY LABEL, and that is a decision. `evals/scenarios.json` is
 * PM-seat owned and its `label` is prose that can be reworded; the `id` is the
 * canonical handle the whole repo keys on (`make demo-parity` iterates it,
 * SPEC/04 gates on "the scenario with id `healthy-claim`"). A selector keyed
 * to the label is a criterion whose subject can move without a diff — this
 * repo's trap-census defect class — so this one is keyed to the id the page
 * renders in `.sid`.
 *
 * If `scenarios.json` did not load, the page renders a banner instead of
 * buttons and this locator finds nothing. That is a FAILURE, not a skip.
 */
export function scenarioButton(page: Page, id: string): Locator {
  return page.locator("#scenarios button").filter({
    has: page.locator(".sid", { hasText: new RegExp(`^${id}$`) }),
  });
}

export interface Instruments {
  tier: string;
  tierNote: string;
  cache: string;
  configuredTier: string;
  retrieval: string;
  roundTrip: string;
}

/**
 * The instrument strip, read as a viewer reads it.
 *
 * `#configured-tier` is read off its `.pill`, not off the line's full text:
 * `refreshHealth()` writes the bare string "configured tier: unavailable" with
 * NO pill when `/api/health` does not answer, so an absent pill is itself the
 * proxy-failure signal rather than a value to be parsed out of prose.
 *
 * Every value is CLAMPED. These are page-controlled strings on their way into
 * a committed card (`record_verdict.py` copies `tierNote` into `fallbacks[]`),
 * and a page that returned a megabyte of prose would put it there. The clamp
 * is far above any real value — `security-reviewer` M2, lower-grade instance.
 */
export async function readInstruments(page: Page): Promise<Instruments> {
  const text = async (sel: string) => {
    const el = page.locator(sel);
    if ((await el.count()) === 0) return "";
    return (await el.first().innerText()).trim().slice(0, 200);
  };
  return {
    tier: await text("#i-tier"),
    tierNote: await text("#i-tier-note"),
    cache: await text("#i-cache"),
    configuredTier: await text("#configured-tier .pill"),
    retrieval: await text("#i-retrieval"),
    roundTrip: await text("#i-roundtrip"),
  };
}

/**
 * What this run OBSERVED, onto the report, for `record_verdict.py`.
 *
 * SPEC/08's record clause: `tier` and `cache_statuses` on the card are
 * observed, not asserted — read off the page's instrument strip, which reads
 * them off the response body. This is the attachment that carries them, so the
 * card cannot claim a tier nobody saw.
 *
 * `appUrl` IS IN HERE FOR THE SAME REASON, and it was missing. The recorder
 * used to re-derive the URL from `playwright.config.ts` at record time, but
 * `make ui-record` is a separate process with no `APP_URL` in it — so
 * `make ui-tests APP_URL=http://127.0.0.1:8000 && make ui-record` filed a
 * loopback run as `layer: "L3"` against the deployed URL, which is exactly the
 * mislabelling `_layer()` exists to prevent, one function above it. The card's
 * URL now comes from the process that opened the browser.
 * `eng-code-reviewer` H3 / `security-reviewer` M3.
 */
export async function attachObservation(
  testInfo: TestInfo,
  scenario: string,
  inst: Instruments,
): Promise<void> {
  await testInfo.attach("observed", {
    contentType: "application/json",
    body: Buffer.from(
      JSON.stringify({ scenario, appUrl: APP_URL, ...inst }, null, 2), "utf8"),
  });
}

/**
 * The resume token's shape, DERIVED from `src/api/resume_token.py`.
 *
 * SPEC/08 Spec 2, justification 4: derived, not transcribed. `mint()` is
 * `secrets.token_urlsafe(_TOKEN_BYTES)`, which is base64url of N random bytes
 * with padding stripped — ceil(N*4/3) characters drawn from [A-Za-z0-9_-].
 *
 * Both halves of that sentence are checked against the file, and a failure to
 * read either one THROWS rather than falling back to a hardcoded 43. A silent
 * fallback is how a derived constant becomes a transcribed one: the source
 * moves, the regex does not, and the spec that says "derived" is describing a
 * literal.
 *
 * At the current `_TOKEN_BYTES = 32` this is 43 characters, which excludes
 * what else the page renders: a uuid4 `thread_id` is 36 characters and a
 * sha256 hex digest is 64. `tests/test_ui_surface_pins.py` recomputes this
 * derivation in Python and drives it against a REAL minted token, a uuid4 and
 * a sha256 digest — the positive control this had none of.
 */
export function resumeTokenPattern(): { source: string; length: number; bytes: number } {
  const src = path.resolve(__dirname, "..", "..", "src", "api", "resume_token.py");
  const text = fs.readFileSync(src, "utf8");

  const bytes = /_TOKEN_BYTES\s*=\s*(\d+)/.exec(text);
  if (!bytes) {
    throw new Error(
      `cannot read _TOKEN_BYTES from ${src}. SPEC/08 requires this pattern to be ` +
        "derived from the source, not transcribed — re-derive it rather than " +
        "hardcoding a length here.",
    );
  }
  if (!/secrets\.token_urlsafe\(\s*_TOKEN_BYTES\s*\)/.test(text)) {
    throw new Error(
      `${src} no longer mints with secrets.token_urlsafe(_TOKEN_BYTES). The ` +
        "alphabet and padding this pattern assumes are that function's; re-derive " +
        "the pattern from whatever replaced it (SPEC/08, Spec 2).",
    );
  }

  const n = Number(bytes[1]);
  const length = Math.ceil((n * 4) / 3);
  return {
    source: `(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{${length}}(?![A-Za-z0-9_-])`,
    length,
    bytes: n,
  };
}

export interface TokenHit {
  where: string;
  match: string;
  node: string;
}

/** Never print a capability to prove it was printed. */
function redact(s: string): string {
  return s.slice(0, 6) + "…[redacted, " + s.length + " chars]";
}

/**
 * Every place in the SERIALIZED DOM that looks like a resume token.
 *
 * `page.content()` AND A SCAN IN NODE, not `page.evaluate`. The first version
 * walked the DOM inside the page's own JavaScript context, where `RegExp`,
 * `Node`, `Array.from` and `Element.prototype.attributes` are all
 * page-overridable — so the one security assertion in this suite could be made
 * to return `[]` by the very page it is inspecting. An XSS'd `app.js`, a
 * skewed deployed asset or a hostile `APP_URL` would each have been enough.
 * `security-reviewer` M1.
 *
 * The serialization is also WIDER than that walk was. `page.content()`
 * includes comment nodes and `<template>` content, both of which the walk
 * skipped — each a one-line `ui/app.js` mutation that would have published the
 * capability with this suite green. `eng-code-reviewer` M9.
 *
 * WHAT IT STILL DOES NOT SEE, stated rather than left to be found: closed
 * shadow roots, and documents inside child frames. `ui/` renders neither on
 * the answer path, and if it ever does this helper has to grow with it.
 *
 * REPORTS THE SURROUNDING MARKUP, not a boolean. Any unrelated 43-character
 * run fails the suite, and under SPEC/08's red-closes-red ruling a spurious
 * red is expensive enough that it has to be diagnosable rather than a mystery.
 *
 * EVERYTHING IT REPORTS IS REDACTED — the match AND the window around it. The
 * first version redacted only the match and then printed `outerHTML` beside
 * it, which contains the match in full; `record_verdict.py` copies failure
 * messages verbatim into a COMMITTED card, so the day this assertion caught a
 * real leak it would have committed the capability to the repository. The
 * comment here said that must not happen while the code did it.
 * `security-reviewer` H1.
 */
export async function tokenLikeNodes(page: Page, pattern: string): Promise<TokenHit[]> {
  const html = await page.content();
  const scan = new RegExp(pattern, "g");
  const hits: TokenHit[] = [];
  let m: RegExpExecArray | null;
  while ((m = scan.exec(html)) !== null) {
    const from = Math.max(0, m.index - 200);
    const to = Math.min(html.length, m.index + m[0].length + 200);
    hits.push({
      where: `serialized DOM, byte offset ${m.index}`,
      match: redact(m[0]),
      // Redacted across the whole window, not just at the hit: a window can
      // contain a second token-shaped run, and one of them escaping is the
      // same leak as both.
      node: html.slice(from, to).replace(new RegExp(pattern, "g"), redact),
    });
  }
  return hits;
}
