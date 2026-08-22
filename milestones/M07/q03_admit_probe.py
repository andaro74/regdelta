"""Would admitting the ONE failing q03 observation actually clear the gate?

This is the load-bearing claim of the recommendation put to the SME seat, so it
is measured rather than reasoned. ADR-0005 exists because a plausible mechanism
was called "verified empirically" on an observation that did not discriminate.

`replay_history` does NOT read the recorded verdict for FRAGILE — it RE-SCORES
every recorded answer with today's `check()` (replay_history.py:148). So the
question is precisely: if `check()` returned no failures for that one recorded
response, does `went_bad` go false for q03, and does any other question still
gate?

Nothing is modified. This recomputes replay's own classification with one
observation's verdict overridden, and prints both the before and the after.

Reads only evals/. No API, no AWS, no cost.
"""
import itertools
import json
import pathlib
import sys

sys.path.insert(0, "evals")
from replay_history import recorded                      # noqa: E402
from run_evals import check                              # noqa: E402

GOLDEN = pathlib.Path("evals/golden_questions.json")
QS = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]}

# The observation the M05 seat examined and declared a false fail: q03 at
# 1f46b92, the answer whose only defect is the paraphrase of its own hedge.
ADMIT = ("q03", "1f46b92")


def classify(admit=None):
    """replay_history's own gating logic, recomputed. Returns (fragile, regressed)."""
    history = recorded()
    fragile, regressed = [], []
    for qid, q in QS.items():
        runs = history.get(qid) or []
        if not runs:
            continue
        agent = []
        for run in runs:
            if run["mode"] == "naive":
                continue
            fails = check(q, run["resp"])
            if admit and (qid, run["sha"][:7]) == admit and fails:
                fails = []                     # the seat's per-observation ruling
            agent.append((run, not fails, fails))
        seq = [ok for _, ok, _ in agent]
        if any(prev and not cur for prev, cur in itertools.pairwise(seq)):
            fragile.append(qid)
        for run, ok, f in agent:
            if run["recorded_pass"] and not ok:
                regressed.append((qid, run["sha"][:7], f))
    return fragile, regressed


for label, admit in (("BEFORE — as the repo stands", None),
                     (f"AFTER  — admitting {ADMIT[0]} at {ADMIT[1]}", ADMIT)):
    fragile, regressed = classify(admit)
    print(f"{label}")
    print(f"    FRAGILE (gates)   : {fragile or 'none'}")
    print(f"    REGRESSED (gates) : {[r[:2] for r in regressed] or 'none'}")
    print(f"    replay would exit : {1 if (fragile or regressed) else 0}")
    print()

print("Note: the override above is applied to ONE (question, sha) pair and to a")
print("verdict that is already failing. It cannot turn a PASS into anything, and")
print("it cannot reach any other question or any future answer.")
