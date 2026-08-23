# Browser testing in RegDelta — how Playwright works, and how it is wired here

This explains two things: what Playwright actually does when you run
`make ui-tests`, and why the demo page is tested at three different layers
rather than one.

Written for someone who has not used Playwright before. If you have, skip to
[How it is wired here](#how-it-is-wired-here).

---

## What Playwright is

Playwright is a library for driving a **real browser** from code. Not a
simulated DOM, not a screenshot comparison — an actual Chromium process, the
same engine as Chrome, opening a real page over a real network connection.

Three ideas cover almost everything:

**1. A browser you control from a script.** Playwright launches Chromium
headless (no visible window), opens a page, and gives you an object to drive
it: `page.goto("/")`, `button.click()`, `page.content()`.

**2. Locators, not elements.** When you write

```ts
const button = page.locator("#scenarios button");
```

you have **not** found anything yet. A locator is a *description* of how to
find something — it is re-evaluated every time you use it. This matters on a
page that changes after an API call: the locator does not go stale.

**3. Assertions that wait.** This is the part that surprises people:

```ts
await expect(result).toContainText("NEEDS HUMAN REVIEW");
```

does not check once and fail. It polls — re-reading the page every ~100 ms —
until the text appears or a timeout expires. So there are no `sleep(5000)`
calls anywhere in this suite. You say what should become true, and Playwright
waits for it.

The corollary bit them once here, and it is worth understanding: **a negative
assertion polls too.** `toHaveCount(0)` on an element that *is* present keeps
re-checking, hoping it disappears, for the whole timeout. That is why one
assertion in this suite carries an explicit short timeout — see
[The timeout trap](#the-timeout-trap).

---

## Why three layers

The demo page is checked at three levels. Each one can see something the others
cannot, and — more importantly — each one is **blind** to something specific.

| | what it runs | what answers it | blind to |
|---|---|---|---|
| **L1** | `tests/test_api.py` | the real API, in-process, with the agent stubbed out | any browser; anything deployed |
| **L2** | `tests/ui_dom_spec.js` | the real page in a real browser, against **scripted** API responses | the real API, the real answer, the real CloudFront distribution |
| **L3** | `ui-tests/` (Playwright) | **the deployed stack** | shadow DOM, iframes, other browsers |

The key sentence: **L2 is green against a stack that is entirely down.** It
ships its own fake answers, so it proves the page *renders correctly* and
proves nothing about whether the deployed system still works. That is not a
flaw — it is what makes L2 fast and free — but it leaves a gap, and L3 is that
gap:

- CloudFront serving a page nobody redeployed
- the `/api/*` proxy no longer reaching the API
- the Lambda missing a dependency (this actually happened: every request
  answered "No module named 'fastapi'")
- the agent quietly changing its answer

None of those is visible at L1 or L2. All of them fail L3 immediately.

**L2 is not redundant and must not be deleted.** L3 alone cannot tell "the page
is broken" from "the stack is broken". Running both is what separates the two.

---

## How it is wired here

### The files

```
ui-tests/
  package.json              @playwright/test, Chromium only — the repo's only npm dependency
  package-lock.json         exact versions, checked by `npm ci`
  playwright.config.ts      where the browser points, timeouts, no retries
  tests/
    _page.ts                shared helpers — no assertions live here
    healthy-claim.spec.ts   Spec 1: does the deployed stack render the right verdict?
    needs-review.spec.ts    Spec 2: does it pause, and does it keep the secret?
  record_verdict.py         turns the run into a permanent evidence record
```

Everything is isolated in `ui-tests/` with its own `package.json`, so nothing
here can reach the rest of the repo's tooling.

### What one run actually does

`make ui-tests`, step by step:

1. **Resolve the deployed environment** — reads the real Lambda's configuration
   so the run knows which corpus and tables are live.
2. **Check the token budget.** Every uncached question costs ~5,900 Opus tokens
   against a daily cap that *cannot be raised*. If there is not enough left, the
   run refuses here, before spending anything.
3. **Install** — `npm ci` (exact lockfile versions) and download Chromium if it
   is not already cached. A fresh clone needs no separate setup step.
4. **Run the two specs**, one at a time, in one Chromium instance.

Each spec does the same opening moves: open the deployed page, find the canned
scenario button, click it, wait for the answer, read the rendered page back.

The button is found by its **scenario id**, not its label:

```ts
page.locator("#scenarios button").filter({
  has: page.locator(".sid", { hasText: /^healthy-claim$/ }),
});
```

The label is product copy that can be reworded at any time; the id is the
canonical handle the whole repo keys on. A test keyed to the label would
silently stop testing the thing it names.

### Spec 1 — `healthy-claim`

Asks the demo's signature question and checks what a viewer actually sees:

- every deadline cell reads **2028-02-25** (the trap: the effective date moved,
  the compliance date did not)
- both source citations are in the citation list
- no cell is blank, no confidence badge reads "no confidence", no
  "row carries no citation" warning — together, that the answer came back
  *complete*
- the instrument strip reads a real tier and a legal cache state, and
  `/health` answered through the CloudFront proxy

### Spec 2 — `needs-review`

Asks a question with no company in it — "are we affected?" — which the system
is supposed to refuse to answer. It checks, **in this order**:

1. the page shows **NEEDS HUMAN REVIEW**
2. the page says a **resume capability was minted**
3. *then* the negatives: no deadline is shown, and nothing anywhere in the
   page's HTML looks like the access token

**The order is the point.** Both negatives are trivially true before the answer
arrives — an empty page has no deadline and no token in it. Checked first, they
would pass against a page that never answered anything. They run only after the
two positives prove the page responded.

Point 2 is subtler than it looks. That sentence is rendered *only* when the
response actually carried a token — so asserting it means "the secret reached
the browser **and** the page chose not to display it", which is a much stronger
claim than "the page said something reassuring".

### How the token check works

The system mints a one-time-ish access token when it pauses for human review.
The page must never print it. To check that, the test needs to know what a token
*looks like* — and it works that out from the source rather than hardcoding it:

1. read `src/api/resume_token.py`
2. confirm it still mints with `secrets.token_urlsafe(_TOKEN_BYTES)`
3. compute the resulting length: 32 bytes of base64url → **43 characters** of
   `A–Z a–z 0–9 _ -`
4. scan the page's entire serialized HTML for anything of that shape

If the source ever changes, the test throws rather than quietly checking for a
format nothing produces.

Two details that matter:

- **The scan happens in Node, not in the browser.** An earlier version walked
  the DOM using JavaScript running *inside the page* — where the page could
  have overridden `RegExp` and forced the answer to be "nothing found". Reading
  the serialized HTML out of the browser cannot be faked by the page.
- **Everything it reports is redacted.** If the check ever fires, its failure
  message ends up in logs and in a committed file. Printing the secret to prove
  the secret was printed would be the bug wearing a test's clothes.

---

## The evidence record

`make ui-record` turns the run into a permanent file:
`evals/history/<commit>-playwright.json`.

It carries what passed, what failed (with the full assertion text), which tier
answered, whether each response was a cache hit or miss, which URL the browser
actually visited, and how long it took.

Three deliberate behaviours:

- **It refuses to record from a dirty working tree.** A measurement filed under
  a commit that cannot reproduce it is worse than no measurement, because it
  survives and reads like a verified claim. (`ARGS=--allow-dirty` overrides and
  stamps the record provisional.)
- **A second run at the same commit does not overwrite the first.** The earlier
  one is moved to `evals/history/superseded/` and the live record names it. So
  "I ran it until it went green" is visible rather than invisible.
- **It records failures faithfully.** A recorder that can only file victories
  is not evidence. Its exit code says whether a record was *written*, never
  whether the tests passed.

The record is deliberately shaped so the golden-set tooling ignores it — it is
not a question-answering score and must never show up in one.

---

## The guardrails

These exist because a browser suite pointed at a live, paid system has failure
modes a normal unit test does not.

**Cost.** Every run can spend real tokens against a cap that cannot be raised.
So: the run checks the budget before it starts, and **no test ever ticks the
"bypass the cache" box** — a cache hit is a perfectly good way to prove the
page and the network path work. `tests/test_ui_surface_pins.py` fails if a test
tries.

**It fails closed.** There is no skip path. Missing browser, unreachable URL,
missing button — all failures, never skips. A skipped test shows a green tick
for something that did not run.

**No retries.** If a test fails, that is the finding. Retrying until green is
how a real defect turns into a footnote.

**The assertions are pinned.** `tests/test_ui_surface_pins.py` (which runs in
the ordinary `make test`) checks that every pre-registered value is still in a
spec file Playwright actually executes, that the token-format derivation still
matches real tokens, and that the assertion order in Spec 2 has not been
shuffled. It was written because reviewers found several one-line edits that
would have quietly deleted a real finding while every other check stayed green
— renaming a spec file so the runner stops collecting it, for instance.

### The timeout trap

Worth knowing because it produced a genuinely misleading result once.

The config allows 60 s per test and 55 s per assertion. Spec 2's deadline check
is a negative, so when it failed it polled for the full 55 s — and the two
checks before it had already used ~15 s. 15 + 55 > 60, so the test was killed
mid-assertion and **everything after that line never ran**, including the token
check. The run reported a failure, which was correct, but the security check
had silently not happened.

The fix, which loosens nothing: that one assertion is `expect.soft` (it still
fails the test, but execution continues) with a 5-second timeout (the page has
demonstrably already rendered by then). Now a failure in one check cannot hide
the verdict of another.

---

## Running it

```bash
make ui-tests                              # against the deployed demo
make ui-tests APP_URL=https://other-url    # somewhere else
make ui-record                             # file the result as evidence
```

Needs AWS credentials (to resolve the environment and check the token budget)
and network access. Chromium and the npm packages install themselves.
Takes roughly 30–80 seconds.

**Today, one of the two specs fails, and that is the recorded state, not a
broken setup.** The `needs-review` scenario pauses for human review *and*
renders a full answer with a deadline and 95% confidence for a company profile
that is empty. See `milestones/M08/README.md` — the failure is the finding, and
fixing it is a separate decision about which layer should change.

### One safety note

Each run mints a real access token, and Playwright writes the raw API response
into its failure trace on disk. Those traces are ignored by git, but:

- **do not attach or share a Playwright trace from this suite**
- delete `ui-tests/test-results/` after you have read one

The full argument for every design decision above is in
[SPEC/08-ui-surface.md](../SPEC/08-ui-surface.md), which was written and
reviewed before any of this code existed.
