# ADR-0002: Ship a naive-RAG baseline (M00b) before the agent graph

- Status: accepted
- Date: (project start)
- Milestone: M00b

## Context
"Agentic beats naive RAG" is the project's thesis. A thesis needs a control.

## Decision
M00b implements the simplest possible pipeline: embed query → top-k vector
search → single Claude call. Run the full golden set, COMMIT THE FAILURES
(expected: traps q01-q04 fail). Every later milestone's scorecard is diffed
against this baseline.

## Consequences
+ Progression is quantified (e.g., 40% → 80% → 100% on traps).
+ The demo has a before/after story with receipts.
- One extra half-day milestone.
