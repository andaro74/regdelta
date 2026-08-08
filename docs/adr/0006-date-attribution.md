# ADR-0006: A document carries only the dates it establishes

- Status: accepted
- Date: 2026-08-08
- Milestone: M02 (pre-work)
- Approved by: human SME sign-off, on sme-eval-triage ruling
- Governs: SPEC/02 retrieval-filter semantics

## Context
The corpus contained a fabricated compliance date. `DOC#2025-03118` — the
"healthy" effective-date delay notice (90 FR 10592) — carried:

```json
"compliance_dates": [{"date": "2028-01-01",
  "applies_to": "...compliance date remains unchanged from the original
                 final rule (89 FR 106064)"}]
```

The notice's only reference to 2028 is preamble prose: *"the compliance date
in the final rule is not until 2028."* No month or day appears anywhere in the
document. The extractor reasoned correctly — its own `applies_to` says the date
is unchanged — and then manufactured day-precision the source never contained.
January 1 is the classic default-fill artifact of a bare year.

The true date is **2028-02-25**, verified verbatim against 89 FR 106064's DATES
section. The stored value was **55 days early**, and it errs in the direction
that manufactures a false deadline: a verdict built on it tells a client to
relabel two months before the law requires it. This is the product's own thesis
failure, committed by our own pipeline, on the single most important fact in
demo scenario 1.

It was found by pulling the live corpus to author `evals/retrieval_truth.json`,
not by any test. Nothing in the M01 hardening could have caught it: `2028-01-01`
is well-formed, real, and inside the plausibility window. **Validation catches
malformed, not fabricated.**

## Decision

**1. A document's date fields carry only the dates that document establishes.**
`2025-03118`'s DATES section establishes exactly one thing — a delayed
effective date of 2025-04-28. Its compliance_dates is therefore `[]`, not
`2028-01-01` and not `2028-02-25`. The 2028 date belongs to the rule that set
it and is reached from the notice by traversing the amendment graph.

**2. Never complete a partial date.** A bare year, a bare month, or a relative
period ("within two years", "180 days after publication") yields no entry. An
omitted date is recoverable; an invented one is not.

**3. Enforced deterministically, not only by prompt.** `_normalize` grounds
every extracted date against the source digest: if the document does not
contain that date's day-precision in a recognizable form, the message fails.
Prompts are probabilistic and this field carries liability — a prompt-only fix
leaves the failure mode reachable on any model swap.

### Consequence for SPEC/02's filter contract
A `compliance_date` range filter answers *"which documents impose a conformance
deadline in this window."* The delay notice imposes none. A range covering 2028
must return the final rule's chunks and **not** the notice's.

This is not a recall loss. A user asking "what is due in 2028" still gets
2024-29957, which carries 2028-02-25. Under the rejected alternative they get
two hits for one obligation — and the second one specifically asserts that the
*delay notice* is what makes 2028 operative, which is the effective-vs-
compliance conflation q01 exists to trap. The filter would manufacture the
exact error the trap tests for.

## Alternatives considered
- **Inherit the underlying rule's date onto the notice (2028-02-25).** Simpler
  for recall, and the value would at least be true. Rejected: it duplicates a
  liability-bearing date across two authoritative records, and CLAUDE.md
  designates the DynamoDB graph authoritative for timeline answers, so whichever
  copy is not updated when FDA extends the date becomes silently wrong.
  Single-writer is the only safe design here. It also contradicts SPEC/01, which
  already scopes this document's SUPERSEDES edge to `effective_date` only —
  stamping a compliance date on it denies that scoping in the same breath.
- **Prompt fix only.** Cheapest, and it does address the observed case.
  Rejected as insufficient alone; kept as one of two layers.

## Consequences
+ The corpus stops asserting a deadline no document sets.
+ The failure mode is caught deterministically rather than by model compliance.
- Re-ingestion is required for `2025-03118`; its `META` idempotency marker must
  be deleted so the poller redoes it in full.
- The "compliance date is unchanged" narrative in `2025-03118#0005` is no
  longer reachable *via a compliance_date filter*. It remains reachable by
  BM25/semantic retrieval, which is how q01 should assemble it. **If an answer
  path is ever found to depend on the filter to surface that prose, the fix
  belongs in amendment-graph traversal — not in denormalizing a date back onto
  a document that never set one.**

## Residual risk, recorded deliberately
Three limits, all found by role-gate review of the implementation. None is
fixed here; each is stated so nobody reads the closed defect as broader
coverage than it is.

**1. Decision 1 (attribution) is enforced only by prompt.** The grounding check
enforces decision 2 — a date must appear in the source. It cannot tell whose
date it is. A notice that quotes the underlying date verbatim ("the compliance
date of February 25, 2028 remains unchanged") — a common FR construction —
grounds cleanly, and the borrowed-date failure returns with nothing
deterministic behind it. The observed defect is closed on both layers only
because 2028-01-01 was *also* ungrounded.

**2. Grounding binds a date to the DOCUMENT, not to a field.** Any full date in
the 12000-char digest will ground any date field. That is what makes a forged
`stay_start` cheap, and it is why the stay write needs its own corroboration
gate (ADR-0007).

**3. The digest is what the model saw, so grounding cannot reject a date the
model was shown.** `extract()` passes one digest object to both the prompt and
`_normalize`, which is load-bearing: re-deriving full text for grounding would
reintroduce the entire false-negative class. Note separately that
`_document_digest` includes preamble blocks but never `regtext_sections`, so
GPOTABLE content — where tiered compliance dates typically live — is outside
extraction altogether. Not reached on the current corpus; recorded because
SPEC/02's `compliance_date` filter may be expected to cover it.

## Golden set
Unaffected, and no edit is proposed. q01 already cites the final rule rather
than the notice, so it was authored consistent with this decision; approving it
ratifies q01 rather than disturbing it.

**The load-bearing warning:** this defect can make q01 *fail at runtime while
q01 is entirely correct* — if the answer path reads the notice's META it emits
"January 1, 2028" and misses `must_contain: "February 25, 2028"`. That is a
model/system regression, and the fix is in ingestion. Anyone relaxing
`must_contain` to `"2028"` to make it pass would be deleting this product's
only regression detector for date fabrication.
