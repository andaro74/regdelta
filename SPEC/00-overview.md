# SPEC/00 — Overview

## What RegDelta is
An agentic assistant for a fictional food company ("Nordvale Foods", ~$400M
annual sales) that watches FDA regulatory changes and answers:
**"What changed, does it apply to us, and what is the real deadline?"**
Every claim cites its source (Federal Register doc number, CFR section).
Low-confidence verdicts pause for human review.

## Demo scenarios (both real, public-domain rules)
1. **"Healthy" claim redefinition** — final rule Dec 19 2024; effective date
   delayed to Apr 28 2025; **compliance date Feb 25 2028 unchanged**. Trap:
   naive RAG reads "delayed" and moves the deadline. Size-tiered compliance
   ($10M threshold).
2. **FD&C Red No. 3 revocation** — order published Jan 16 2025 (90 FR 4628);
   food use **effective** Jan 15 2027; ingested drugs **effective** Jan 18
   2028 (two dates in one order). **Administratively stayed** under
   21 U.S.C. 371(e)(2) from Feb 18 2025 by the filing of objections; stay
   **lifted Aug 5 2026 with both dates confirmed, not moved** (91 FR 50475).
   Cascades: TTB formula re-approval for the cocktail mixer;
   existing-inventory nuance; HHS "phase out sooner" is a request, not a rule.

   **The stay is the strongest artifact in the corpus and the poller found it
   unattended.** Between Feb 2025 and Aug 2026 the honest answer to "when must
   we comply?" was neither "January 15 2027" nor "the deadline moved" — it was
   *"January 15 2027, but the provision is stayed and not currently
   operative."* A system that answers a bare date is wrong in a way no
   date-comparison test detects. There is also **no Federal Register document
   for the stay itself** — it arose by operation of law and is knowable only
   retrospectively from the document that lifts it, so between an objection
   filing and the lift the corpus cannot know a stay is in force. See ADR-0007.

   **Effective, not compliance — and the distinction is the point.** Unlike
   scenario 1, this order states no compliance date at all; it repeals the
   listing, and after the effective date the food is adulterated. So the
   operative deadline for a manufacturer must be *derived* from the repeal,
   not read off a compliance-date field. The corpus therefore stores
   `compliance_date = null` for this document (ADR-0006: a document carries
   only the dates it establishes), and a compliance-date range filter
   correctly returns nothing for Red No. 3. Producing the real deadline is
   the timeline agent's job at M03. A demo that called Jan 15 2027 a
   "compliance date" would be committing the exact conflation scenario 1
   exists to expose.

## System shape
- **Persistent core stack**: S3 corpus (source of truth, chunks stored WITH
  embeddings) · S3 Vectors index (always-on retrieval tier) · DynamoDB
  (registry + amendment graph, LangGraph checkpoints, cache) · daily
  EventBridge ingestion · API GW + Lambda (LangGraph) · nightly evals.
- **Ephemeral search stack**: AOSS vector search collection (dev mode,
  ~$0.24/hr), hydrated from S3 on deploy, destroyed after each session.
- **Routing seam**: SSM `/regdelta/search/endpoint` present → AOSS hybrid;
  absent → S3 Vectors. Same golden set must pass on both paths.

## Milestones
01 ingestion → 02 knowledge base (both tiers) → 03 agents →
04 API + demo UI → 05 deploy + lifecycle → 06 load test & observability.
