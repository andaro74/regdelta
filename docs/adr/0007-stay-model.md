# ADR-0007: Stays are intervals, not supersession

- Status: accepted
- Date: 2026-08-08
- Milestone: M02 (pre-work)
- Basis: SME-seat ruling; primary sources cited inline; no second approver exists (ADR-0005). Statutory text (21 U.S.C. 371(e)(2)) and both FR
  documents verified against federalregister.gov.
- Amends: SPEC/01 supersession scoping

## Context
On 2026-08-05 the daily poller ingested `2026-15920` (91 FR 50475) unattended.
Its DATES section:

> This order that published ... January 16, 2025 (90 FR 4628) with effective
> dates of January 15, 2027, and January 18, 2028, **was administratively
> stayed by the filing of objections under section 701(e)(2)** of the FD&C Act
> (21 U.S.C. 371(e)(2)) as of February 18, 2025. FDA **lifts the administrative
> stay** as of August 5, 2026. The effective dates ... **are confirmed**.

The pipeline recorded `DOC#2026-15920 SUPERSEDES#2025-00830 scope=effective_date`
— because `_SCOPES` was `{effective_date, compliance_date, full}` and nothing
else fit. But this document **changes no date**. It confirms them. Per CLAUDE.md
timeline answers come from this graph, so SPEC/03's timeline agent would read
that edge and conclude the dates moved. It is the M01 thesis-row inverted.

Three facts settle the design, all verified against the Federal Register:

1. **A 701(e)(2) stay suspends, it does not toll.** The statute stays "the
   effectiveness of those provisions of the order to which the objections are
   made" until final action. There is no day-for-day extension. The stay ran
   ~17.5 months and 2027-01-15 remained 2027-01-15.
2. **The stay was not partial.** Both the food repeal (21 CFR 74.303) and the
   ingested-drug repeal (21 CFR 74.1303) were suspended.
3. **No Federal Register document exists for the stay itself.** It arose by
   operation of law on 2025-02-18 and is documented only retrospectively, in
   the document that lifts it.

## Decision

**1. Scope vocabulary.** `_SCOPES` becomes:

| value | semantics |
|-------|-----------|
| `effective_date` | cites a prior document and states a NEW effective date for it |
| `compliance_date` | cites a prior document and states a NEW compliance date for it |
| `stay` | suspends the prior document's legal effect pending further agency action; states no new dates |
| `stay_lifted` | ends a previously imposed suspension; the prior document returns to operative status |
| `dates_confirmed` | states the prior document's existing dates stand unchanged; states no new dates |
| `full` | wholly replaces, repeals or withdraws the prior document |

Disambiguation rule, written so extraction can apply it: use `effective_date` /
`compliance_date` **only if a new date string appears**. If the document repeats
dates the prior document already set, that is `dates_confirmed`. Test — could
you fill in `new_date` from this document? If not, it is not a date change.
`stay_lifted` and `dates_confirmed` are not mutually exclusive; emit one edge
per scope.

**2. Stay and lift do not belong on a SUPERSEDES edge.** Supersession answers
*which text governs*. A stay changes no text and a confirmation changes nothing
at all, yet any consumer applying the natural rule "the most recent SUPERSEDES
edge wins" would conclude 2026-15920 displaced 2025-00830 — when 2025-00830 is
still the governing order and the document to cite for 2027-01-15. Edges become
predicate-typed: `SUPERSEDES#`, `STAYS#`, `LIFTS_STAY#`, `CONFIRMS#`.

**3. The stay is a first-class interval, not an edge pair.** A `STAY_PERIOD`
item is written on the *stayed* document by the document that lifts it:

```
pk=DOC#2025-00830  sk=STAY_PERIOD#2025-02-18
  start, end, authority="21 U.S.C. 371(e)(2)",
  scope_sections, source_doc, dates_changed=false
```

Two reasons, and the first is decisive:
- **An edge pair cannot represent this case.** A `STAYS` edge needs a source
  document and there is none — the stay was never separately published. A design
  requiring stay-edge plus lift-edge simply cannot ingest the real event.
- **Point-in-time queries need the interval.** "What was the deadline on
  2025-06-01?" is a containment test against a span, not an inference over two
  endpoints.

**4. The edge sort key must carry the predicate and scope.** `SUPERSEDES#<doc>`
alone collides: only one edge could exist per (citing, target) pair, so a
document doing two things to the same target lost one to last-write-wins,
silently. This had to be fixed before any multi-scope vocabulary could land.

**5. An unknown scope raises.** It previously degraded to `full` — wholesale
replacement, the most destructive available reading. A prompt/enum skew or a
near-miss like `"stay lifted"` would have recorded that the August 2026 notice
*wholly replaced* the January 2025 order. Fail-loud matches the policy already
applied to `doc_type` and to dates.

## Consequences
+ The graph can express what actually happened, including the state the product
  exists to get right: on 2025-06-01 the honest answer was "January 15, 2027,
  but stayed and not currently operative" — neither "the deadline moved" nor
  "there is no deadline".
+ These decisions land before `src/graph/nodes.py` is written, which is the
  cheapest possible moment.
- Re-ingestion of `2026-15920` is required.
- **The graph is necessarily wrong about the present between an objection
  filing and the lift publication**, because the interval is only knowable
  retrospectively. This is inherent, not a defect to fix: SPEC/03's verdict node
  must surface the possibility of an unpublished stay rather than hide it.

## Golden set
Unaffected; q02 and q04 remain correct and no edit is proposed. Two items are
flagged for the SME to initiate separately:
- No question exercises stay/lift or point-in-time semantics.
- q08 has a pre-existing ambiguity unrelated to this event: it accepts
  "January 15, 2025" for a publication date, but 90 FR 4628 published
  2025-01-16; 2025-01-15 is the order date.

**Live regression risk to watch:** 2026-15920 is now the freshest, most
on-topic document for Red No. 3 queries, and its own DATES sentence is
misdrafted — it attaches *both* dates to amendatory instruction 4, where the
underlying order attaches only 2028-01-18. q02's
`must_not_contain: ["January 18, 2028 for food"]` is materially more likely to
trip than it was before this document existed.
