# RegDelta

Agentic regulatory-change assistant for food labeling (FDA). Answers "what
changed, does it apply to us, and what's the real deadline?" with citations.

## Commands
- `make evals`         — full golden set against the live API (the definition of done)
- `make smoke`         — 5-question smoke subset
- `make test`          — unit tests (pytest)
- `make core`          — deploy persistent stack
- `make up` / `make down` — create/destroy the ephemeral AOSS hot tier
- `make status`        — search-tier state + session cost

## Stack
Python 3.14 · LangGraph · Bedrock (Claude + Titan v2 embeddings, 1024-dim)
· S3 Vectors (always-on tier) · OpenSearch Serverless (ephemeral hot tier)
· DynamoDB · AWS CDK (Python) · FastAPI on Lambda.

## Architecture rules
- S3 corpus bucket is the source of truth. Search indexes are pure functions
  of it. Never write ingestion output directly to AOSS.
- Retrieval routes by SSM param `/regdelta/search/endpoint`: present → AOSS;
  absent → S3 Vectors path. Both paths must pass evals.
- AOSS is **not hybrid by default** (ADR-0009 Ruling 3(a)). Measured, BM25
  ranked the chunk that answered the question 14th while promoting shorter
  chunks that merely repeat the query's terms: hybrid scored 7/9 against
  vector-only's 9/9. `config.RETRIEVAL_LEXICAL_LANE=1` restores it and is off
  by default. Do not re-enable it to "fix" a probe — the reversal condition is
  a probe the lexical lane *wins*, and it is written beside the flag.
  Consequently both tiers now run the same algorithm on different
  infrastructure: AOSS earns its place on latency and concurrent load, not on
  relevance. Say that, not "hybrid".
- Embeddings are computed once at ingest and persisted with chunks. Never
  re-embed during index hydration.
- Every answer must cite FR doc number and/or CFR section for each claim.
  An answer without citations is a bug, not a style issue.
- Timeline questions (effective vs compliance dates, supersession) are
  answered from the DynamoDB amendment graph, not vector similarity.

## Workflow
- One milestone per session. Read the relevant SPEC/*.md first; its
  "Done when" is the exit criterion. Never mark done until it passes.
- Work on branch mNN-<slug>; the close tag is the short form `mNN` (never
  the branch name — a same-named branch and tag make git refspecs
  ambiguous). At milestone close, the user runs /close-milestone NN (see
  .claude/skills/close-milestone): evidence pack in milestones/MNN/,
  `run_evals.py --record`, ADR if needed, tag.
- Baseline discipline: never "improve" src/baseline/naive.py — it is the
  control (ADR-0002). All progress claims are deltas vs its scorecard.
- Ask before adding dependencies.
- Role gates (docs/governance/ROLES.md): never edit
  evals/golden_questions.json to make a failure pass — run the
  sme-eval-triage agent and STOP for a human decision from the SME seat. Run
  security-reviewer on any infra/IAM/workflow diff and eng-code-reviewer
  before opening a PR. Spec changes go through pm-spec-reviewer.
  There is one human here, so no gate is mechanically enforced (ADR-0005).
  What makes an SME-seat ruling sound is a primary-source citation a reader
  can falsify — never a signature. Say "ruling, with sources", not "approved".
  The routing rule is kept because it works: stopping is what caught q08 and
  the fabricated compliance date.
- Regulatory-domain details (date semantics, amendatory instructions,
  thresholds) live in .claude/skills/regulatory-domain — consult when
  working on ingestion parsing or graph nodes.
