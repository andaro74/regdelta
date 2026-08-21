# SPEC/06 Done-when: what is deferred, and why

`SPEC/06`'s Done-when has four clauses. Two are met by the retrieval-concurrency
profile and the dashboard; **three are deferred, and this file is the record**,
because a Done-when clause with no disposition in writing is the milestone's
exit criterion left unanswered.

`eng-code-reviewer` found all three unaccounted for at M06 close: the
`loadtest/reports/` directory was empty, `locustfile.py` was still a pre-M06
locust TODO against a session-state line saying locust is no longer needed, and
the word `chaos` appeared nowhere in the repo.

---

## 1. Both `/query` load profiles — DEFERRED

> *"Profiles: 100 and 500 concurrent users, 80/20 repeated/unique questions."*
> *"Both profiles produce report artifacts in `loadtest/reports/`."*

**Reason: a quota, not a budget.** `L-ED2BADF9` caps Claude Opus 4.6 at
**2,592,000 tokens per day** and reports `Adjustable: false`. At the measured
5,881.8 Opus tokens per uncached `/query`, the 500-user profile exhausts a whole
day's cap in **13.6 seconds**, and the six runs the disposition clause asks for
are **125× the cap and $2,629**. AWS will not raise it, so no budget approves
it.

Decided by the human seat at M06 open. Written up as **Change 7** of
`milestones/M06/spec06-disposition-amendment.md`, which also prices the
alternative engineering recommended and the seat declined — running them against
Haiku 4.5 at $4.09 and $10.23 — so a later milestone can pick it up unchanged.

**Nothing is decided by their absence**: neither profile ever carried Tier B's
disposition. That is `SPEC/06`'s own "Out of scope" text as amended.

## 2. `loadtest/locustfile.py` — DELETED

It was a two-line TODO naming the two profiles above and the library that would
drive them. `locust` was never added as a dependency and is not needed: the
disposition is measured by an open-loop driver (`src/ops/retrieval_load.py`)
invoked in-region, and the profiles it was for are deferred.

A file whose whole content is a TODO for deferred work reads as *unfinished*
rather than as *deliberately deferred by the seat*, which is the opposite of
what the record should say. This file replaces it.

## 3. The Bedrock-throttle chaos test — DEFERRED, and narrowed

> *"verify graceful degradation (honest message, not a 5xx storm) when Bedrock
> throttles"* … *"a Bedrock-throttle chaos test returns the degraded-but-honest
> response."*

**The verdict-path half cannot be run here.** Reaching a genuine Opus 4.6
throttle means 3,000,000 tokens inside one minute: **$23.63** at this account's
measured input/output mix, and **115.7% of a non-adjustable DAILY cap** — so the
test would take `make evals` off the air until 00:00 UTC as its side effect. The
human seat's standing instruction at the M06 window is that Opus must not reach
throttle, and `evals/check_opus_headroom.py` now enforces it.

**The retrieval-path half is affordable and is still deferred, deliberately.**
It would be reached through Titan Text Embeddings V2's 6,000 requests/minute
ceiling (also `Adjustable: false`), producing a real `ThrottlingException` on
the retrieval path and exercising `shared.util.retry`'s 2/4/8-second backoff and
the router's fallback. It is deferred because it must not run inside the
disposition window: it deliberately exceeds a ceiling the disposition must stay
under, and a Titan throttle disqualifies a step (the amended clause's
dispositive-step condition). Running both in one window would spend the
disposition to get the chaos test.

**A simulated exception is not accepted as a substitute.** `tests/` has no
chaos test and will not grow a mocked one: asserting that a raise raises is
what ADR-0013 exists to reject, and the property being claimed —
degraded-but-honest under a REAL throttle — is precisely the one a mock cannot
establish.

Proposed as an appendix to `SPEC/06:18-19` in the amendment, with the narrowing
stated: **the verdict-path throttle is not exercised at M06**.

---

## What IS met

- **The retrieval-concurrency profile** produces
  `loadtest/reports/tier-disposition-<sha>.json` — the artifact SPEC/06's
  disposition clause names, written by `make tier-disposition`.
- **The dashboard is screenshot-ready**: `regdelta`, five alarms, two janitor
  metric filters, X-Ray active on the query path and on the load driver.

## The standing condition on all three

Every deferral above is a `SPEC/06` Done-when clause, and Done-when is the
milestone's exit criterion. **They are deferred by the human seat, not by
engineering**, and `milestones/M06/spec06-disposition-amendment.md` is where the
seat's ruling on them is recorded. If that amendment is not adopted, these
deferrals have no authority and M06 does not close.
