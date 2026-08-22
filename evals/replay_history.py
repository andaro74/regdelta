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

  FALSE FAIL  a recorded answer the SME seat examined individually and ruled a
            false fail (evals/admitted_false_fails.json). Reported on every
            run, counted, and not gated. See the note above `admission_for`.

FRAGILE and REGRESSED exit non-zero; IMPROVED and ADMITTED do not, the latter
unless --strict. The first two are defects a change either introduces or does
not. ADMITTED is a standing property of the question set awaiting an SME ruling
— it is true of six questions today — so gating on it would fail every PR in the
repo over someone else's open question. See the note above the return statement.

A STALE ADMISSION GATES. An entry matching no recorded answer is the register
rotting, which is the failure mode an override list has, so it fails the run
rather than being ignored.

FRAGILE WAS UNDIRECTED UNTIL 2026-08-18 and flagged any disagreement, over runs
pooled across commits. A question that failed, was fixed and now passes was
therefore a gating defect — and since history is append-only, permanently one.
q14 turned CI red that way: the crossref wiring landed between two recorded runs
and made it pass. Direction is now the whole distinction, and it is a claim
about TIME, so cards are ordered by their `at` rather than by filename.

Nothing here edits ground truth. A finding is an argument for a ruling, and
under CLAUDE.md that ruling is the SME seat's.

    python evals/replay_history.py                  # what CI runs
    python evals/replay_history.py --strict         # ADMITTED gates too
    python evals/replay_history.py --no-admissions  # the true state, unadmitted
    python evals/replay_history.py --id q05 -v
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evals import check, flatten_answer

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "evals" / "history"
GOLDEN = ROOT / "evals" / "golden_questions.json"
ADMISSIONS = ROOT / "evals" / "admitted_false_fails.json"


def scored_digest(resp: dict) -> str:
    """Digest of the exact text `check()` scores, and nothing else.

    Over `flatten_answer(resp)` rather than over `resp`, which also carries
    `cache`, `tier` and `fallback_reason` — those describe how the answer was
    obtained, not what was scored. An admission keyed on them would break when
    the same answer came back off a different tier, which is not a change in
    the artifact the seat ruled on.
    """
    return hashlib.sha256(flatten_answer(resp).encode("utf-8")).hexdigest()


def load_admissions() -> list[dict]:
    """The SME seat's per-observation false-fail rulings.

    Absent file means an empty register, not an error: a checkout without one
    should gate MORE, never less.
    """
    if not ADMISSIONS.exists():
        return []
    return json.loads(ADMISSIONS.read_text(encoding="utf-8")).get("admissions", [])


