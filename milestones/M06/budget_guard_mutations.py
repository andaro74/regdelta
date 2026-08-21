"""Mutations against the $20 load-test ceiling.

The human seat approved a hard ceiling at M06 open. A ceiling is only worth the
refusals it can actually make, so every branch in `loadtest/budget.py` that can
say no is broken here in turn, and `tests/test_loadtest_budget.py` must go RED
for each. A survivor means the ceiling is a number in a file.

The specimens and the guard share an author, which the M05 record says is the
condition under which a rule cannot be validated by its own author's examples
(`milestones/M05/q03-ruling.md`). This harness does not fix that; it narrows it,
by testing the GUARD rather than agreeing with it. eng-code-reviewer is the
other half.

Offline, free, no AWS. Every mutation is reverted in a `finally`.

Run: python milestones/M06/budget_guard_mutations.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUDGET = ROOT / "loadtest" / "budget.py"
CONFIG = ROOT / "src" / "shared" / "config.py"
TEST = "tests/test_loadtest_budget.py"

MUTATIONS = [
    ("B1-ceiling-not-enforced", BUDGET,
     "    if usd > ceiling:\n        raise BudgetExceededError(",
     "    if False:\n        raise BudgetExceededError(",
     "the dollar ceiling stops refusing; a $2,629 plan runs"),

    ("B2-ceiling-off-by-one", BUDGET,
     "    if usd > ceiling:",
     "    if usd > ceiling * 10:",
     "a ceiling that is silently ten times what the seat approved"),

    ("B3-quota-check-skipped", BUDGET,
     "        if total > cap:",
     "        if False:",
     "the refusal money cannot buy stops firing; a plan needing 125x a "
     "non-adjustable cap is approved"),

    ("B4-quota-ignores-todays-spend", BUDGET,
     "        total = planned + already.get(model, 0)",
     "        total = planned",
     "every plan is checked against a fresh day, so a run late in the day "
     "passes and then throttles"),

    ("B5-unpriced-model-is-free", BUDGET,
     "        raise UnpricedModelError(",
     "        return {\"input\": 0.0, \"output\": 0.0}  # noqa\n    if False:\n        raise UnpricedModelError(",
     "a model with no rate costs zero, so every total stays plausible and is "
     "wrong in our favour"),

    ("B6-meter-checks-after-instead-of-before", BUDGET,
     "        if self.spent() + estimate > self.ceiling:",
     "        if self.spent() > self.ceiling:",
     "reserve() detects an overshoot instead of preventing one — a log line, "
     "not a ceiling"),

    ("B7-cache-writes-priced-as-plain-input", BUDGET,
     '            + (cache_write * r["input"] * 1.25)) / 1_000_000',
     '            + (cache_write * r["input"] * 1.00)) / 1_000_000',
     "cache writes under-priced by 25%, in the direction that flatters us"),

    ("B8-cache-tokens-dropped-from-the-quota-count", BUDGET,
     "        return self.calls * (self.input + self.output\n"
     "                             + self.cache_read + self.cache_write)",
     "        return self.calls * (self.input + self.output)",
     "a cached run under-counts against a cap that cannot be raised"),

    ("B9-seat-approved-ceiling-changed", CONFIG,
     'LOADTEST_BUDGET_USD = float(os.environ.get("LOADTEST_BUDGET_USD", "20.00"))',
     'LOADTEST_BUDGET_USD = float(os.environ.get("LOADTEST_BUDGET_USD", "200.00"))',
     "the default ceiling silently becomes ten times what the seat approved"),

    ("B10-opus-rate-set-to-list-price", CONFIG,
     '"us.anthropic.claude-opus-4-6-v1": {"input": 5.50, "output": 27.50},',
     '"us.anthropic.claude-opus-4-6-v1": {"input": 5.00, "output": 25.00},',
     "Bedrock's marketplace rate replaced by the first-party list price, "
     "under-counting every estimate by 10%"),

    ("B11-daily-cap-inflated", CONFIG,
     '"us.anthropic.claude-opus-4-6-v1": 2_592_000,',
     '"us.anthropic.claude-opus-4-6-v1": 25_920_000,',
     "the non-adjustable cap recorded as ten times its real value"),
]


def run_guard() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    return proc.returncode, (proc.stdout + proc.stderr)[-800:]


def main() -> int:
    rc, out = run_guard()
    if rc != 0:
        print("BASELINE IS RED — fix the guard before mutating it.\n" + out)
        return 2
    print(f"baseline: green ({TEST})\n")

    results = []
    for mid, path, find, replace, why in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if find not in original:
            results.append({"id": mid, "outcome": "NOT-APPLIED", "why": why,
                            "detail": "anchor text not found"})
            print(f"  {mid:38s} NOT-APPLIED  (anchor missing)")
            continue
        try:
            path.write_text(original.replace(find, replace, 1), encoding="utf-8")
            rc, out = run_guard()
        finally:
            path.write_text(original, encoding="utf-8")
        outcome = "killed" if rc != 0 else "SURVIVED"
        results.append({"id": mid, "outcome": outcome, "exit": rc, "why": why,
                        "tail": out if rc == 0 else None})
        print(f"  {mid:38s} {outcome}")

    after, _ = run_guard()
    survivors = [r for r in results if r["outcome"] != "killed"]
    Path(__file__).with_suffix(".json").write_text(json.dumps({
        "guard": TEST,
        "ceiling_usd_approved_by_the_seat": 20.00,
        "mutations": len(MUTATIONS),
        "survivors": len(survivors),
        "tree_restored_and_green": after == 0,
        "results": results,
    }, indent=2), encoding="utf-8")

    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
    if after != 0:
        print("!! the tree did not come back green — check `git diff`")
        return 3
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
