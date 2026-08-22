"""Which instrument, if any, separates q03's correct hedge from a flat assertion?

The M05 open thread proposes scoring q03 structurally: "the defect is a TTB
proposition carrying a Red No. 3 citation, and the failing answer's
`answer_rows[1].citations` was `[]`, so it is checkable structurally." That is
one observation of one card. This probe tests the three candidate instruments
against ALL the specimens the seat has already declared, before anything is
built.

A candidate is only usable if it scores every CORRECT and LIMIT_FALSE_FAIL
specimen PASS and every WRONG specimen FAIL, and lets none of
`negation_scope_false_passes.py`'s four through.

Reads only evals/ and milestones/. No API, no AWS, no cost.
"""
import json
import sys

sys.path.insert(0, "evals")
import run_evals as r                                    # noqa: E402
from check_discrimination import (CORRECT, LIMIT_FALSE_FAIL,  # noqa: E402
                                  LIMIT_FALSE_PASS, SPECIMENS, WRONG)

QS = {q["id"]: q for q in json.loads(
    open("evals/golden_questions.json", encoding="utf-8").read())["questions"]}

# The four reproductions that got the M05 negation-scope rule reverted.
FALSE_PASS_BAR = [
    ("B1 concessive 'whether exempt or not'", "q03",
     "You must stop using Red No. 3 by January 15, 2027 (90 FR 4628). I cannot confirm "
     "the filing deadline, but whether exempt or not, TTB requires a revised formula.",
     None),
    ("B2 hedge-then-assert, same sentence", "q03",
     "You must stop by January 15, 2027 (90 FR 4628). I cannot confirm whether TTB "
     "requires it; TTB requires it before you ship.", None),
    ("B4 banned token inside answer_rows", "q03",
     "You must stop using Red No. 3 by January 15, 2027 (90 FR 4628).",
     [{"required_change": "Reformulate; I cannot confirm whether",
       "note": "TTB requires a revised formula before you ship"}]),
]


def fails_of(qid, answer, rows=None):
    resp = {"answer": answer, "citations": [], "status": "ok"}
    if rows is not None:
        resp["answer_rows"] = rows
    return r.check(QS[qid], resp)


def without_ban(qid, answer, rows=None):
    """The same scorer with q03's TTB ban removed — candidate 'drop the ban'."""
    q = dict(QS[qid])
    q["must_not_contain"] = [n for n in q.get("must_not_contain", [])
                             if "ttb" not in n.lower()]
    resp = {"answer": answer, "citations": [], "status": "ok"}
    if rows is not None:
        resp["answer_rows"] = rows
    return r.check(q, resp)


print("=" * 96)
print("1. Do the LIMIT_FALSE_FAIL and the WRONG specimens fail for the SAME REASON?")
print("   (if yes, no rule keyed on the failure reason can tell them apart)")
print("=" * 96)
reasons = {}
for kind, label, answer in SPECIMENS["q03"]:
    f = fails_of("q03", answer)
    reasons.setdefault(tuple(f), []).append((kind, label))
    print(f"  {kind:11} {label[:52]:52} -> {f or 'PASS'}")
print()
for reason, members in reasons.items():
    kinds = {k for k, _ in members}
    if len(members) > 1 and reason:
        flag = "  <-- COLLISION" if {WRONG} & kinds and {LIMIT_FALSE_FAIL} & kinds else ""
        print(f"  reason {list(reason)}{flag}")
        for k, lab in members:
            print(f"      {k:11} {lab}")

print()
print("=" * 96)
print("2. Candidate 'drop the TTB ban': what does the acceptance bar say?")
print("=" * 96)
leaked = 0
for kind, label, answer in SPECIMENS["q03"]:
    f = without_ban("q03", answer)
    verdict = "PASS" if not f else "FAIL"
    want_pass = kind in (CORRECT, LIMIT_FALSE_FAIL, LIMIT_FALSE_PASS)
    bad = (verdict == "PASS") != want_pass
    leaked += bad and kind == WRONG
    print(f"  {kind:11} {label[:52]:52} -> {verdict}"
          f"{'   <-- NOW A FALSE PASS' if bad and kind == WRONG else ''}")
for label, qid, answer, rows in FALSE_PASS_BAR:
    f = without_ban(qid, answer, rows)
    v = "PASS" if not f else "FAIL"
    leaked += v == "PASS"
    print(f"  {'BAR':11} {label[:52]:52} -> {v}"
          f"{'   <-- FALSE PASS' if v == 'PASS' else ''}")
print(f"\n  {leaked} defective answers score PASS if the ban is dropped.")

print()
print("=" * 96)
print("3. Candidate 'structural row check': is the defect ever IN the rows?")
print("=" * 96)
print("  Measured over every recorded q03 answer by q03_invariant_probe.py:")
print("    - 11 of 22 answers carry answer_rows; 10 carry NONE; 1 carries a single row")
print("    - in ALL 11, the agency row carries ZERO citations — including both FAILs")
print("    - the banned literal appears in the PROSE in both FAILs, and in the")
print("      rows in none of the 22")
print()
print("  So a rule 'no agency row may carry citations' scores every recorded")
print("  answer identically, and reads a field the defect has never occupied.")
print("  It is inert on 10 of 22 answers outright.")
