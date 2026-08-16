---
name: regulatory-domain
description: FDA/Federal Register domain semantics for RegDelta — date types, amendatory instructions, thresholds, citation formats. Consult when working on ingestion parsing, the timeline agent, or verdict logic.
---
# Regulatory Domain Cheat Sheet

## The three dates (never conflate)
- publication_date: when the doc appears in the Federal Register.
- effective_date: when the rule text legally changes / may be used.
- compliance_date: when regulated parties MUST conform. Often years later.
A delay of the effective date does NOT move the compliance date unless the
notice says so explicitly. (Demo trap: "healthy" delay to 2025-04-28 left
compliance at 2028-02-25.)

**Many documents set no compliance date at all.** A repeal or delisting states
only an effective date: after it, the listing is gone and the product is
adulterated. The operative deadline for a regulated party is then *derived*
from the repeal — it is NOT a compliance_date to be stored. Per ADR-0006 a
document carries only the dates it establishes, so `compliance_date` stays
null and a compliance-date range filter returns nothing for such a document.
Deriving and explaining the real deadline is the timeline agent's job
(SPEC/03), and the verdict must say which kind of date it is reasoning from.
Recording a repeal's effective date as a compliance date would commit exactly
the conflation this product exists to expose.

## Amendatory instructions
FR rules modify the CFR via imperative edits: "In § 101.65, revise
paragraph (d)(2)…", actions ∈ {add, revise, remove, redesignate}. Parse to
{action, target_citation, [new_text]}. The eCFR shows the result; the FR
doc is the authoritative delta.

## Supersession scoping
An amendment can supersede another document ENTIRELY or a single aspect
(e.g., only its effective date). Edges are predicate-typed and scoped
(ADR-0007); timeline answers must respect both.

| scope | predicate | meaning |
|-------|-----------|---------|
| effective_date | SUPERSEDES | states a NEW effective date for the prior doc |
| compliance_date | SUPERSEDES | states a NEW compliance date for the prior doc |
| full | SUPERSEDES | wholly replaces / repeals / withdraws the prior doc |
| stay | STAYS | suspends the prior doc's effect; no new dates |
| stay_lifted | LIFTS_STAY | ends a suspension; prior doc operative again |
| dates_confirmed | CONFIRMS | prior doc's dates stand UNCHANGED; no new dates |

Decision rule: `effective_date`/`compliance_date` only if a NEW date string
appears. A document repeating dates already set is `dates_confirmed`, not a
date change — ask whether you could fill in `new_date` from this document.
`stay_lifted` and `dates_confirmed` are not mutually exclusive; emit both.

**A stay or confirmation is never SUPERSEDES.** Supersession answers which
text governs; a stay changes no text and a confirmation changes nothing.
Recording either as SUPERSEDES makes "most recent edge wins" conclude the
newer document displaced the older, when the older still governs and is the
one to cite.

## Administrative stays (21 U.S.C. 371(e)(2))
Filing objections to an FDA order automatically stays the effectiveness of the
provisions objected to, until final agency action. Semantics:

- **Suspended, not tolled.** The statute has no day-for-day extension. Dates do
  not move. The Red No. 3 stay ran ~17.5 months and 2027-01-15 stayed
  2027-01-15.
- **Not merely unenforceable.** During the stay the provision has no legal
  effect at all — Red No. 3 remained a lawfully listed food color additive.
- **The correct answer during a stay is tri-state**, and neither "the deadline
  moved" nor "there is no deadline": *"the stated date is X, but the provision
  is administratively stayed as of D pending FDA action on objections — plan to
  X, treat it as unconfirmed."*

Stays are stored as a first-class interval on the STAYED document
(`STAY_PERIOD#<start>` with start/end/authority/dates_changed), not as an edge
pair. **A stay is often never separately published** — it arises by operation
of law and is documented only retrospectively by the document that lifts it, so
there may be no source document for a STAYS edge to come from. A corollary
worth surfacing in verdicts: between an objection filing and the lift
publication, the corpus cannot know a stay is in force.

Worked example: Red No. 3 order 2025-00830 (90 FR 4628) → stayed 2025-02-18 →
2026-15920 (91 FR 50475) lifts the stay 2026-08-05 and confirms both dates.

## Applicability thresholds
Common pattern: $10M annual food sales splits compliance timelines
(bigger = sooner). Always resolve deadlines against company profile.

**Verify the tier per rule — never assume it.** That threshold is real in FDA
labeling generally (the Nutrition Facts rule), but it does **not** apply to
the "healthy" rule: FDA considered a longer small-business period and declined
it (2024-29957#0303), so 2028-02-25 is uniform. Zero mentions of any dollar
threshold exist across the whole corpus. Asserting a size tier that the rule
does not contain invents an exemption — the mirror of inventing a deadline,
and the same class of error as ADR-0006. If a rule sets no tier, applicability
turns on conduct (here: whether the product bears a "healthy" claim).

## Binding vs non-binding
Final rule / order = binding. Guidance, press releases, "FDA encourages…"
= requests. Verdicts must label which is which.

## Citation formats to emit
CFR: "21 CFR 101.65(d)(2)". Federal Register: "89 FR 106064" or the doc
number "2024-29957". Every verdict row carries ≥1 of each when applicable.

## Known demo facts (ground truth for evals)
- Healthy rule: pub 2024-12-27, effective delayed to 2025-04-28,
  compliance 2028-02-25 (unchanged by the delay).
- Red No. 3: order 2025-00830 / 90 FR 4628, **published 2025-01-16**
  (FDA announced it on the 15th — the announcement date is NOT the
  publication date and appears nowhere in the document; do not cite it);
  food use **effective** 2027-01-15; ingested drugs **effective** 2028-01-18.
  This order sets **no compliance date** — see "The three dates" above.
  Inventory manufactured before the effective date is not adulterated;
  TTB formula re-approval required if an approved alcohol formula changes.
  Stayed 2025-02-18 → 2026-08-05, dates confirmed unchanged (91 FR 50475).
