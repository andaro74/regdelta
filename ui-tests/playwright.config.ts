/*
 * SPEC/08 — the UI surface, against the deployed stack.
 *
 * L3. `tests/ui_dom_spec.js` (L2) drives the same page in a real browser
 * against SCRIPTED API responses; `tests/test_api.py` (L1) drives the real API
 * in-process with the graph stubbed. Neither touches a deployed byte. This
 * config points a browser at the distribution.
 *
 * RETRIES 0, DELIBERATELY. SPEC/08's ruling is that a red result closes the
 * milestone red: the failure is the finding, recorded as-run, not retried
 * until it agrees. A retry here would be the loosening that ruling forbids,
 * spelled as a config value instead of as an edited assertion — and it would
 * spend a second uncached graph run to do it.
 *
 * NO SKIP PATH ANYWHERE. If Chromium is missing, the URL is unreachable, the
 * page does not load or a scenario button is absent, this suite FAILS. L2
 * exits 64 for "no chrome found" and the python wrapper turns that into a
 * SKIP, which is right there because chrome is not a declared dependency;
 * here Chromium IS one, and a skip would be a green check for a thing that did
 * not run. That is what `fail_closed: true` on the recorded card asserts.
 */
import { defineConfig, devices } from "@playwright/test";

// SPEC/08: default to the deployed distribution, overridable by env. The
// default is the URL in README.md and docs/demo-walkthrough.md.
export const APP_URL = process.env.APP_URL || "https://d2rdgeiujg622n.cloudfront.net";

export default defineConfig({
  testDir: "./tests",

  // A cache miss runs the full graph and takes ~10-13s through Lambda; the
  // paused scenario is a guaranteed miss (a body carrying a resume_token is
  // never cached). 60s leaves room for a cold start without leaving so much
  // that a hung request looks like a slow one.
  timeout: 60_000,
  expect: { timeout: 55_000 },

  retries: 0,
  forbidOnly: true,

  // SERIAL, one worker. Two specs, each of which can spend an uncached graph
  // run against a NON-ADJUSTABLE daily Opus cap. Nothing here needs
  // concurrency, and concurrency against Bedrock is SPEC/06's subject, not
  // this file's.
  fullyParallel: false,
  workers: 1,

  reporter: [["list"], ["json", { outputFile: "results/playwright.json" }]],

  use: {
    baseURL: APP_URL,
    // Kept only for a run that failed. The trace is what a reader of a red
    // M08 opens; keeping traces for green runs would put megabytes beside a
    // card that says nothing happened.
    trace: "retain-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
