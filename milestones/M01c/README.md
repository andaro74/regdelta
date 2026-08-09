# M01c — The corpus asserted a deadline no document sets

- Git tag: `m01c`   Branch: `m01c-corpus-corrections`   PR: #7 (merged)
- Commits: `d2fcdb6` (ADRs + implementation) · `a9ae007` (role-gate fixes) ·
  `8504925` (SPEC/02 executability) · `29c7910` (SME rulings) ·
  `48aa922` (live-run fixes) · `398138b` (store consistency + SPEC/00, SPEC/01)
- Spec: SPEC/01 (amended)   ADRs: **ADR-0006**, **ADR-0007** (both new)
- Sessions: 1 Claude Code session

## Why this is a milestone and not part of M02
M02 is a retrieval milestone. This is ingestion correctness. It was found
while doing M02 pre-work and grew large enough that burying it inside M02
would make both illegible — M02's Done-when is "both tiers pass recall@8 =
1.0", which none of this satisfies. Exit criterion here is its own:

> **The corpus no longer asserts a date no document sets, and the amendment
> graph distinguishes a stay from a supersession.**

M02's actual deliverable — `src/retrieval/*` — is untouched and still
`NotImplementedError`.

## Done-when verification (against the live us-west-2 corpus)

| criterion | result |
|-----------|--------|
| `2025-03118` compliance date empty in all 3 stores holding it | ✅ `META.compliance_dates == []`, `compliance_date` null on all 6 chunks, absent from S3 Vectors metadata |
| META does not disagree with the chunks on any date field | ✅ both `['2025-04-28']` for effective (they diverged once — see below) |
| No stored date has day precision absent from its source | ✅ enforced by `_date_is_grounded`, deterministic |
| `2026-15920` records LIFTS_STAY + CONFIRMS and **no** SUPERSEDES | ✅ verified post-re-ingest |
| Exactly one `STAY_PERIOD` on `DOC#2025-00830`, `dates_changed=false` | ✅ `STAY_PERIOD#2025-02-18#2026-15920`, authority extracted not hardcoded |
| Re-ingest removes edges a document no longer asserts | ✅ observed live: the stale `SUPERSEDES#2025-00830` was deleted |
| `make test` green | ✅ 247 passed (169 at M01c open) |
| `make lint` green | ✅ ruff clean, `tests/` now in scope |

**Before → after, the headline row:**

```
DOC#2025-03118  compliance_dates
  before  [{"date": "2028-01-01", "applies_to": "…compliance date remains
           unchanged from the original final rule (89 FR 106064)"}]
  after   []
```

## Scorecard
No eval row. The golden set needs an answering endpoint (SPEC/04), and this
milestone changed no answer path. Its instrument is the Done-when table above.

**Baseline caveat recorded this milestone:** q08's M00b result was decided
partly by a defective assertion (it required an uncitable date), so the M00b
`3/10` control contains one coin-flip question. The scorecard was **not**
rewritten — it is frozen evidence of what was measured — but every future
delta against it must carry the caveat. See `milestones/M00b/README.md`.

## What you can demo (2-3 min)
1. `git show d2fcdb6 -- docs/adr/0006-date-attribution.md` — a fabricated
   regulatory deadline, 55 days early, in the direction that invents an
   obligation, on the central fact of demo scenario 1.
2. Query `DOC#2025-00830` in DynamoDB: a `STAY_PERIOD` interval with
   `dates_changed=false`. The dates never moved; the rule was simply not
   operative for 17.5 months. Neither "the deadline moved" nor "there is no
   deadline" is the right answer, and no date-comparison test detects that.
3. `git log` the review trail: eleven defects across four role-gate passes,
   then two more that only a live run found.

## Evidence artifacts
- ADR-0006 (date attribution, with a residual-risk section), ADR-0007 (stays)
- `.claude/skills/regulatory-domain` — stay semantics and the repeal rule
- `tests/test_ingestion_wiring.py` — the seam tests; every fix mutation-checked
- PR #7 review trail; PRs #3/#4 (branch-protection probes, closed unmerged)

## What broke / what I'd redo

> ⚠️ Written from the engineering seat. Not reviewed by the human PM.

**1. Validation catches malformed, never fabricated — and I shipped the
opposite impression.** M01 closed with four "unvalidated input" deferrals and
this milestone closed them. None of that hardening could have caught
`2028-01-01`: it is well-formed, real, and inside the plausibility window.
Only the source text can. The lesson is that an input-validation layer says
nothing about whether a value is *true*, and the M01 evidence pack implied
more coverage than it had.

**2. Four of the eleven review findings were bugs introduced while fixing
earlier findings.** Two are worth naming. The stay-interval write reintroduced
ADR-0007's own last-write-wins collision *in the same commit that fixed it for
edges*. And `_write_stay_period` hardcoded `21 U.S.C. 371(e)(2)` — fabricating
a statutory basis, which is ADR-0006's exact failure mode committed while
implementing ADR-0006. Fixing a class of bug does not confer immunity to it.

**3. A live run found two things that 240 tests and three review passes did
not.** An `applies_to` charset whitelist DLQ'd a real document over a colon in
a rule title, and the stay interval collided with itself when one document
emits both halves — which survived only because the model happened to emit
them in the lucky order. **Reversed, the graph would report Red No. 3 as still
stayed today.** Both were found in the first five minutes against real data.
The strongest argument in this milestone is for getting code in front of real
input earlier, not for more review.

**4. I purged a DLQ on an assumption and destroyed evidence.** I labelled the
messages "the 2025-03118 attempts" without checking; the one message I read
was a different document, and SQS returned one of three. Recovery worked only
because the registry-diff poller is self-healing by design. Stating an
unverified assumption as fact in an action's own description is how it got
past me.

**5. Two acceptance criteria I wrote were unusable.** One said a *non-null*
compliance date fails M02 — but ADR-0006 prescribes `[]`, which is non-null,
so the approved value failed my own criterion. The other named
`corpus/parsed/` as a store holding `compliance_dates`, which it has never
held. Both were caught by review and by verification respectively. A criterion
nobody has executed is a hypothesis.

**6. `_resolve_fr_citation` cannot resolve a citation to its document.** It
falls back to the FR API *term* search, which finds documents that **mention**
a citation, not the document that **is** it. Observed: `2026-15671` cites
"91 FR 24380"; the term search returns only `2026-15671` itself, so resolution
fails and the document DLQs permanently. The daily poller re-enqueues it until
it ages out of the 7-day window, then it is silently absent from the corpus
forever. **Recorded, not fixed** — it needs a citation-lookup strategy, and it
is a corpus-completeness hole rather than a correctness one. Related: the model
emitted a supersedes edge for a comment-period reopening, which supersedes
nothing.

**What I'd redo:** pull the live corpus and read it *before* writing the
acceptance criteria. Every defect in this milestone — the fabricated date, the
stay mislabelling, the store divergence, the wrong store name in two specs —
was visible in production data that nobody had looked at since M01 close.
