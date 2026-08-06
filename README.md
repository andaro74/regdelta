# RegDelta

Agentic FDA regulatory-change assistant, built milestone-by-milestone with
Claude Code. Every milestone is tagged, scored against a fixed golden
question set, and journaled — the repo history IS the demo.

## Progression

| M | Milestone | Tag | Traps (q01-q04) | Overall | Status |
|---|-----------|-----|-----------------|---------|--------|
| 00b | Naive-RAG baseline (the control) | `m00b-baseline` | 1/4 * | 30% | ✅ |
| 01 | Ingestion + amendment graph | `m01-ingestion` | n/a | n/a | ✅ |
| 02 | Two-tier retrieval (S3 Vectors / AOSS) | `m02-retrieval` | – | – | ⬜ |
| 03 | Agent graph + HITL | `m03-agents` | –/4 | –% | ⬜ |
| 04 | API + demo UI | `m04-demo` | – | – | ⬜ |
| 05 | Deploy + lifecycle | `m05-deploy` | – | – | ⬜ |
| 06 | Load + observability | `m06-scale` | – | – | ⬜ |
| 07 | Governance layer (three doors) | `m07-governance` | – | – | ⬜ |

Fill each row at milestone close (see .claude/skills/close-milestone).

\* The baseline's single trap "pass" (q03) is **not earned** — the question
leaks its own answer token and has no TTB source in the corpus to retrieve.
Recorded as-run per SPEC/00b's "if the traps pass, the questions are too
easy — record it" clause; a tightening is drafted and awaiting SME approval
(milestones/M00b). M01 has no eval row because the golden set needs an
answering endpoint, which is SPEC/04.
The intended arc: baseline fails the trap questions → retrieval fixes
recall → the agent graph fixes the traps → the rest makes it production-
shaped. Evidence lives in milestones/M*/ and evals/history/.

## Governance (separation of roles, from the start)
The org chart is encoded in the repo: CODEOWNERS maps files to role seats
(PM owns SPEC/**, the compliance SME owns golden ground truth, Security
owns tool policy + infra, the lead owns CLAUDE.md/ADRs), branch protection
makes those reviews mandatory, the eval-gate workflow blocks any PR that
regresses the golden set, and role subagents (.claude/agents/) run
first-pass review from each seat. Start here: docs/governance/ROLES.md ·
demo script: docs/governance/demo-script.md · setup:
docs/governance/branch-protection.md.

## Traceability rules
- One milestone = one branch (`mNN-<slug>`) = one tag at close.
- `python evals/run_evals.py --record` after every green run you care
  about — history is append-only JSON keyed by git SHA + tier.
- Consequential choices get an ADR (docs/adr/). Superseded ADRs are
  marked, never deleted.
- milestones/MNN/README.md answers: what can I demo right now, what's the
  delta vs baseline, what broke.

## Quick start
    make bootstrap && make core     # persistent stack (S3 Vectors tier)
    make ingest-backfill            # load the demo corpus
    make evals                      # definition of done
    make up / make down             # ephemeral AOSS hot tier per session

See SPEC/00-overview.md (mission), SPEC/00b (baseline), CLAUDE.md (rules).
