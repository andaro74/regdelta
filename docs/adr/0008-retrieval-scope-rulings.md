# ADR-0008: Two retrieval-scope rulings (probes r01 and r04)

- Status: accepted
- Date: 2026-08-08
- Milestone: M02
- Basis: SME-seat ruling; primary sources cited inline; no second approver
  exists (ADR-0005)
- Relates to: SPEC/02 "Ground truth ownership" carve-outs 1 and 2

## Context
`evals/retrieval_truth.json` is engineering-authored, and SPEC/02 carves out
two classes of entry where the choice is a regulatory judgment rather than a
corpus fact: q01's expected set (carve-out 1) and any entry encoding a scope,
date, or applicability distinction (carve-out 2). Probes **r01** and **r04**
are one of each. Both shipped marked `SME-SEAT RULING NEEDED` and blocked
nothing mechanically, which is precisely why they needed to be settled before
M02 closes rather than after.

ADR-0005 settled what "settled" means here: there is one human, so no second
signature exists to obtain. A ruling is sound when it cites primary sources a
reader can check without trusting the author. Both rulings below are recorded
with the source text inline. Neither is a corpus fact; both are falsifiable
against the cited documents.

## Ruling 1 (r01) — the expected set is BOTH chunks, not the delay notice alone

**Probe.** *"The effective date of the new 'healthy' claim rule was delayed.
Did the compliance deadline change?"*
Expected: `2024-29957#0000` **and** `2025-03118#0003`.

**Sources.**
- 89 FR 106064 (doc 2024-29957), DATES: *"The compliance date of this final
  rule is February 25, 2028."*
- 90 FR 10592 (doc 2025-03118), DATES: the effective date *"is delayed until
  April 28, 2025"*; and separately, *"the compliance date remains unchanged at
  this time."*

**Ruling.** Two chunks, both required.

The question is a two-part conjunction — *what is the deadline* and *did the
delay move it* — and the two halves live in different documents. The delay
notice alone answers only the second. A system that returns only 2025-03118
has retrieved a document that says a date did not change without ever
retrieving the date, and the only way to produce "February 25, 2028" from that
context is to generate it. That is the failure mode this product exists to
prevent, and it would be invisible at M02 because recall would score 1.0 on a
one-chunk expected set.

**The counter-argument, and why it loses.** One could argue the notice's
"remains unchanged" is sufficient because the answer to *"did the deadline
change?"* is literally "no". True for that question in isolation — but q01 is
scored on prose at M04 and its `must_contain` includes the date. Setting the
retrieval bar below what the answer layer needs would let M02 go green and q01
fail at M04, which is the exact ordering failure SPEC/02's probe pair was
written to prevent.

**Scope of this ruling.** It fixes the expected set, not the ranking. Whether
both chunks arrive at ranks 1–2 or 6–7 is a retrieval-quality question; the
ruling is only that both must arrive inside top-8.

## Ruling 2 (r04) — the § 74.1303 drugs regtext is excluded from a food query

**Probe.** *"We make a strawberry frosting containing FD&C Red No. 3. When
must we stop using it?"*
`must_not_return`: `2025-00830#0027`, `2025-00830#0028`.

**Sources.**
- 21 CFR 74.303 — *"FD&C Red No. 3"*, listed under Subpart A, **Foods**.
- 21 CFR 74.1303 — the same colour listed under Subpart B, **Drugs**. The
  part-74 subpart structure is the regulatory scope boundary itself, not a
  filing convenience.
- 90 FR 4628 (doc 2025-00830), DATES: *"effective January 15, 2027, except for
  amendatory instruction 4, which is effective January 18, 2028."* Instruction
  4 is the one that removes § 74.1303.

**Ruling.** Exclude. A frosting is a food; § 74.1303 governs ingested drugs and
sets a deadline thirteen months later. Returning it for a food query puts two
dates in the context with nothing in the retrieved text marking which one binds
the asker, and the later, wronger date is the one a summariser is most likely
to surface as "the deadline". Excluding a chunk that cannot lawfully apply to
the asker is precision, not recall loss.

**The counter-argument, and why it loses on this probe specifically.** A
manufacturer may well make both foods and drugs, and for such a company the
2028 date is real. That is an *applicability* question — it turns on the
asker's product profile, which SPEC/03's verdict layer resolves against the
company profile. It is not a retrieval question, and this probe's query states
its product: a strawberry frosting. If a later milestone adds a probe whose
query is product-ambiguous ("we make consumer products containing Red No. 3"),
the correct expected set for *that* probe includes both, and this ruling does
not bar it.

**What this ruling does NOT cover, and must not be read as covering.** Both
dates live in a single chunk — `2025-00830#0000`, the DATES paragraph, which is
r04's *expected* chunk. Retrieval therefore cannot separate them, and this
ruling does not claim it does. Excluding #0027/#0028 removes the drugs
*regtext*, not the drugs *date*. Disambiguating the two dates inside #0000 is
the answer layer's job at M04, guarded there by q02's `must_not_contain`.
A reader who takes r04 passing as evidence that the food/drug split is handled
end-to-end has over-read it.

## Consequences
+ Both carve-outs are closed with citable bases, so M02 can be evaluated
  against a probe set with no open rulings in it.
- Ruling 2 is deliberately narrow and will need revisiting the moment a
  multi-product asker appears in the golden set. Recorded here rather than
  left as a surprise.
- Neither ruling was reviewed by a second person. Per ADR-0005 the mitigation
  is the inline sources above, not a signature: if either ruling is wrong, the
  quoted text is where it is wrong, and a reader can find that without
  trusting this document.
