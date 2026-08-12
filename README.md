# RegDelta

Agentic FDA regulatory-change assistant, built milestone-by-milestone with
Claude Code. Every milestone is tagged, scored against a fixed golden
question set, and journaled — the repo history IS the demo.

## Progression

| M | Milestone | Tag | Traps (q01-q04) | Overall | Status |
|---|-----------|-----|-----------------|---------|--------|
| 00b | Naive-RAG baseline (the control) | `m00b` | 1/4 * | 30% | ✅ |
| 01 | Ingestion + amendment graph | `m01` | n/a | n/a | ✅ |
| 02 | Two-tier retrieval (S3 Vectors / AOSS) | `m02` | n/a ** | 9/9 probes ** | ✅ |
| 03 | Agent graph + HITL | `m03` | –/4 | –% | ⬜ |
| 04 | API + demo UI | `m04` | – | – | ⬜ |
| 05 | Deploy + lifecycle | `m05` | – | – | ⬜ |
| 06 | Load + observability | `m06` | – | – | ⬜ |
| 07 | Governance layer (three doors) | `m07` | – | – | ⬜ |

Fill each row at milestone close (see .claude/skills/close-milestone).

\* The baseline's single trap "pass" (q03) is **not earned** — the question
leaks its own answer token and has no TTB source in the corpus to retrieve.
Recorded as-run per SPEC/00b's "if the traps pass, the questions are too
easy — record it" clause; a tightening is drafted and awaiting SME approval
(milestones/M00b). M01 has no eval row because the golden set needs an
answering endpoint, which is SPEC/04.

\*\* **M02's number is not comparable to the rows above it, and must not be read
as a delta.** "9/9 probes" is `recall@8 = 1.0` on both retrieval tiers over the
9-probe retrieval set — a *retrieval* measurement at the `router.retrieve()`
contract. It is not answer quality, so it is not a delta against M00b's 30%;
every scorecard carries `"comparable_to_baseline": false` and SPEC/02's "No trap
score" rule bars a trap column here. The golden set still needs SPEC/04's
answering endpoint, which is why the traps column reads n/a rather than 0/4.
Evidence: `evals/history/b16f596-retrieval-{s3vectors,aoss}.json`, gated by
`make retrieval-parity`.
Two things M02 recorded rather than resolved: Tier B's **hybrid** retrieval
measured *worse* than vector-only (7/9 vs 9/9), so the lexical lane is off
(ADR-0009 Ruling 3(a)); and Tier B's replacement justification — latency — is
**unmeasured**, owed to SPEC/04, with ADR-0001 amended to reopen if it shows no
advantage.
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
- One milestone = one branch (`mNN-<slug>`) = one tag at close (`mNN`).
  Branch and tag must NEVER share a name: git cannot disambiguate
  `refs/heads/x` from `refs/tags/x`, so `git push -u origin x` fails with
  "src refspec matches more than one" and `git checkout x` is ambiguous.
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
