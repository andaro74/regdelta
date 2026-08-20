#!/usr/bin/env python
"""Score every answer ever recorded against the questions as they stand now.

`check_discrimination.py` asks whether a question can tell a hand-written right
answer from a hand-written wrong one. This asks a question the hand cannot:
**would this question have scored the answers the system actually gave?**

It exists because hand-written specimens share an author with the scoring
tokens, and therefore share their blind spots. Three times on 2026-08-15 a token
was written assuming a phrasing the model did not use — q18 wrote "are affected"
where the model wrote "is affected"; q05 wrote "contain a food group" where the
model wrote "contain A SPECIFIED AMOUNT OF a food group". Every one of those
passed the discrimination harness, because the specimens were written by whoever
wrote the tokens. Recorded answers are the one source of phrasings the author
did not choose, and since `aa79ec5` every scorecard carries them.

What it reports, and why each matters:

  FRAGILE   an agent answer that PASSED earlier FAILS later. The question is
            passing on the wording of the day rather than on the content, which
            is how q05 passed at 2cea737 and failed at e26d8ef with identical
            tokens.
  IMPROVED  the reverse direction: fails earlier, passes later, never back. A
            question the repo repaired. Reported, never gated — see below.
  REGRESSED an agent answer that passed when recorded now fails. Either a
            question was tightened past a correct answer, or the answer was
            never as good as its pass suggested.
  ADMITTED  a NAIVE control answer now passes. The control is the frozen
            baseline (ADR-0002); a question it can satisfy is measuring less
            than it claims.

FRAGILE and REGRESSED exit non-zero; IMPROVED and ADMITTED do not, the latter
unless --strict. The first two are defects a change either introduces or does
not. ADMITTED is a standing property of the question set awaiting an SME ruling
— it is true of six questions today — so gating on it would fail every PR in the
repo over someone else's open question. See the note above the return statement.

FRAGILE WAS UNDIRECTED UNTIL 2026-08-18 and flagged any disagreement, over runs
pooled across commits. A question that failed, was fixed and now passes was
therefore a gating defect — and since history is append-only, permanently one.
q14 turned CI red that way: the crossref wiring landed between two recorded runs
and made it pass. Direction is now the whole distinction, and it is a claim
about TIME, so cards are ordered by their `at` rather than by filename.

Nothing here edits ground truth. A finding is an argument for a ruling, and
under CLAUDE.md that ruling is the SME seat's.

    python evals/replay_history.py            # what CI runs
    python evals/replay_history.py --strict   # ADMITTED gates too
    python evals/replay_history.py --id q05 -v
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evals import check

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "evals" / "history"
GOLDEN = ROOT / "evals" / "golden_questions.json"


def recorded() -> dict[str, list[dict]]:
    """Every recorded answer, keyed by question id, oldest card first.

    Cards written before the answer-recording change carry no `response` and
    are skipped rather than counted as empty answers — an absent answer is not
    a blank one, and treating it as blank would invent failures.

    OLDEST FIRST MEANS BY `at`, NOT BY FILENAME. This docstring said "oldest
    card first" while sorting `HISTORY.glob("*.json")`, which orders
    alphabetically by the sha in the name: 2cea737 sorts before 42e9010 and was
    recorded fifteen hours later. Nothing depended on the order while FRAGILE
    compared a SET of verdicts — the direction of a change is what needs it, and
    that is what the finding below now reads.

    `at` has been on every card since the first one. Cards without it fall back
    to the filename so an old or hand-written card still sorts somewhere
    deterministic rather than crashing the run.
    """
    def when(path: Path) -> tuple[str, str]:
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return ("", path.name)
        return (str(card.get("at") or ""), path.name)

    out: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(HISTORY.glob("*.json"), key=when):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "questions" not in card:
            continue                       # retrieval card, different shape
        for q in card["questions"]:
            resp = q.get("response") or {}
            if not (resp.get("answer") or resp.get("answer_rows")):
                continue
            out[q["id"]].append({
                "sha": card.get("sha", path.stem.split("-")[0]),
                "at": card.get("at") or "",
                "mode": card.get("mode", "?"),
                "recorded_pass": q.get("pass"),
                "resp": resp,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", action="append", help="only these question ids")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the scorer's reasons")
    ap.add_argument("--strict", action="store_true",
                    help="also fail on ADMITTED (a naive-control answer passing). "
                         "Off by default: that is a standing SME-seat question about "
                         "the question set, not a defect a given change introduced.")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    questions = {q["id"]: q for q in
                 json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]}
    history = recorded()
    if not history:
        print("no recorded answers yet — cards carry them only from aa79ec5 onward.")
        return 0

    fragile, improved, regressed, admitted, unseen = [], [], [], [], []
    for qid, q in questions.items():
        if args.id and qid not in args.id:
            continue
        runs = history.get(qid) or []
        if not runs:
            unseen.append(qid)
            continue

        verdicts = []
        for run in runs:
            fails = check(q, run["resp"])
            verdicts.append((run, not fails, fails))

        agent = [(r, ok, f) for r, ok, f in verdicts if r["mode"] != "naive"]
        control = [(r, ok, f) for r, ok, f in verdicts if r["mode"] == "naive"]

        # DIRECTIONAL, and that is a ruling, not a refinement.
        #
        # This was `len({ok for ...}) > 1` — any disagreement at all, over runs
        # POOLED ACROSS COMMITS. So a question that failed, was fixed, and now
        # passes reported as a defect, and history is append-only: the pre-fix
        # cards never age out, so the gate stayed red forever on a question the
        # repo had already repaired. That is a standing tax on every future fix,
        # and it fired for real — q14 turned CI red because the crossref wiring
        # landed between two runs and made it pass (sme-eval-triage, 2026-08-18,
        # classed (a) SYSTEM for the two failures; the question stands and was
        # not touched).
        #
        # What survives is the half that is a defect: a verdict that went
        # pass -> fail somewhere in recorded time. What the tool cannot see is
        # WHY, so it still cannot separate flakiness from a code change — it now
        # separates the two DIRECTIONS, and only one of them is bad news.
        # fail -> pass is reported as IMPROVED so a reader still sees the
        # question changed verdict, which is the signal that caught q05.
        #
        # Ordering is by `at`, so "went pass -> fail" is a claim about time.
        # See recorded(): it used to sort by filename, i.e. by sha.
        verdicts_in_time = [ok for _, ok, _ in agent]
        went_bad = any(prev and not cur
                       for prev, cur in itertools.pairwise(verdicts_in_time))
        if went_bad:
            fragile.append((qid, agent))
        elif len(set(verdicts_in_time)) > 1:
            improved.append((qid, agent))
        for run, ok, fails in agent:
            if run["recorded_pass"] and not ok:
                regressed.append((qid, run, fails))
        for run, ok, _ in control:
            if ok:
                admitted.append((qid, run))

        mark = "  "
        if any(qid == f[0] for f in fragile):
            mark = "!!"
        elif any(qid == i[0] for i in improved):
            mark = "++"
        print(f" {mark} {qid}  " + " ".join(
            f"{r['sha'][:7]}:{r['mode'][:5]}={'PASS' if ok else 'FAIL'}"
            for r, ok, _ in verdicts))
        if args.verbose:
            for run, _ok, fails in verdicts:
                for f in fails:
                    print(f"        {run['sha'][:7]} {run['mode']}: {f}")

    print("\n" + "-" * 74)
    for qid, runs in fragile:
        print(f"FRAGILE   {qid}: agent answers disagree across runs — "
              f"{' '.join(f'{r[0]['sha'][:7]}={'PASS' if r[1] else 'FAIL'}' for r in runs)}")
        for run, ok, fails in runs:
            if not ok:
                print(f"          {run['sha'][:7]} failed on: {fails[0]}")
    for qid, runs in improved:
        print(f"IMPROVED  {qid}: fails earlier, passes later, never the other "
              f"way — {' '.join(f'{r[0]['sha'][:7]}={'PASS' if r[1] else 'FAIL'}' for r in runs)}")
        print("          REPORTED, not gated: the question changed verdict, and "
              "the direction is the one you want.")
    for qid, run, fails in regressed:
        print(f"REGRESSED {qid}: passed at {run['sha'][:7]}, fails against the "
              f"question as it stands now — {fails[0]}")
    for qid, run in admitted:
        print(f"ADMITTED  {qid}: the NAIVE control's answer at {run['sha'][:7]} "
              f"passes. ADR-0002 makes that a question worth re-reading.")
    if unseen:
        print(f"NO RECORDED ANSWER  {', '.join(sorted(unseen))} — "
              f"nothing to replay; these rest on hand-written specimens alone.")
    if not (fragile or improved or regressed or admitted):
        print("No question changes its verdict across the answers on file.")

    # WHAT GATES AND WHAT ONLY REPORTS.
    #
    # FRAGILE and REGRESSED are defects in the instrument, and a commit either
    # introduces one or does not — so they gate.
    #
    # ADMITTED is not that. "The naive control's own answer satisfies this
    # question" is a STANDING CONDITION of the question set, owned by the SME
    # seat under CLAUDE.md, and it is true today of six questions including four
    # trap-tagged ones. Gating on it would fail every PR in the repo until a
    # ruling lands, on a finding that PR did not cause and its author cannot
    # fix — denial of merge on someone else's open question.
    #
    # Found by running this in CI conditions rather than by reasoning about it:
    # the first version returned 1 for all three, which would have turned the
    # branch red on the commit that added it.
    if fragile or regressed:
        return 1
    if admitted and args.strict:
        return 1
    if admitted:
        print(f"\n{len(admitted)} ADMITTED finding(s) above are REPORTED, not gated — "
              f"they are open SME-seat questions about the question set, not defects "
              f"in any one change. `--strict` gates on them too.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
