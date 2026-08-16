# ADR-0011: The corpus boundary is a CFR part, not an agency

- Status: accepted
- Date: 2026-08-15
- Milestone: M03 (found while building it; the defect is M01's)
- Amends: SPEC/01 ingestion scope

## Context
The poller asked the Federal Register for "agency = FDA, type in
RULE/PRORULE/NOTICE" and ingested everything that came back. **FDA is one
agency publishing for food, drugs, devices, veterinary medicine and tobacco**,
so that is a publisher filter, not a subject filter.

Left running on its daily schedule it took the corpus from **4 FR documents to
49** between 2026-07-30 and 2026-08-15 — 15 of them during a single working
session. Among them: a digital breast tomosynthesis reclassification, three
more device reclassifications, and a run of drug and device user-fee notices,
all competing for the eight retrieval slots every answer gets.

Two things this also broke quietly. M02's retrieval probe set carries a
`corpus_snapshot` of 2026-08-08 and was measured against a materially smaller
index than the one now serving. And the golden-set scorecards had no record of
which corpus answered them at all, so two runs against different corpora were
indistinguishable in `evals/history/`.

## Decision
**Filter on the document's own `cfr_references`: keep a document only if it
cites 21 CFR part ≤ 199.** Title 21 splits cleanly at 200 — parts 70–82 colour
additives, 100–169 labelling and standards, 170–199 food additives; 200+ are
drugs, 500s veterinary, 800s devices, 1100+ tobacco. The field is requested in
the poll query, so an out-of-scope document is never fetched, chunked, embedded
or paid for.

Documents citing **no** CFR part are excluded by default
(`POLL_REQUIRE_CFR=1`): a document that amends no regulation cannot be the
subject of "what changed, does it apply to us, and what's the real deadline".

## Alternatives considered
- **Filter on FR `topics`. Tried first and it is wrong.** The Red No. 3 order's
  topics are `['Color additives', 'Cosmetics', 'Drugs']` — no food topic at
  all. A topic allowlist would drop the document half the golden set turns on.
  A test pins that fact so the idea is not quietly revisited.
- **Filter on the title.** The 38 no-CFR-reference documents carry no topics
  either (all 26 sampled were empty), so title text is the only remaining
  signal — which would mean separating "Food Safety Modernization Act
  Third-Party Certification" from "Prescription Drug User Fee Rates" by string
  matching. That is not a scope rule, it is a guess with a regex.
- **Keep everything and let retrieval sort it out.** Rejected on measurement,
  not taste: every irrelevant document competes for a fixed eight-slot page,
  and the probe set that certified retrieval was measured before any of them
  existed.
- **Keep the no-CFR-reference documents.** This is the closest call, and it is
  why the behaviour is a flag rather than an assumption. Some of them are
  genuinely food-adjacent (FSMA notices, a BHT request for information). They
  set no CFR deadline, so they cannot answer this product's question — but that
  is a scope judgement, and `POLL_REQUIRE_CFR=0` restores the old behaviour.

## Consequences
**Easier.** The corpus stays about food labelling without anyone watching it.
Retrieval competes against relevant distractors instead of arbitrary ones.

**Harder / riskier.** The filter reads one API field, so if the Federal
Register renames or drops `cfr_references`, every record looks out of scope,
everything is skipped, and the handler returns `enqueued: 0` — which looks
exactly like a quiet week. **This ships with its own alarm**: the poller raises
when the key is ABSENT from the response, rather than when skips are merely
high, because a week of device and drug notices legitimately skips everything
and raising on that would be a daily false alarm — the failure mode the
existing total-rejection alarm's own comment warns about.

Out-of-scope skips are reported in the handler result and held in a list
separate from `_rejected`, because a rejection means the upstream shape broke
and a skip means the filter worked, and merging them makes one look like the
other.

**A consequence for existing evidence, not just future ingestion.** M02's
retrieval numbers were measured against a 4-document corpus and the probe set
still says so. This ADR does not repair that; it makes the drift visible going
forward, and re-verifying the probe set against the current corpus is owed
work.

**Revisit when** the product's scope changes (dietary supplements and animal
food both live above part 500 and would need the bound moved), or if the
no-CFR-reference exclusion turns out to drop something a user asks about.

## Evidence
Against the 49 documents in the corpus on 2026-08-15, the rule separates them
exactly:

| kept (21 CFR ≤ 199) | dropped (≥ 200) |
|---|---|
| 101 healthy rule + its delay notice | 892 digital breast tomosynthesis |
| 74 Red No. 3 order + the stay lift | 892 radiology devices |
| 170/570 GRAS proposed rule | 864 hematology devices |
| 117 ready-to-eat food guide | 876 gastro-urology devices |
| | 870/876/878 device accessories |

Six kept, five dropped, and the six are precisely the documents the golden set
and the retrieval probe set depend on. The remaining 38 cite no CFR part.
