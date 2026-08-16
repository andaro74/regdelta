# SPEC/03 — Agent Graph (LangGraph)

## Goal
The reasoning layer: supervisor → parallel {retrieval, timeline, crossref}
→ applicability → verdict (+citations) → [HITL pause if confidence < 0.7].

## Nodes (src/graph/nodes.py)
- supervisor: classify intent, decompose, set company profile from request.
- retrieval_agent: calls the retrieval router (SPEC/02).
- timeline_agent: answers date questions from the DynamoDB amendment graph —
  walks SUPERSEDES edges with scope; NEVER from similarity search.
- crossref_agent: resolves "as defined in §", incorporation-by-reference,
  cross-agency triggers (FDA reformulation → TTB formula re-approval).
- applicability: company profile vs thresholds ($10M tiering, product types).
- verdict: rows {product, trigger, required_change, real_deadline,
  confidence, citations[]}. Distinguishes binding rule vs agency request
  (HHS "sooner" ask). Unknown → say so + escalate; never guess.
- hitl_gate: two distinct triggers, two distinct statuses, because they need
  different things from different humans. An INSUFFICIENT PROFILE (no product
  or claim to apply a rule to) ends `needs_input` and asks for
  `company_profile`. CONFIDENCE below `CONFIDENCE_HITL_THRESHOLD` ends
  `pending_review` and asks for a `reviewer_decision`. Either way: checkpoint
  to DynamoDB, write a review item, END. The resume endpoint continues from
  the checkpoint. This spec said only `pending_review` until 2026-08-15,
  before anyone had noticed there were two triggers; the implementation drew
  the distinction first and the spec follows it.

## State (src/graph/state.py)
TypedDict: query, company_profile, retrieved[], timeline_facts[],
crossrefs[], verdict_rows[], confidence, citations[], status.

## Model policy (src/shared/config.py)
Sonnet-class for retrieval-adjacent nodes; strongest model for verdict
synthesis only. Model ids are config values, never literals in node code.
Bedrock prompt caching for the static system preamble.

## Done when
One full golden-set run, agent mode, on the S3 Vectors tier — `make evals`
against the deployed API, or `make agent-evals` against the loopback shim
while SPEC/04's endpoint is unimplemented — with both of:

- **Overall:** ≥ 80% of questions passing, read from the run's closing
  `N/M passed (P%)` line. The runner exits 0 only at 100%, so exit status is
  not this bar; the printed line is.
- **Traps:** every question tagged `trap` passing, read from the per-question
  results of that same run. Do not run `--subset trap` separately as the
  evidence: it is a second set of live model calls and can disagree with the
  run it is meant to describe. Membership of the trap set is whatever
  `python evals/run_evals.py --subset trap` selects. **The tag governs; no
  list of IDs in this spec overrides it.**

*Trap-tag census, 2026-08-16: **eight** questions (q01–q04, q07, q11, q19, q20).*
A dated observation, not the criterion. If a run selects a different number,
this line is stale and the tag is still right. But widening the tag widens this
exit criterion, so any change to the tag is a PM-seat decision and must arrive
as a diff to this line.

<sup>Was five (q01–q04, q07) on 2026-08-15. Merging `q11`–`q20` tagged three of
the new questions `trap`, which took the gate from five to eight — the exact
silent widening this line exists to prevent, arriving as a diff because the
line asked it to. The criterion is stricter than it was and the agent meets it:
8/8 at `e26d8ef`.</sup>

**Known limitation of this gate, 2026-08-16.** The naive control passes four of
the eight — q02, q04, q11, q20 — on its own recorded answers
(`make replay-history`). ADR-0002 makes that control the thing every progress
claim is measured against, so on those four the trap is not currently
discriminating between naive RAG and the agent graph. The gate is still worth
having: the agent passes all eight and the control fails four, including every
one that turns on date attribution. But "traps 8/8" should be read as *"the
agent passes all eight, and the control passes four of them"*, and the questions
themselves want an SME-seat re-read. Recorded here rather than left to be
discovered, because a delta over a control is only as strong as the control's
inability to pass.

HITL demonstrated on the golden question tagged `hitl` (q10): an underspecified
company profile ends `needs_input` with a checkpoint written, and
`POST /resume/{id}` with a sufficient profile continues to a cited answer. The
first half is scored by the golden set; the second is **not** — the runner only
ever POSTs `/query` — so resume is demonstrated by hand and its transcript
recorded in the milestone pack. `pending_review` is the *other* trigger
(confidence below `CONFIDENCE_HITL_THRESHOLD`) and is not what this criterion
observes.

## Out of scope
- Resume as an automated check. `run_evals.py` only POSTs `/query`; automating
  the resume half is a SPEC/04 API-surface decision.
- The AOSS tier. Both tiers must pass evals (SPEC/02); this milestone's exit
  criterion is measured on S3 Vectors only.
- Latency and cost targets for the graph. Unmeasured here.
- Expansion of the golden set (`evals/proposed/`). Unruled at time of writing.
  This criterion is written against the set as tagged today.

## Open — PM seat, not resolved by this spec
`≥ 80%` is a bar whose meaning is a function of a number we change for
unrelated reasons. At ten questions it means "ship with at most two known-wrong
answers"; at twenty it means four. We grow the golden set to increase coverage,
so under a percentage every question added to catch a failure also buys
permission to have one — and nobody decided that this product's tolerance for
wrong regulatory answers doubles. The recommendation on file is to replace it
with an absolute count ("at most 2 failures overall, zero on trap-tagged
questions"), which holds today's tolerance exactly at ten and is stricter than
16/20 at twenty — correct, because the proposed additions are harder. It wants
an ADR and its own diff, landed before `evals/proposed/` merges. Related: the
runner's exit status should encode whatever bar is chosen, so "did we pass?" is
a command rather than a reader doing arithmetic off a printed line — that
matters once `.github/workflows/evals.yml` scores this set post-M04.
