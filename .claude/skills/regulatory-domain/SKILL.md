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

## Amendatory instructions
FR rules modify the CFR via imperative edits: "In § 101.65, revise
paragraph (d)(2)…", actions ∈ {add, revise, remove, redesignate}. Parse to
{action, target_citation, [new_text]}. The eCFR shows the result; the FR
doc is the authoritative delta.

## Supersession scoping
An amendment can supersede another document ENTIRELY or a single aspect
(e.g., only its effective date). Model edges as
DOC#a SUPERSEDES DOC#b {scope}. Timeline answers must respect scope.

## Applicability thresholds
Common pattern: $10M annual food sales splits compliance timelines
(bigger = sooner). Always resolve deadlines against company profile.

## Binding vs non-binding
Final rule / order = binding. Guidance, press releases, "FDA encourages…"
= requests. Verdicts must label which is which.

## Citation formats to emit
CFR: "21 CFR 101.65(d)(2)". Federal Register: "89 FR 106064" or the doc
number "2024-29957". Every verdict row carries ≥1 of each when applicable.

## Known demo facts (ground truth for evals)
- Healthy rule: pub 2024-12-27, effective delayed to 2025-04-28,
  compliance 2028-02-25 (unchanged by the delay).
- Red No. 3: order 2025-01-15; food compliance 2027-01-15; ingested drugs
  2028-01-18; pre-compliance-date manufactured inventory not adulterated;
  TTB formula re-approval required if an approved alcohol formula changes.
