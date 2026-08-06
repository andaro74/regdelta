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
`make baseline` runs the full golden set against mode=naive and records a
scorecard to evals/history/; results committed to evals/history/ and
milestones/M00b/. Tag `m00b` exists at the recorded commit.

PREDICTION, not a criterion: q01-q04 (traps) fail, q05-q06 (plain
retrieval) pass. The control is allowed to score anything; record what
actually happened either way.

FALSIFIED by run `7f012b8-naive-full`: q05 also fails. The baseline states
the right criteria and cites nothing, attributing them to "the Background
passage." The control is weaker than this spec assumed — 3/10, traps 1/4.
Do not "fix" q05 to match this prediction: the correct-content /
no-provenance failure IS the demo, and every later milestone's delta is
measured from 3/10.

If a trap PASSES, the question is too easy. Recording the finding with a
drafted tightening satisfies THIS milestone — ground truth is SME-owned
and engineering may not edit it (CLAUDE.md). It does not satisfy the next
one: no milestone may report a trap score until every open tightening is
SME-approved and applied, or explicitly closed won't-fix. Open at M00b
close: q03.

The control is only comparable if it is frozen: NAIVE_MODEL, NAIVE_TOP_K=8
and temperature 0 are pinned constants. If any changes — including an
upgrade becoming available — re-run and re-record the baseline; never
compare across two controls.
