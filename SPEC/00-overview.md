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
2. **FD&C Red No. 3 revocation** — order Jan 15 2025; food compliance
   Jan 15 2027; drugs Jan 18 2028 (two dates in one order). Cascades:
   TTB formula re-approval for the cocktail mixer; existing-inventory
   nuance; HHS "phase out sooner" is a request, not a rule.

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
