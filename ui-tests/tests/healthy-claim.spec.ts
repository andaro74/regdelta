/*
 * SPEC/08 Spec 1 — `healthy-claim`, against the deployed stack.
 *
 * WHAT THIS CATCHES THAT L1 AND L2 CANNOT (SPEC/08's control):
 *   1. deployed-asset skew — the bucket holding a page nobody redeployed
 *   2. the /api/* proxy at runtime — pinned at the synthesized template by
 *      tests/test_api_hosting.py, exercised by nothing
 *   3. the deployed function answering at all (M04 shipped one that replied
 *      "No module named 'fastapi'" to every invoke)
 *   4. q01's trap surviving into the browser — at L2 that date is a constant
 *      in the test file, so L2 is green against a stack that is entirely down
 *   5. #i-tier naming a real tier — a body that never reached retrieval
 *      renders "none"
 *   6. the cache label being on-contract in what LAMBDA returns
 *
 * THE BYPASS CHECKBOX IS NEVER TICKED, here or anywhere in this suite. Every
 * bypassed ask is ~5,881.8 Opus tokens against L-ED2BADF9 — 2,592,000/day,
 * `Adjustable: false`. A cache hit is acceptable and is recorded as one; what
 * a hit cannot support is the FRESHNESS half of the trap claim, because the
 * body is replayed from up to an hour ago. SPEC/08 says so and the card
 * carries which happened.
 */
import { expect, test } from "@playwright/test";
import { attachObservation, readInstruments, scenarioButton } from "./_page";

const DEADLINE = "2028-02-25";
const CITATIONS = ["89 FR 106064", "90 FR 10592"];
const TIERS = ["aoss", "s3vectors"];
const CACHE_STATES = ["hit", "miss", "bypass", "disabled"];

test("the healthy-claim verdict renders against the deployed stack", async ({ page }, testInfo) => {
  await page.goto("/");

  // The button has to EXIST. If scenarios.json did not load, the page renders
  // a banner where the buttons go, and this is where that becomes a failure
  // rather than a suite with nothing to click.
  const button = scenarioButton(page, "healthy-claim");
  await expect(button, "the healthy-claim scenario button is not on the page").toHaveCount(1);

  // The button selects the scenario AND asks, in one handler. The checkbox is
  // left exactly as the page ships it — untouched, which is the cost control.
  await expect(page.locator("#bypass")).not.toBeChecked();
  await button.click();

  const result = page.locator("#result");
  const rows = result.locator("table tbody tr");
  await expect(rows.first(), "no verdict row rendered").toBeVisible();

  // ── the deadline. EVERY row, not any row.
  const deadlines = result.locator("td.deadline");
  const seen = await deadlines.allInnerTexts();
  expect(seen.length, "the table rendered no deadline cell at all").toBeGreaterThan(0);
  for (const d of seen) {
    expect(d.trim(), `a verdict row's real_deadline is not ${DEADLINE}`).toBe(DEADLINE);
  }

  // ── the citations, in the RESPONSE-LEVEL list.
  //    `citesCell(cites, true)` renders that list as a div wrapping div.cites,
  //    appended straight to the card; the per-row lists are the same div.cites
  //    inside a <td>. `.card > div > .cites` is therefore the response-level
  //    one and not a row's — which is what "the rendered Citations list"
  //    means in SPEC/08, and the reason it is not just a page-wide text match.
  const citationList = result.locator(".card > div > .cites");
  await expect(citationList, "no response-level Citations list rendered").toHaveCount(1);
  for (const cite of CITATIONS) {
    await expect(
      citationList,
      `the answer does not cite ${cite}`,
    ).toContainText(cite);
  }

  // ── "full": three assertions, because the page renders an absent field
  //    three different ways (SPEC/08 Spec 1, and pm-spec-reviewer N8 — the
  //    em dash alone covers three of six columns).
  //
  //    (a) product / trigger / required_change go through `td()`, which writes
  //        the em dash for null, undefined or "".
  const cells = await result.locator("table tbody td").allInnerTexts();
  for (const cell of cells) {
    expect(cell.trim(), "a verdict cell rendered the em dash — a field came back empty")
      .not.toBe("—");
  }
  //    (b) confidence is a badge, not a td(): `confidenceBadge` writes the
  //        words "no confidence" for a null and never an em dash.
  await expect(
    result.locator("table tbody td .pill", { hasText: "no confidence" }),
    "a verdict row carries no confidence value",
  ).toHaveCount(0);
  //    (c) citations on a ROW render as an empty cell, not an em dash. The
  //        page already has the instrument — `V.uncitedRows` raises a banner,
  //        and it is stronger than "the list is non-empty" because it filters
  //        on normCite, so a row citing unparseable junk fires it too.
  //        CLAUDE.md: an answer without citations is a bug, not a style issue.
  await expect(
    result.locator(".banner b", { hasText: "a verdict row carries no citation" }),
    "a verdict row cites nothing the page could parse",
  ).toHaveCount(0);

  // ── the instrument strip, read off the response body.
  const inst = await readInstruments(page);
  await attachObservation(testInfo, "healthy-claim", inst);

  expect(
    TIERS,
    `#i-tier reads ${JSON.stringify(inst.tier)} — "none" means this run never ` +
      "reached retrieval, and the em dash means the strip was never rendered",
  ).toContain(inst.tier);

  expect(
    CACHE_STATES,
    `#i-cache reads ${JSON.stringify(inst.cache)}, which is off SPEC/04's contract ` +
      "(exactly one of hit | miss | bypass | disabled). If this is `uncacheable`, " +
      "that is a SPEC/04 contract change and must be read as one — not widened away here.",
  ).toContain(inst.cache);

  expect(
    TIERS,
    `#configured-tier reads ${JSON.stringify(inst.configuredTier)} — empty means ` +
      "GET /api/health did not answer through the CloudFront /api/* proxy, and " +
      '"unknown" means it answered with no tier in the body',
  ).toContain(inst.configuredTier);
});
