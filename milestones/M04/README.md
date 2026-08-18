# M04 — API + Demo UI  **(IN PROGRESS)**

- Branch: `m04-api-demo`   PR: **#11 (draft)**   Spec: `SPEC/04-api-and-demo.md`
- Base: `main` at `f22b545` (M02 + M03 merged 2026-08-16)
- This pack is written mid-milestone, not at close. Everything below is either
  measured and cited, or named as not yet done. Nothing here is a projection.

## Where it stands

| phase | state |
|---|---|
| 0 — spec amendment (`/resume` auth) | **done**, `pm-spec-reviewer` accept-with-changes |
| 1 — `/query`, `/resume`, `/health`, `scenarios.json` | **done**, verified end-to-end against real AWS |
| 2 — response cache + bypass | **done**, verified against real DynamoDB |
| crossref wiring (M03 carryover, M04-blocking) | **done**, SPEC/04's retrieval gate now passes |
| 3 — UI | not started |
| 4 — `make demo-parity` + Tier B latency | **not started — next** |
| 5 — golden set vs deployed API, both tiers | not started |

## Evidence

`evals/history/a7bd28c-s3vectors-full.json` — agent mode, 49-document corpus:

    overall            18/20  (90%)     was 16/20 before the crossref fix
    --subset retrieval   5/5            SPEC/04's Done-when clause: MET
    --subset trap        8/8
    --subset smoke       5/5
    --subset timeline    6/7

690 tests, ruff clean, CI green on #11.

## What Phase 4 actually requires

SPEC/04's comparability criterion, read closely — it carries **two controls that
are corrections, not refinements**, and the criterion measures nothing without
them:

1. **Both tier runs bypass the response cache**, and the artifact records that
   they did. Implemented and ready: `no_cache: true` in the body, or the
   `x-regdelta-no-cache` header; every response carries a `cache` field
   (`hit|miss|bypass|disabled`). Without this the two runs are minutes apart
   inside a 1h TTL, the second is a hit returning the first tier's answer, and
   citations agree by construction.
2. **Each scenario answered twice on ONE tier.** Without a same-tier control a
   disagreement cannot be attributed: ordinary run-to-run variance and genuine
   tier-caused divergence look identical.

The artifact is `milestones/M04/answer-parity-<sha>.json`, recording per
scenario per tier: scenario `id`, **sha256 of the question and profile as run**,
the citation set, every `real_deadline`, and the cache status. It passes when
the two tiers agree on citations (as sets) and every `real_deadline` exactly.
Confidence and prose may differ.

Plus **Tier B's latency**, a debt owed since ADR-0001 asked for "retrieval p50
per tier" at M02: median and p95 `router.retrieve()` per tier over the probe
set, in the artifact. **No target is set, deliberately** — the criterion gates
that an honest number exists, not that it beats a threshold. If Tier B is not
meaningfully faster, that is a finding and a demo beat to drop.

## Deferred, with evidence — not forgotten

- **q15 / retrieval decomposition.** One unfiltered query at `top_k=8` for a
  question naming two unrelated triggers; the colour half dominates the
  embedding and the 'healthy' half is never retrieved. NOT in any gated subset
  (`[applicability, verdict]`) and all three demo scenarios pass, so it does not
  block M04. It is the worst remaining defect for a compliance product: it told
  a manufacturer bearing a 'healthy' claim that no such rule could be confirmed.
- **q12 / point-in-time reasoning.** The system answers "was that a fair reading
  in mid-2025" as a likelihood question rather than a finality one. Ruled (a)
  SYSTEM by `sme-eval-triage` against 21 U.S.C. 371(e)(2); the question stands.
- **The naive control passes four of the eight traps** (q02, q04, q11, q20) on
  its own recorded answers. SME-seat re-read. Declared in SPEC/03 and the M03
  pack.
- **Rule (7)'s match reporter.** `check()` reports only failure reasons, so a
  PASS is unauditable at token granularity. Would have caught q05 while green.
- **Per-job workflow permissions guard.** Declined 2026-08-16 with a reversal
  condition recorded in `.github/workflows/evals.yml`: add it in the same change
  that flips `EVAL_GATE_ENABLED`.
- **`>= 80%` as a form of bar.** At twenty questions it permits four failures
  where it permitted two at ten. Recommendation on file is an absolute count,
  with an ADR, before the set grows again.

## Environment notes that cost real time this session

- **Always `eval "$(python evals/local_env.py)"` before anything touching AWS.**
  It resolves the deployed query Lambda's own environment. Without it the shim
  exits and `make agent-evals` measures nothing.
- **Two interpreters.** `.venv` and the user-level Python 3.14 both exist and
  disagreed; `.venv` was missing `langgraph`, `fastapi`, `ruff` and `httpx`
  entirely. `pip install -r requirements-dev.txt` makes `.venv` match CI.
- **`gh` is at `/c/Program Files (x86)/GitHub CLI/gh.exe`** and may not be on
  PATH in a shell started before the 2.97 upgrade.
- **ruff's `EXE001`/`EXE002` are skipped on Windows** — they read the filesystem
  exec bit. `tests/test_file_modes.py` closes that gap from the git index.
- **This shell mangles backslashes in heredocs.** Write scripts with a file, not
  a heredoc, when they contain regexes or line continuations.

## The one decision still open

Whether **retrieval decomposition** (q15) is folded into M04 or takes its own
milestone. It is out of SPEC/04's scope and blocks nothing M04 gates on; the
argument for pulling it in is that `make demo-parity`'s artifact would otherwise
describe a system that changes shortly after. That argument is weak — artifacts
here are sha-stamped by design — so the default is: **leave it deferred.**
