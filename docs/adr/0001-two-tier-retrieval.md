# ADR-0001: Two-tier retrieval (S3 Vectors always-on, AOSS ephemeral)

- Status: accepted
- Date: (project start)
- Milestone: M02

## Context
The demo idles most of the time; OpenSearch bills continuously. But the
production-standard hybrid (BM25+kNN) story matters to the audience.

## Decision
S3 Vectors is the always-on tier (pay-per-request, <$2/mo idle). AOSS
vector search collection (dev mode, ~$0.24/hr) is an ephemeral hot tier,
hydrated from S3 on `make up`, destroyed after each session. Routing seam:
SSM /regdelta/search/endpoint. Both tiers must pass the same golden set.

## Alternatives considered
- Always-on AOSS — ~$175+/mo idle for a demo.
- S3 Vectors only — loses BM25/hybrid and the enterprise scale story.
- Managed OpenSearch domain up/down — 20-40 min spin-up, too slow per session.

## Consequences
+ Idle cost ≈ zero; live tier-switch is itself a demo moment.
- Two retrieval code paths to keep at eval parity (enforced by CI matrix).

## Evidence
Recorded per milestone in milestones/M02/scorecard (eval pass rate per tier,
retrieval p50 per tier).
