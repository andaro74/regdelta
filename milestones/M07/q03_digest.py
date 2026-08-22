"""Compute the register entry for the observation the seat admitted.

The digest is taken over `run_evals.flatten_answer(resp)` — the exact text
`check()` scores — rather than over the response dict, which also carries
`cache`, `tier` and `fallback_reason`. Those describe how the answer was
obtained, not what was scored, and an admission keyed on them would break for
reasons unrelated to the answer.

Prints the entry to paste into evals/admitted_false_fails.json.
No API, no AWS, no cost.
"""
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, "evals")
from replay_history import recorded                      # noqa: E402
from run_evals import check, flatten_answer              # noqa: E402

GOLDEN = pathlib.Path("evals/golden_questions.json")
QS = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]}

for run in recorded()["q03"]:
    fails = check(QS["q03"], run["resp"])
    if not fails:
        continue
    print(json.dumps({
        "question": "q03",
        "sha": run["sha"],
        "at": run["at"],
        "mode": run["mode"],
        "scored_sha256": hashlib.sha256(
            flatten_answer(run["resp"]).encode("utf-8")).hexdigest(),
        "admits_fails": fails,
    }, indent=2))
