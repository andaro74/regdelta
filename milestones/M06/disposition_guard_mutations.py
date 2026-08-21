"""Mutations against `loadtest/retrieval_load.py`'s judgement.

This file is the one that decides whether Tier B survives M06, so ADR-0013
applies to it more than to anything else in the milestone: a gate here that has
never refused anything is a gate nobody has checked, and the thing it would let
through is a retirement reached on a misconfiguration.

FIVE FAMILIES, because there are five ways to get the verdict wrong:

  V  the comparison itself — the keep condition, the tie, the disjuncts
  S  which samples it is taken over — warmup, pooling, the highest step
  G  the gates — corpus, vantage, config, tier, scored-run count
  C  the POPULATION the p95 is taken over. A latency exists only for a call
     that returned one, so a tier that failed most of its calls is compared on
     the few that survived — and the ones that fail are the slow ones. The
     worse tier looks faster, and the keep condition is a disjunction.
  O  the ORDER the outcomes are decided in, which is not a style question:
     a gate failure reported as a failed measurement spends one of the two
     attempts Change 6 allows, and a second one retires Tier B by default

The C family arrived with the code it attacks, which is the discipline
security-reviewer asked for: a family that only mutates code an existing guard
already reads can never surface a property no guard asserts. Every clause added
in response to a finding now ships with the mutation that would delete it.

Every mutation must turn `tests/test_tier_disposition.py` RED. A survivor means
that assertion is decoration.

Offline, free, no AWS — `dispose()` is pure, which is why it is a separate
function from `run_half()`. Every mutation is applied to the file's text and
reverted in a `finally`, and the run re-checks that the tree came back green.

Run: python milestones/M06/disposition_guard_mutations.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "loadtest" / "retrieval_load.py"
TEST = "tests/test_tier_disposition.py"

#: (id, find, replace, why it must be caught)
MUTATIONS = [
    # ------------------------------------------------------- V: the comparison
    ("V1-keep-on-any-difference",
     '                     and b["p95_ms"] <= a["p95_ms"])',
     '                     and b["p95_ms"] <= a["p95_ms"] * 1.10)',
     "a 10% grace on the keep condition. The clause says at or below, and "
     "'a difference inside the recorded run-to-run spread is not an advantage'"),

    ("V2-the-comparison-is-inverted",
     '                     and b["p95_ms"] <= a["p95_ms"])',
     '                     and a["p95_ms"] <= b["p95_ms"])',
     "`a` is Tier A and `b` is Tier B; swapped, the slower tier keeps its "
     "place and the faster one retires. Nothing about the artifact would look "
     "wrong"),

    ("V3-error-rate-disjunct-needs-no-margin",
     '(a["error_rate"] - b["error_rate"]) >= ERROR_RATE_ADVANTAGE',
     '(a["error_rate"] - b["error_rate"]) > 0',
     "'at least 5 percentage points lower' becomes 'lower at all', which any "
     "noise satisfies"),

    ("V4-the-disjunction-becomes-a-conjunction",
     'out["verdict"] = "keep" if (latency_keeps or errors_keep) else "retire"',
     'out["verdict"] = "keep" if (latency_keeps and errors_keep) else "retire"',
     "the clause is a disjunction — either arm keeps Tier B. As a conjunction "
     "the error-rate route is unreachable and Tier B retires on latency alone"),

    ("V5-retirement-stops-naming-what-is-removed",
     '           "regdelta-search stack, the AOSS client, the reindex Lambda and the "\n'
     '           "routing branch are removed, and /regdelta/search/endpoint stops "\n'
     '           "being a tier selector.")',
     '           "Tier B is retired.")',
     "a retirement verdict that does not say what retirement DOES is a verdict "
     "nobody can act on; the clause enumerates five things"),

    # -------------------------------------------------------- S: the samples
    ("S1-warmup-is-scored",
     'return [r for r in attempt.get("runs") or [] if not r.get("warmup")]',
     'return list(attempt.get("runs") or [])',
     "'three times per tier, the first discarded as warmup'. A cold Lambda's "
     "boto3 client construction was 819.7-1,019.6 ms at M04; pooling it moves "
     "a p95"),

    ("S2-the-lowest-step-becomes-dispositive",
     "    rate = max(qualifying)",
     "    rate = min(qualifying)",
     "'the HIGHEST arrival rate at which both tiers completed the step'. The "
     "lowest is the one where concurrency — Tier B's only remaining case — has "
     "barely been applied"),

    ("S3-p95-becomes-p50",
     '        "p95_ms": _percentile(samples, 0.95),',
     '        "p95_ms": _percentile(samples, 0.50),',
     "the clause names p95, and a median hides the tail that a concurrency "
     "profile exists to expose"),

    ("S4-percentile-drifts-from-the-drivers",
     "    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))",
     "    rank = max(1, min(len(ordered), int(q * len(ordered))))",
     "linear-rank instead of nearest-rank. Two percentile methods over the "
     "same samples can differ by more than the effect being measured, and the "
     "artifact would carry both numbers under one stated method"),

    ("S5-a-tiers-steps-are-pooled-with-the-other-tiers",
     '    return [s for run in _scored_runs(attempt)\n'
     '            for s in run.get("steps") or [] if s.get("driven_rate") == rate]',
     '    return [s for run in _scored_runs(attempt)\n'
     '            for s in run.get("steps") or []]',
     "every rate's samples pooled into every step: the dispositive p95 stops "
     "being about the dispositive step and no longer varies with load at all"),

    # ----------------------------------------------------------- G: the gates
    ("G1-eligibility-reads-the-drivers-claim",
     '    if step.get("invocation_error"):\n        return False',
     '    return bool(step.get("dispositive_eligible"))\n'
     '    if step.get("invocation_error"):\n        return False',
     "the orchestrator would then gate on the writer's own summary rather than "
     "on the run — the defect `evals/run_demo_parity.py` found three times"),

    ("G2-a-fallen-back-step-counts",
     '    if step.get("tiers_observed") != [tier]:\n        return False',
     "",
     "the security-review finding at the orchestrator layer: a step that "
     "answered from the other tier, filed under this one"),

    ("G2b-a-step-with-no-successful-call-counts",
     '    if not step.get("latencies_ms"):\n        return False',
     "",
     "the hole G2 exposed on its first outing. A step where every call raised "
     "observes no tier, which the half-level union check reads as no "
     "disagreement, and carries no samples — so it reached the dispositive "
     "slot with p95 None on both sides, neither disjunct held, and Tier B "
     "retired on a run that measured nothing"),

    ("G3-the-corpus-gate-accepts-two-absences",
     '    out["corpus_agree"] = (len(set(fingerprints.values())) == 1\n'
     '                           and all(fingerprints.values()))',
     '    out["corpus_agree"] = len(set(fingerprints.values())) == 1',
     "`corpus.fingerprint()` returns {'available': false} with REGISTRY_TABLE "
     "unset, and two Nones are equal — the gate silently stops gating, which "
     "is exactly why RESOLVE_ENV_STRICT exists"),

    ("G4-the-vantage-gate-goes-away",
     '    if len({attempts[t].get("vantage") for t in present}) != 1:\n'
     '        failures.append(f"the halves were driven from different vantages: "\n'
     '                        f"{out[\'vantage\']}")',
     "",
     "'from one vantage recorded and identical across both halves' — Change 5 "
     "is the reason internal validity survives the move in-region at all"),

    ("G5-a-half-with-one-scored-run-is-accepted",
     '        if len(scored) < RUNS_PER_TIER - WARMUP_RUNS:',
     '        if len(scored) < 0:',
     "one scored run per tier is not the clause's measurement, and run-to-run "
     "spread is what 'ties retire' is defined against"),

    # ------------------------------ C: the population the p95 is taken over
    # HIGH 3. A p95 is computed over the calls that returned a latency, so a
    # tier that failed most of its calls is compared on the few that survived
    # — and the ones that fail are the slow ones. Survivor bias makes the WORSE
    # tier look faster, and the keep condition is a disjunction, so a low p95
    # over a tiny sample keeps Tier B on the strength of having broken.

    ("C1-the-latency-arm-ignores-comparability",
     "    latency_keeps = (comparable\n"
     '                     and b["p95_ms"] is not None and a["p95_ms"] is not None',
     '    latency_keeps = (b["p95_ms"] is not None and a["p95_ms"] is not None',
     "survivor bias wins the latency disjunct: Tier B fails 60% of its calls, "
     "its surviving 40% are fast, and it keeps its place for having broken"),

    ("C2-comparability-loses-its-absolute-value",
     '                  and abs(a["error_rate"] - b["error_rate"]) < ERROR_RATE_ADVANTAGE)',
     '                  and (a["error_rate"] - b["error_rate"]) < ERROR_RATE_ADVANTAGE)',
     "signed instead of absolute: a Tier B that is far WORSE gives a negative "
     "difference, which is below the threshold, so exactly the case the rule "
     "exists for is read as comparable"),

    ("C3-comparability-accepts-any-gap",
     "abs(a[\"error_rate\"] - b[\"error_rate\"]) < ERROR_RATE_ADVANTAGE)",
     "abs(a[\"error_rate\"] - b[\"error_rate\"]) < 1.0)",
     "the threshold widened to everything, which is C1 by another route and "
     "the shape a 'temporary' loosening takes"),

    ("C4-a-step-that-lost-calls-counts",
     '    dispatched, returned = step.get("dispatched"), step.get("returned")\n'
     "    if dispatched is None or returned is None or returned != dispatched:\n"
     "        return False",
     "",
     "a call that never returned is in no sample, so it is invisible in `n` "
     "AND in the error rate. Measured: 2 of 20 returned, error_rate 0.0, "
     "dispositive_eligible true, p95 over two samples"),

    ("C5-a-missing-account-is-assumed-complete",
     "    if dispatched is None or returned is None or returned != dispatched:",
     "    if dispatched is not None and returned is not None and returned != dispatched:",
     "a step recorded by a driver that predates the fields would be assumed to "
     "have accounted for everything — the artifact is the evidence, and an "
     "absent field is not a passing one"),

    # ----------------------------------------------------------- O: the order
    ("O1-the-floor-is-decided-before-the-gate",
     '    if failures:\n'
     '        out["verdict"] = "gate-failed"\n'
     '        out["verdict_reason"] = (\n'
     '            "the comparison was not made: " + "; ".join(failures))\n'
     '        return out\n\n'
     '    qualifying = [r for r in SCHEDULE if per_rate[r]["both_eligible"]]',
     '    qualifying = [r for r in SCHEDULE if per_rate[r]["both_eligible"]]',
     "THE ORDERING BUG, as it actually occurred. A half that answered from the "
     "wrong tier makes every step ineligible, so with the floor first an IAM "
     "propagation delay presents as 'no qualifying step', spends one of the "
     "two attempts Change 6 allows, and on a repeat RETIRES TIER B by the "
     "default outcome — on a misconfiguration"),

    ("O2-a-failed-measurement-is-a-retirement-on-the-first-attempt",
     '        second = min(out["attempts_per_tier"].values()) >= 2',
     "        second = True",
     "Change 6: a run that reached no real load is a failed measurement, NOT a "
     "retirement. Unbounded the other way, a dead profile becomes the argument "
     "against Tier B"),

    ("O3-the-floor-never-terminates",
     '        second = min(out["attempts_per_tier"].values()) >= 2',
     "        second = False",
     "the other direction, and the reason Change 6 is bounded at one re-run: "
     "M06 would end with Tier B alive and the bar never met, which "
     "`SPEC/06:48-49` forbids"),

    ("O4-a-measured-retirement-exits-non-zero",
     '    return 0               # keep or retire, on a qualifying step',
     '    return 1               # keep or retire, on a qualifying step',
     "a retirement reached ON A QUALIFYING STEP is the harness working. Exit 1 "
     "would make `make tier-disposition` read as broken at the moment it "
     "succeeded, and the operator would re-run it"),

    ("O5-an-unmeasured-retirement-exits-zero",
     '    if disposition.get("failed_measurement"):\n'
     '        return 5           # `retire` reached by the default outcome, not measured',
     "",
     "the clause asks the target to exit non-zero when no step qualifies. Exit "
     "0 would file a retirement nobody measured as a clean run"),
]


def run_guard() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    return proc.returncode, (proc.stdout + proc.stderr)[-800:]


def main() -> int:
    baseline_rc, baseline_out = run_guard()
    if baseline_rc != 0:
        print("BASELINE IS RED — fix the guard before mutating it.")
        print(baseline_out)
        return 2
    print(f"baseline: green ({TEST})\n")

    original = ORCH.read_text(encoding="utf-8")
    results = []
    for mid, find, replace, why in MUTATIONS:
        if find not in original:
            results.append({"id": mid, "outcome": "NOT-APPLIED",
                            "detail": "anchor text not found; the mutation "
                                      "does not describe today's source",
                            "why": why})
            print(f"  {mid:52s} NOT-APPLIED  (anchor missing)")
            continue
        try:
            ORCH.write_text(original.replace(find, replace, 1), encoding="utf-8")
            rc, out = run_guard()
        finally:
            ORCH.write_text(original, encoding="utf-8")
        outcome = "killed" if rc != 0 else "SURVIVED"
        results.append({"id": mid, "outcome": outcome, "exit": rc,
                        "why": why, "tail": out if rc == 0 else None})
        print(f"  {mid:52s} {outcome}")

    after_rc, _ = run_guard()
    survivors = [r for r in results if r["outcome"] != "killed"]
    report = {
        "guard": TEST,
        "subject": "loadtest/retrieval_load.py",
        "baseline_green": baseline_rc == 0,
        "tree_restored_and_green": after_rc == 0,
        "mutations": len(MUTATIONS),
        "survivors": len(survivors),
        "results": results,
    }
    out_path = Path(__file__).with_suffix(".json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed  "
          f"-> {out_path.name}")
    if after_rc != 0:
        print("!! the tree did not come back green — check `git diff`")
        return 3
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
