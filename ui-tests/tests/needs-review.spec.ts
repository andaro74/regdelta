/*
 * SPEC/08 Spec 2 — `needs-review`: the pause, and the capability the page must
 * not print.
 *
 * WHAT THIS CATCHES THAT L1 AND L2 CANNOT:
 *   1. Every one of `tests/ui_dom_spec.js`'s four scripted responses is
 *      `status: "ok"`. The `needs_input | pending_review` branch of
 *      `renderResult` — SPEC/04's required "needs human review" state, and the
 *      only reason the `needs-review` scenario exists — has never been
 *      rendered by any test at any layer. This is the first check of any kind.
 *   2. The DEPLOYED graph really pauses: hitl_gate, the confidence threshold
 *      and the DynamoDB checkpointer all live in the deployed function. L1
 *      stubs the graph and proves a STUBBED pause mints a token.
 *   3. "resume capability was minted" renders only when `body.resume_token` is
 *      truthy, so asserting it is not "the page said something reassuring" —
 *      it is THE TOKEN WAS PRESENT IN THE RESPONSE AND THE PAGE DECLINED TO
 *      DISPLAY IT. A page that printed the token would pass a "does it pause"
 *      check just as well.
 *   4. The token is absent from the serialized DOM, not merely from the
 *      visible text.
 *   5. No deadline on a paused run: a pause means no answer is being asserted,
 *      and a page rendering both would be asserting one anyway.
 *
 * THIS SPEC COSTS ON EVERY RUN AND CANNOT BE MADE NOT TO.
 * `response_cache.cacheable()` refuses to store any body carrying a
 * `thread_id` or a `resume_token` — correct, a capability must not be cached —
 * so the paused scenario is a guaranteed miss. One uncached graph run per
 * execution, budgeted in SPEC/08's cost posture.
 *
 * ORDER IS LOAD-BEARING. Both negatives below are trivially true BEFORE the
 * response arrives: an empty #result has no deadline cell and no token in it.
 * They run only after the two positives hold, or they would be green against a
 * page that never answered — green by construction, the shape this repository
 * has already found four times. pm-spec-reviewer M7.
 */
import { expect, test } from "@playwright/test";
import {
  attachObservation,
  readInstruments,
  resumeTokenPattern,
  scenarioButton,
  tokenLikeNodes,
} from "./_page";

const PAUSE = "NEEDS HUMAN REVIEW";
const MINTED = "resume capability was minted";

test("the pause renders and the resume capability is never printed", async ({ page }, testInfo) => {
  await page.goto("/");

  const button = scenarioButton(page, "needs-review");
  await expect(button, "the needs-review scenario button is not on the page").toHaveCount(1);

  await expect(page.locator("#bypass")).not.toBeChecked();
  await button.click();

  const result = page.locator("#result");

  // ── 1. the pause itself
  await expect(
    result,
    "the deployed graph did not pause for review on the question that has no asker in it",
  ).toContainText(PAUSE);

  // ── 2. the token reached the browser AND was withheld
  await expect(
    result,
    "no capability was minted — either the run is not resumable (no checkpoint " +
      "was written) or the response carried no resume_token, and neither is the " +
      "state this scenario demonstrates",
  ).toContainText(MINTED);

  const inst = await readInstruments(page);
  await attachObservation(testInfo, "needs-review", inst);

  // ── 3. only now, the negatives.
  //
  // SOFT, AND ON A SHORT TIMEOUT, and both are repairs rather than
  // concessions. The first version was a hard assertion inheriting the 55s
  // expect timeout: a negative that is violated polls for the whole window, so
  // 15s of round trip plus 55s of polling blew the 60s test timeout and
  // EVERYTHING BELOW THIS LINE BECAME DEAD CODE — deterministically, whenever
  // this assertion fails. That put the capability check, which is the
  // security-relevant one, permanently behind a known-failing product
  // assertion, and it is why M08's first run reported a token scan that never
  // executed. `expect.soft` keeps the failure (the test still goes red) while
  // letting the scan below run; the 5s timeout removes no waiting the
  // assertion needs, because the two auto-retrying positives above have
  // already proved the page rendered. `eng-code-reviewer` H1/H2,
  // `security-reviewer` H3.
  await expect.soft(
    result.locator("td.deadline"),
    "a paused run rendered a deadline — a pause means no answer is being asserted",
  ).toHaveCount(0, { timeout: 5_000 });

  // ── 4. and nothing token-shaped anywhere in the DOM.
  const pattern = resumeTokenPattern();
  const hits = await tokenLikeNodes(page, pattern.source);
  expect(
    hits,
    `something matching the resume token's shape (${pattern.length} chars of ` +
      `[A-Za-z0-9_-], derived from _TOKEN_BYTES=${pattern.bytes} in ` +
      "src/api/resume_token.py) is in the served DOM:\n" +
      hits.map((h) => `  · ${h.where}: ${h.match}\n    ${h.node}`).join("\n") +
      "\n\nIf this is a real token the page is publishing a bearer capability " +
      "and that is the finding. If it is an unrelated 43-character run, the " +
      "derivation above is what needs revisiting — not this assertion.",
  ).toEqual([]);
});
