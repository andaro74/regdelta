# SPEC/00b — M00b: Naive-RAG Baseline (the control)

## Goal
The simplest thing that answers questions, so later milestones have a
measured starting point. See ADR-0002.

## Build
src/baseline/naive.py: embed query (Titan v2) → S3 Vectors top-8 (no
filters, no fusion, no graph) → one Claude call ("answer using these
passages") → return {answer, citations?: whatever the model emits}.
Wire behind POST /query?mode=naive so evals can target it forever.

## Explicit non-goals
No metadata filtering, no timeline graph, no HITL, no caching. Resist
improving it — its job is to lose correctly.

## Done when
Full golden set runs against mode=naive; results committed to
evals/history/ and milestones/M00b/. EXPECTED: q01-q04 (traps) fail,
q05-q06 (plain retrieval) pass. Tag m00b-baseline pushed. If the traps
PASS, the golden questions are too easy — tighten them (that finding is
itself evidence; record it).