def admission_for(admissions: list[dict], qid: str, run: dict,
                  fails: list[str]) -> dict | None:
    """The register entry admitting THIS failure of THIS recorded answer, if any.

    Four things must match, and each one is load-bearing:

      question + sha   the observation the seat named
      scored_sha256    the answer itself. A different answer — including a
                       paraphrase, which is the whole difficulty with q03 —
                       has a different digest and is NOT admitted. This is
                       what keeps FRAGILE live on new non-determinism, and it
                       is the difference between this and the general admit
                       path M05 §11 refused: an entry names an artifact, not
                       a rule, so it cannot generalise to a future answer.
      admits_fails     the failure reasons, EXACTLY and in order. If the same
                       recorded answer starts failing for a different or an
                       additional reason — a token added to the golden set, a
                       new check kind — the entry does not apply and the gate
                       fires. An admission cannot silence a defect it was not
                       written for.

    Never consulted for a passing answer: the caller only asks when `fails` is
    non-empty, so this can suppress a FAIL and can never manufacture one.
    """
    for entry in admissions:
        if entry.get("question") != qid or entry.get("sha") != run["sha"]:
            continue
        if entry.get("admits_fails") != fails:
            continue
        if entry.get("scored_sha256") != scored_digest(run["resp"]):
            continue
        return entry
    return None


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
    ap.add_argument("--no-admissions", action="store_true",
                    help="ignore evals/admitted_false_fails.json and report the "
                         "unadmitted state. The audit run: what the gate would say "
                         "if no seat had ruled on anything.")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    questions = {q["id"]: q for q in
                 json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]}
    history = recorded()
    if not history:
        print("no recorded answers yet — cards carry them only from aa79ec5 onward.")
        return 0

    admissions = [] if args.no_admissions else load_admissions()
    used: list[int] = []
    examined: set[str] = set()

    fragile, improved, regressed, admitted, unseen = [], [], [], [], []
    false_fails: list[tuple[str, dict, dict]] = []
    for qid, q in questions.items():
        if args.id and qid not in args.id:
            continue
        runs = history.get(qid) or []
        if not runs:
            unseen.append(qid)
            continue
        examined.add(qid)

        verdicts = []
        for run in runs:
            fails = check(q, run["resp"])
            # THE SEAT'S RULING IS APPLIED HERE AND NOWHERE ELSE. Only after
            # check() has scored the answer, and only to a verdict that is
            # already FAIL — so the register can subtract a failure and can
            # never add or preserve a pass. run_evals.py is untouched, so
            # `make evals` still scores the answer as failing and the live
            # scorecard still says so. This is the merge gate, not the scorer.
            entry = admission_for(admissions, qid, run, fails) if fails else None
            if entry is not None:
                used.append(admissions.index(entry))
                false_fails.append((qid, run, entry))
                fails = []
            verdicts.append((run, not fails, fails, entry))

        agent = [v for v in verdicts if v[0]["mode"] != "naive"]
        control = [v for v in verdicts if v[0]["mode"] == "naive"]

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
        verdicts_in_time = [ok for _, ok, _, _ in agent]
        went_bad = any(prev and not cur
                       for prev, cur in itertools.pairwise(verdicts_in_time))
        if went_bad:
            fragile.append((qid, agent))
        elif len(set(verdicts_in_time)) > 1:
            improved.append((qid, agent))
        # An admitted observation is not REGRESSED either, and that follows
        # rather than being decided separately: the seat ruled the answer was
        # never wrong, so it did not regress against a question it still meets.
        for run, ok, fails, _ in agent:
            if run["recorded_pass"] and not ok:
                regressed.append((qid, run, fails))
        for run, ok, _, _ in control:
            if ok:
                admitted.append((qid, run))

        mark = "  "
        if any(qid == f[0] for f in fragile):
            mark = "!!"
        elif any(qid == i[0] for i in improved):
            mark = "++"
        # An admitted run prints ADMIT, never PASS. It did not pass; a seat
        # ruled its failure was not evidence of anything, and a reader
        # scanning this grid has to be able to see the difference.
        print(f" {mark} {qid}  " + " ".join(
            f"{r['sha'][:7]}:{r['mode'][:5]}="
            f"{'ADMIT' if e is not None else 'PASS' if ok else 'FAIL'}"
            for r, ok, _, e in verdicts))
        if args.verbose:
            for run, _ok, fails, entry in verdicts:
                for f in fails:
                    print(f"        {run['sha'][:7]} {run['mode']}: {f}")
                if entry is not None:
                    print(f"        {run['sha'][:7]} {run['mode']}: ADMITTED "
                          f"{entry['admits_fails']} — {entry.get('ruling')}")

    print("\n" + "-" * 74)
    for qid, runs in fragile:
        print(f"FRAGILE   {qid}: agent answers disagree across runs — "
              f"{' '.join(f'{r[0]['sha'][:7]}={'PASS' if r[1] else 'FAIL'}' for r in runs)}")
        for run, ok, fails, _ in runs:
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
    # PRINTED EVERY RUN, never folded into a count elsewhere. The register's
    # whole defence is that it is visible; a suppression a reader has to go
    # looking for is the thing M05 §11 refused.
    for qid, run, entry in false_fails:
        print(f"FALSE FAIL {qid}: the answer at {run['sha'][:7]} fails on "
              f"{entry['admits_fails'][0]!r}, and the SME seat ruled that a "
              f"false fail on {entry.get('ruled_at')}.")
        print(f"           NOT a defect this change introduced, and NOT fixed — "
              f"see {entry.get('ruling')}.")
    # STALENESS IS ONLY A CLAIM ABOUT QUESTIONS THIS RUN ACTUALLY EXAMINED.
    #
    # The first version compared `used` against the whole register, which made
    # `--id q05` report q03's entry as stale and turned the gate red on a
    # scoping flag. Two synthetic-history tests failed the same way. Neither is
    # register rot: the entry describes an observation the run never looked at.
    #
    # So an entry is judged only when its question was replayed against at
    # least one recorded answer. Everything that rot actually looks like in
    # this repo is still caught — a typo in the register, a deleted card, an
    # answer that changed, a reason that changed — because in all four q03 still
    # has runs and the entry still matches none of them.
    #
    # THE HOLE THIS LEAVES, stated rather than discovered later: if every card
    # for a question disappears, its entries are never judged. That is reported
    # below as NOT EVALUATED and deliberately does not gate, because the same
    # condition is produced by any legitimate run over a subset of history.
    stale = [e for i, e in enumerate(admissions)
             if i not in used and e.get("question") in examined]
    unevaluated = [e for i, e in enumerate(admissions)
                   if i not in used and e.get("question") not in examined]
    for entry in stale:
        print(f"STALE ADMISSION  {entry.get('question')} at {entry.get('sha')}: "
              f"matches no recorded answer failing "
              f"{entry.get('admits_fails')}. Either the card is gone, the "
              f"answer changed, or it now fails for another reason — in every "
              f"case the entry no longer describes anything and must be "
              f"re-ruled or removed.")
    for entry in unevaluated:
        print(f"NOT EVALUATED    {entry.get('question')} at {entry.get('sha')}: "
              f"no recorded answer for that question in this run, so the "
              f"admission was neither used nor judged. Reported, not gated.")
    if unseen:
        print(f"NO RECORDED ANSWER  {', '.join(sorted(unseen))} — "
              f"nothing to replay; these rest on hand-written specimens alone.")
    if not (fragile or improved or regressed or admitted or false_fails
            or stale or unevaluated):
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
    #
    # A STALE ADMISSION GATES, and that is the register paying for itself. The
    # standing objection to an override list is that it rots: entries outlive
    # the thing they described and nobody notices, so the list quietly grows
    # into a general admit path. An entry that matches nothing is that rot,
    # observable, and it can only be caused by someone editing the register or
    # the history — never by an ordinary change. So it fails the run.
    if fragile or regressed or stale:
        return 1
    if admitted and args.strict:
        return 1
    if false_fails:
        print(f"\n{len(false_fails)} FALSE FAIL(s) above are admitted by "
              f"evals/admitted_false_fails.json — each one an SME-seat ruling on "
              f"one named recorded answer, not a rule. They are REPORTED, not "
              f"gated. `--no-admissions` shows the unadmitted state.")
    if admitted:
        print(f"\n{len(admitted)} ADMITTED finding(s) above are REPORTED, not gated — "
              f"they are open SME-seat questions about the question set, not defects "
              f"in any one change. `--strict` gates on them too.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
