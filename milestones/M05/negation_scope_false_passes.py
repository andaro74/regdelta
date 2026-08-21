"""The four false passes that got the M05 negation-scope rule reverted.

Run against the CURRENT scorer, this must report 0 false passes: the bare
substring test in `run_evals.check()` catches all four. Run against any future
attempt at negation scope, it is the acceptance bar — a rule that lets any of
these through reopens the defect the 2026-08-12 q03 ruling closed.

B1 is the one that settles it: a fabricated TTB obligation, asserted flatly
after a concessive `whether exempt or not`, scoring PASS. No TTB source
document exists anywhere in the corpus.

Found by eng-code-reviewer on commit 4ed91b8; reproduced here before acting.
See milestones/M05/q03-ruling.md §10. No API, no AWS, no cost.
"""
import json
import sys

sys.path.insert(0, "evals")
import run_evals as r

with open("evals/golden_questions.json", encoding="utf-8") as fh:
    QS = {q["id"]: q for q in json.load(fh)["questions"]}


def verdict(qid, answer, rows=None, status="ok"):
    resp = {"answer": answer, "citations": [], "status": status}
    if rows is not None:
        resp["answer_rows"] = rows
    fails = r.check(QS[qid], resp)
    banned = [f for f in fails if "forbidden text present" in f]
    return ("PASS" if not fails else "FAIL"), banned, fails


CASES = [
    ("B1 q03 concessive 'whether exempt or not'", "q03",
     "You must stop using Red No. 3 by January 15, 2027 (90 FR 4628). I cannot confirm "
     "the filing deadline, but whether exempt or not, TTB requires a revised formula.",
     None, "ok"),
    ("B2 q03 hedge-then-assert, same sentence", "q03",
     "You must stop by January 15, 2027 (90 FR 4628). I cannot confirm whether TTB "
     "requires it; TTB requires it before you ship.",
     None, "ok"),
    ("B3 q18 'cannot say whether I cannot determine'", "q18",
     "You are affected. The compliance date is February 25, 2028 (89 FR 106064). "
     "I cannot say whether I cannot determine your date without your annual food sales.",
     None, "ok"),
    ("B4 q03 banned token inside answer_rows", "q03",
     "You must stop using Red No. 3 by January 15, 2027 (90 FR 4628).",
     [{"required_change": "Reformulate; I cannot confirm whether",
       "note": "TTB requires a revised formula before you ship"}], "ok"),
]

print(f"{'case':50} {'verdict':8} banned-token failure?")
print("-" * 92)
bad = 0
for label, qid, answer, rows, status in CASES:
    v, banned, fails = verdict(qid, answer, rows, status)
    leak = (v == "PASS")
    bad += leak
    print(f"{label:50} {v:8} {'NONE  <-- FALSE PASS' if leak else banned[:1]}")
    if not leak and not banned:
        print(f"{'':50} (failed, but not on the ban: {fails})")
print()
print(f"{bad} of {len(CASES)} reproduce as FALSE PASSES")
