# SPEC/03 — Agent Graph (LangGraph)

## Goal
The reasoning layer: supervisor → parallel {retrieval, timeline, crossref}
→ applicability → verdict (+citations) → [HITL pause if confidence < 0.7].

## Nodes (src/graph/nodes.py)
- supervisor: classify intent, decompose, set company profile from request.
- retrieval_agent: calls the retrieval router (SPEC/02).
- timeline_agent: answers date questions from the DynamoDB amendment graph —
  walks SUPERSEDES edges with scope; NEVER from similarity search.
- crossref_agent: resolves "as defined in §", incorporation-by-reference,
  cross-agency triggers (FDA reformulation → TTB formula re-approval).
- applicability: company profile vs thresholds ($10M tiering, product types).
- verdict: rows {product, trigger, required_change, real_deadline,
  confidence, citations[]}. Distinguishes binding rule vs agency request
  (HHS "sooner" ask). Unknown → say so + escalate; never guess.
- hitl_gate: confidence < 0.7 → checkpoint (DynamoDB), write review item,
  END with status=pending_review. Resume endpoint continues from checkpoint.

## State (src/graph/state.py)
TypedDict: query, company_profile, retrieved[], timeline_facts[],
crossrefs[], verdict_rows[], confidence, citations[], status.

## Model policy (src/shared/config.py)
Sonnet-class for retrieval-adjacent nodes; strongest model for verdict
synthesis only. Model ids are config values, never literals in node code.
Bedrock prompt caching for the static system preamble.

## Done when
`make evals` ≥ 80% overall AND 100% on q01–q04 (trap questions), on the
S3 Vectors tier. HITL demonstrated: one golden question with an
underspecified company profile ends pending_review, then resumes correctly.
