# SPEC/04 — API + Demo UI

## API (src/api/api.py — FastAPI + Mangum on Lambda)
- POST /query {question, company_profile?} → {answer_rows[], citations[],
  confidence, status, trace_id}
- POST /resume/{checkpoint_id} {reviewer_decision} → final answer
- GET  /health → includes active retrieval tier (aoss|s3vectors)
- Response cache: DynamoDB exact-match on normalized question hash, TTL 1h.
  Semantic cache OFF by default (flag SEMANTIC_CACHE=1) — a wrong cache hit
  in compliance is worse than a slow answer.

## UI (ui/ — static, S3+CloudFront)
Single page: question box; 3 canned scenario buttons; verdict table with
citation links (federalregister.gov / ecfr.gov); confidence badges;
"needs human review" state; active-tier indicator + retrieval latency
readout (the live tier-switch demo moment).

## Done when
Canned query #1 renders the full Nordvale table in a browser against the
deployed stack; /health reports the correct tier before and after
`make up`; a cached repeat query returns < 500ms.

Plus — **the prose assertions SPEC/02 relocated here**:
`python evals/run_evals.py --subset retrieval` passes against the deployed
API on BOTH tiers (search stack down, then up). M02 measures retrieval at
the `router.retrieve()` contract because no answering endpoint exists yet;
this milestone is the first point at which those questions can run as
written, and it is where they become binding. See SPEC/02 "Why not the
golden set here" — that deferral is only honest if this clause holds.

This also re-verifies SPEC/00's "same golden set must pass on both paths":
after M02, cross-tier evidence is chunk-level only, so the live tier-switch
demo moment above has no answer-level verifier until this runs.

### Answer-level cross-tier comparability (owed by ADR-0009)
Passing the same assertions on both tiers is **not** the same as producing
comparable *answers*, and the tier-switch demo beat sells the latter. ADR-0009
recorded this as unhomed; it is homed here.

**Done when:** for each of the three canned scenarios, `/query` is answered once
per tier at one sha and the two responses agree on (a) every `citations[]` entry
— FR doc number and CFR section, as sets — and (b) every `real_deadline` in
`answer_rows[]`, exactly. Confidence may differ; prose may differ. **A citation
or a date that changes when only the infrastructure changed is a bug**, by the
same argument that makes an uncited answer a bug rather than a style issue.

This became cheaper, not harder, after ADR-0009 Ruling 3(a): both tiers now run
the same retrieval algorithm and their chunk-level scorecards agree to sixteen
digits of MRR, so a disagreement here indicates the *answer* layer is
non-deterministic across tiers rather than that retrieval differs. That is worth
knowing either way, which is why the criterion stays even though it is now
expected to pass easily.

### Tier B's latency claim (owed by ADR-0009 Ruling 3(a))
Ruling 3(a) retired Tier B's relevance justification: with the lexical lane off
it runs the same algorithm as Tier A, so what it earns its cost with is **latency
and concurrent load**. The UI above already displays a retrieval-latency readout;
displaying a number is not asserting one, and **retiring an unmeasured hybrid
claim in favour of an unmeasured performance claim would be the same defect in
new clothes.**

**Done when:** the readout is populated from a real measurement on both tiers at
one sha — median and p95 `router.retrieve()` latency over the probe set, recorded
in the scorecard — and the demo narration cites only what that measurement shows.
**No target is set here.** A threshold invented before the first measurement
would be fitted to nothing, and if Tier B turns out *not* to be meaningfully
faster on this corpus size, that is a finding to record and a demo beat to drop —
not a number to tune until it passes. Deciding what to do with the result is a
PM-seat call once the number exists.
