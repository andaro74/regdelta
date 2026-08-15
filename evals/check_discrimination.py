#!/usr/bin/env python
"""Can each golden question tell a right answer from a wrong one?

`make evals` measures the SYSTEM. This measures the INSTRUMENT. It never calls
the API: it replays run_evals.check() — the real scorer, imported, not
reimplemented — against hand-written answers, and requires

    a correct answer   -> PASS
    a wrong answer     -> FAIL

A question that fails this is worse than a question that fails an eval, because
it fails silently. q07 scored a stable 0/3 for three recorded commits while
measuring nothing at all: its accept token matched a wrong answer and its
required token matched nothing a right answer would say. That is the fourth
defect class in the 2026-08-12 SME ruling, and it is invisible to inspection —
you cannot see it by reading the question, only by running answers through it.

HOW TO WRITE SPECIMENS, which is the whole difficulty:

    The specimens must be adversarial to the SCORING TOKENS, not illustrative
    of the answer.

The 2026-08-15 ruling exists because this was got wrong. Ten questions were
drafted and checked by the same seat, all ten passed, and a later adversarial
pass found defects in all ten — five false passes and five false fails. The
harness was sound; the specimens were not. Whoever wrote the bans wrote the
wrong answers in the phrasings those bans anticipated, so the test confirmed
the author's expectations instead of testing them. When adding a question:

  * write the wrong answer that is CLOSEST to right — the swapped date, the
    negated carve-out, the true-but-ungrounded hedge — not an obviously silly one;
  * write the correct answer in the phrasing you would NOT have chosen, and
    especially the one that has to restate the stem's false premise to deny it;
  * for every accept token, ask whether it is a substring of its own negation
    ('affected' is inside 'not affected'); for every ban, ask whether a correct
    refutation reproduces it ('not published on January 15, 2025').

Specimens marked LIMIT_FALSE_PASS / LIMIT_FALSE_FAIL record a defect accepted
deliberately rather than one nobody noticed: a wrong answer that still scores
PASS, or a correct answer that still scores FAIL. They assert TODAY's behaviour,
so the run fails if one starts behaving — the limitation is then gone and the
note documenting it in the question has become a lie. The direction has to be
declared, because the two kinds score in opposite directions and a single
"expected to misbehave" marker cannot tell them apart.

Usage:
    python evals/check_discrimination.py                    # live golden set
    python evals/check_discrimination.py --file evals/proposed/golden_questions_q11_q20.json
    python evals/check_discrimination.py --id q14 -v
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evals import check

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SET = ROOT / "evals" / "golden_questions.json"

# Citations are supplied generously on purpose: must_cite_any is not what this
# harness is testing, and a specimen failing on a missing citation would mask
# the token defect it was written to expose.
CITES = ["90 FR 4628", "2025-00830", "21 CFR 74.303", "91 FR 50475", "2026-15920",
         "89 FR 106064", "2024-29957", "90 FR 10592", "2025-03118",
         "21 CFR 101.65", "21 CFR 101.13"]

CORRECT, WRONG = "correct", "wrong"
LIMIT_FALSE_PASS = "limit-pass"   # a WRONG answer that scores PASS today, knowingly
LIMIT_FALSE_FAIL = "limit-fail"   # a CORRECT answer that scores FAIL today, knowingly
LIMITS = (LIMIT_FALSE_PASS, LIMIT_FALSE_FAIL)

# ---------------------------------------------------------------------------
# Specimens. (kind, label, answer[, status])
# ---------------------------------------------------------------------------
SPECIMENS: dict[str, list[tuple]] = {

    # ---------------- the live set, q01-q10 --------------------------------
    # Never discrimination-checked before 2026-08-15. Two of these ten had
    # already been ruled on after failing at the keyboard (q02, q08) and one
    # after failing to measure anything at all (q07).

    "q01": [
        (CORRECT, "no, only the effective date moved", (
            "No. The effective date was delayed to April 28, 2025, but the compliance "
            "deadline remains February 25, 2028 (89 FR 106064).")),
        (CORRECT, "phrased around the negated verb", (
            "The compliance deadline did not change. It is February 25, 2028; it was the "
            "effective date that was delayed, not the compliance date (2024-29957).")),
        (WRONG, "says YES, then names the right date", (
            "Yes — the compliance deadline changed when the effective date was pushed back. "
            "It is now February 25, 2028, and it remains there (89 FR 106064).")),
        (WRONG, "conflates the two dates outright", (
            "Both dates shifted together. Compliance is now due February 25, 2028, which "
            "remains the operative date (89 FR 106064).")),
    ],

    "q02": [
        (CORRECT, "safe harbour for product already made", (
            "You must stop using FD&C Red No. 3 by January 15, 2027 (21 CFR 74.303, "
            "90 FR 4628). Product manufactured before that date with certified colour will "
            "not be regarded as adulterated merely because it is still on shelves.")),
        (WRONG, "inverts the grandfather clause", (
            "You must stop by January 15, 2027. Product manufactured after that date using "
            "certified Red No. 3 will not be regarded as adulterated (21 CFR 74.303).")),
        (WRONG, "asserts a recall in fresh vocabulary", (
            "Stop by January 15, 2027. Any certified product still on shelves after that "
            "date must be withdrawn from sale and cannot lawfully be sold.")),
    ],

    "q03": [
        (CORRECT, "declines the unsourced obligation", (
            "You must stop using Red No. 3 by January 15, 2027 (90 FR 4628). As for the "
            "formula on file with another agency, I cannot confirm any further obligation "
            "from my sources — verify with that agency directly.")),
        (WRONG, "no hedge at all; 'not in' matches incidentally", (
            "You must stop using Red No. 3 by January 15, 2027. There is nothing else to "
            "do: after that date the colour is not in the list of approved additives "
            "(90 FR 4628).")),
        (WRONG, "asserts the TTB obligation in fresh words", (
            "Stop by January 15, 2027. You will also need to file a new formula with the "
            "Alcohol and Tobacco Tax and Trade Bureau before shipping the reformulated "
            "mixer, which is outside the scope of the FDA order.")),
    ],

    "q04": [
        (CORRECT, "distinguishes request from rule", (
            "No. The HHS statement is a request, not a rule; it is not binding. Your legal "
            "deadline remains January 15, 2027 under 21 CFR 74.303.")),
        (WRONG, "treats the request as binding", (
            "Yes — you should comply with the HHS request and phase out early. The "
            "regulatory backstop is January 15, 2027.")),
        (WRONG, "hedges the wrong way", (
            "HHS has requested an earlier phase-out and FDA supports it, so plan to meet "
            "that timetable rather than January 15, 2027.")),
    ],

    "q05": [
        (CORRECT, "both criteria", (
            "Two things. The food must contain a meaningful amount of a food group "
            "equivalent, and it must stay within limits for added sugars, sodium and "
            "saturated fat (21 CFR 101.65).")),
        (WRONG, "states both criteria INVERTED", (
            "A food qualifies if it contains no food group equivalent and exceeds the "
            "thresholds for added sugars, sodium and saturated fat (21 CFR 101.65).")),
        (WRONG, "fabricates a front-of-package requirement", (
            "The updated rule requires front-of-package disclosure of added sugars and "
            "sodium, plus a statement of the food group equivalent it contains "
            "(21 CFR 101.65).")),
    ],

    "q06": [
        (CORRECT, "names the section", (
            "21 CFR 101.65 governs the implied nutrient content claim 'healthy'.")),
        (WRONG, "names the wrong section, mentions the right one", (
            "It is governed by 21 CFR 101.13; 101.65 was the old section and no longer "
            "applies.")),
    ],

    "q07": [
        (CORRECT, "no size-based extension", (
            "Your compliance date is February 25, 2028. The rule provides no extension "
            "based on company size; the date applies to all manufacturers "
            "(89 FR 106064).")),
        (WRONG, "grants the extension, avoids the year 2029", (
            "As a smaller manufacturer you get an extra year beyond February 25, 2028 to "
            "come into compliance (89 FR 106064).")),
        (WRONG, "grants the extension while conceding the rule applies to all", (
            "The rule applies to all manufacturers, but smaller ones such as you get an "
            "additional year past February 25, 2028 (89 FR 106064).")),
        (WRONG, "names the fabricated tier year", (
            "With $8M in sales you fall under the small-business provision, so your date "
            "is February 25, 2029 rather than February 25, 2028.")),
    ],

    "q08": [
        (CORRECT, "three dates, no compliance date stated", (
            "Published January 16, 2025. Effective January 15, 2027 for food. The order "
            "sets no compliance date; the effective date is the operative deadline.")),
        (WRONG, "invents a food compliance date", (
            "Published January 16, 2025, effective January 15, 2027. No compliance date is "
            "stated in the order, but FDA expects compliance by January 18, 2028.")),
        (WRONG, "applies the drug date to food", (
            "Published January 16, 2025. Effective January 15, 2027, though "
            "January 18, 2028 applies to food in practice. No compliance date is set.")),
        (LIMIT_FALSE_FAIL, "correctly explains what January 15, 2025 was", (
            "FDA announced the revocation on January 15, 2025, but Federal Register "
            "publication was January 16, 2025. Effective January 15, 2027 for food; no "
            "compliance date is stated.")),
    ],

    "q09": [
        (CORRECT, "human food only", (
            "No. The 'healthy' claim rule applies to human food and does not apply to pet "
            "food, so your dog treat line is not covered.")),
        (WRONG, "applies it to dog treats; 'outside' matches incidentally", (
            "Yes, the rule reaches your dog treats. Reformulate them to meet the food "
            "group requirement — anything outside those criteria cannot bear the claim.")),
        (WRONG, "applies it via the phrase 'human food'", (
            "Dog treats are regulated on the same basis as human food, so the updated "
            "criteria apply to your line and you should plan to reformulate.")),
    ],

    "q10": [
        (CORRECT, "gate fires, nothing asserted", (
            "I need to know what product you make and what claims its label bears before I "
            "can tell you whether the healthy-claim changes reach you.", "needs_input")),
        (WRONG, "answers confidently without a profile", (
            "Yes, the healthy-claim changes affect you. You must comply by "
            "February 25, 2028.", "ok")),
        (LIMIT_FALSE_PASS, "gate fires but the answer asserts a deadline anyway", (
            "I need more detail about your products. Your compliance date is "
            "February 25, 2028.", "pending_review")),
    ],

    # ---------------- the proposed set, q11-q20 ----------------------------

    "q11": [
        (CORRECT, "denies via the stem's own verb", (
            "You work to January 15, 2027. The suspension did not change it. The order at "
            "90 FR 4628 was stayed under 21 U.S.C. 371(e)(2), and 91 FR 50475 lifted the stay "
            "and confirmed both dates. A stay suspends; it does not toll, so no document "
            "extended the deadline.")),
        (CORRECT, "negation-only phrasing, no 'unchanged'", (
            "The deadline was not extended by the stay. It is still January 15, 2027, "
            "confirmed by 91 FR 50475 when the stay was lifted (90 FR 4628).")),
        (WRONG, "tolling, states a new date", (
            "The stay ran about 17 months, so your new compliance date is roughly July 2028, "
            "pushed from January 15, 2027. 91 FR 50475 confirmed the stay was lifted.")),
        (WRONG, "tolling, avoids every banned verb", (
            "Because the order was suspended for about 18 months, the January 15, 2027 date "
            "shifted accordingly to mid-2028. 91 FR 50475 lifted the stay.")),
        (WRONG, "right date, unaware a stay ever existed", (
            "Your deadline is January 15, 2027 and nothing has changed it.")),
        (WRONG, "'confirmed' about the stay, not the dates", (
            "The order was suspended and 91 FR 50475 confirmed the suspension, so your "
            "deadline moved out to July 2028 from January 15, 2027.")),
    ],

    "q12": [
        (CORRECT, "holds both time-indexed states", (
            "It was fair at the time. The order was stayed from February 18, 2025 under "
            "371(e)(2), so the provision had no legal effect and might never have taken "
            "effect. That is no longer the position: the stay was lifted August 5, 2026 "
            "(91 FR 50475) and both dates were confirmed, so compliance is due "
            "January 15, 2027.")),
        (CORRECT, "says 'never took effect' of the stay period", (
            "That was a fair reading then — during the stay the rule never took effect and "
            "could have been withdrawn. Stayed February 18, 2025; lifted August 5, 2026; the "
            "removal is now in force with compliance by January 15, 2027.")),
        (WRONG, "denies the 'fair then' half", (
            "That was never a fair reading; the order was always final. It was stayed "
            "February 18, 2025, lifted August 5, 2026, and compliance is January 15, 2027.")),
        (WRONG, "still stayed", (
            "It was fair at the time and it still is: the order remains stayed. Stay began "
            "February 18, 2025, review was due August 5, 2026, compliance January 15, 2027.")),
        (WRONG, "no point-in-time reasoning at all", (
            "The removal is in force and compliance is due January 15, 2027. The stay ran "
            "February 18, 2025 to August 5, 2026.")),
    ],

    "q13": [
        (CORRECT, "'do not share the same effective date'", (
            "It removes 21 CFR 74.303, the food and ingested-drug listing, effective "
            "January 15, 2027, and separately removes 74.1303 effective January 18, 2028. "
            "They do not share the same effective date.")),
        (CORRECT, "terse 'not all on the same day'", (
            "Two provisions are removed and not all on the same day: 74.303 on "
            "January 15, 2027 and 74.1303 on January 18, 2028.")),
        (WRONG, "collapses both to the food date", (
            "The order removes 74.303 and 74.1303, both effective January 15, 2027.")),
        (WRONG, "swaps food and drug provisions", (
            "It removes two listings. 74.1303 applies to food and is revoked "
            "January 15, 2027; 74.303 is the ingested-drug listing, revoked "
            "January 18, 2028.")),
        (WRONG, "food date only, drug provision dropped", (
            "It removes 74.303, the colour additive listing for food, effective "
            "January 15, 2027.")),
    ],

    "q14": [
        (CORRECT, "states the carve-out", (
            "A 'healthy' claim must also satisfy the general requirements for nutrient "
            "content claims in 21 CFR 101.13, with the exception of 101.13(h) when the claim "
            "is made in accordance with 101.65(d).")),
        (CORRECT, "never names 101.65", (
            "It must meet 21 CFR 101.13. One part does not apply: 101.13(h) is excluded for "
            "claims made under paragraph (d).")),
        (WRONG, "the exact negation — 'nothing is carved out'", (
            "All the general requirements of 101.13 apply to a healthy claim, including "
            "101.13(h). Nothing is carved out.")),
        (WRONG, "negation via 'not carved out'", (
            "A healthy claim must comply with 21 CFR 101.13 in its entirety; 101.13(h) is "
            "not carved out.")),
        (WRONG, "negation via the other accept token", (
            "21 CFR 101.13 governs healthy claims and nothing is excluded, 101.13(h) "
            "included.")),
        (WRONG, "asserts full application, no carve vocabulary", (
            "A healthy claim must meet 21 CFR 101.13 in full — every paragraph, "
            "101.13(h) among them.")),
    ],

    "q15": [
        (CORRECT, "two rows, correctly attributed", (
            "Two changes. First, reformulate to remove FD&C Red No. 3: the colour additive "
            "listing at 74.303 is revoked and the deadline is January 15, 2027 (90 FR 4628). "
            "Second, either meet the revised 'healthy' criteria in 21 CFR 101.65 or drop the "
            "claim, by February 25, 2028 (89 FR 106064).")),
        (WRONG, "collapses to one deadline", (
            "You must reformulate and relabel. A single deadline of February 25, 2028 "
            "applies to both changes (89 FR 106064, 90 FR 4628).")),
        (WRONG, "swaps the deadlines between the rules", (
            "Remove Red No. 3 by February 25, 2028 (90 FR 4628), and meet the healthy "
            "criteria by January 15, 2027 (89 FR 106064).")),
        (LIMIT_FALSE_PASS, "swap phrased without the banned adjacency", (
            "The colour additive change is due February 25, 2028 under 90 FR 4628. The "
            "'healthy' labeling change is due January 15, 2027 under 89 FR 106064.")),
    ],

    "q16": [
        (CORRECT, "grounded: 'only in passing', no requirement", (
            "My sources do not cover front-of-package nutrition labeling as a requirement. "
            "The documents I have discuss it only in passing, in the preamble to the "
            "'healthy' rule, and they establish no requirement and no date.")),
        (CORRECT, "flat refusal naming the absent rule", (
            "I cannot confirm that from my sources. The front-of-package proposed rule "
            "(90 FR 5426) is not among the documents I searched.")),
        (WRONG, "fabricates a requirement and a date", (
            "Yes — you must add a front-of-package nutrition summary, and you must comply by "
            "January 1, 2028.")),
        (WRONG, "priors, hedged: 'you do not have to'", (
            "No, you do not have to add a front-of-package nutrition summary at this time. "
            "FDA has only proposed one.")),
        (WRONG, "true in the world, ungrounded in the corpus", (
            "There is no current requirement. FDA proposed one at 90 FR 5426 but it is not "
            "final, so nothing is required of you yet.")),
    ],

    "q17": [
        (CORRECT, "attributes the delay to the effective date", (
            "Published December 27, 2024 (89 FR 106064). The effective date was delayed to "
            "April 28, 2025 by 90 FR 10592. The compliance date is February 25, 2028 and "
            "remains unchanged.")),
        (CORRECT, "terse, uses 'not delayed'", (
            "Publication December 27, 2024 (89 FR 106064); effective April 28, 2025 after a "
            "delay (90 FR 10592, 2025-03118); compliance February 25, 2028, not delayed.")),
        (WRONG, "bare participle evades 'was delayed'", (
            "Published December 27, 2024 (89 FR 106064). The compliance date delayed to "
            "February 25, 2028 by 90 FR 10592, and the effective date is April 28, 2025.")),
        (WRONG, "swaps effective and compliance", (
            "Published December 27, 2024. The effective date is February 25, 2028 and the "
            "compliance date is April 28, 2025 (89 FR 106064, 90 FR 10592), unchanged since.")),
        (WRONG, "omits the second document entirely", (
            "Published December 27, 2024, effective April 28, 2025, compliance "
            "February 25, 2028 (89 FR 106064). Nothing changed after publication.")),
    ],

    "q18": [
        (CORRECT, "affirms applicability", (
            "Yes, you are affected. A shelf-stable lentil soup bearing a 'healthy' claim must "
            "meet the revised criteria in 21 CFR 101.65 by February 25, 2028 (89 FR 106064).",
            "ok")),
        (CORRECT, "phrased as 'applies to you'", (
            "The revised healthy-claim rule applies to you, because the label bears the "
            "claim. Compliance is due February 25, 2028 (89 FR 106064).", "ok")),
        (WRONG, "denies applicability — the substring trap", (
            "You are not affected by the healthy-claim changes. For manufacturers who are, "
            "the compliance date is February 25, 2028.", "ok")),
        (WRONG, "gate fires when it should not", (
            "I need more information about your company before I can answer. Yes, you are "
            "affected, and the compliance date is February 25, 2028.", "pending_review")),
        (WRONG, "demands a revenue figure", (
            "You are affected, but I cannot determine your deadline without your annual food "
            "sales. The date for large manufacturers is February 25, 2028.", "needs_input")),
    ],

    "q19": [
        (CORRECT, "concedes the true half, refutes the inference", (
            "They are right that the order sets no compliance date, but they are wrong that "
            "there is no hard deadline. The effective date is January 15, 2027; from that "
            "date 74.303 is revoked, Red No. 3 is no longer listed for use in food, and any "
            "food bearing it is adulterated.")),
        (CORRECT, "derives without quoting the supplier", (
            "Only partly. The order states an effective date and no compliance date, but the "
            "effective date is the operative deadline: on January 15, 2027 the listing is "
            "revoked and product containing the colour becomes unlawful to ship.")),
        (WRONG, "endorses the inference", (
            "Correct — the order sets no compliance date, so there is no deadline. You may "
            "continue using Red No. 3 after January 15, 2027 until your stock runs out.")),
        (WRONG, "agrees without the banned phrasing", (
            "They're right. The order gives only an effective date of January 15, 2027, and "
            "effective dates bind the agency rather than regulated industry.")),
        (LIMIT_FALSE_FAIL, "quotes the full inference in order to reject it", (
            "Your supplier's position is that the order sets no compliance date, so there is "
            "no hard deadline. The first half is right and the second is wrong: on "
            "January 15, 2027 the listing is revoked and the food is adulterated.")),
    ],

    "q20": [
        (CORRECT, "negates the anchor", (
            "It was not published on January 15, 2025 — that was the date FDA announced the "
            "revocation. The Federal Register publication date is January 16, 2025 "
            "(90 FR 4628).")),
        (CORRECT, "corrects the memo directly", (
            "Your memo is incorrect. January 15, 2025 is the announcement date; publication "
            "in the Federal Register was January 16, 2025.")),
        (WRONG, "accepts the anchor", (
            "That is right — it was published on January 15, 2025, at 90 FR 4628.")),
        (WRONG, "accepts the anchor while naming the 16th", (
            "The publication date is January 15, 2025. The rule appears at 90 FR 4628 and "
            "takes effect January 16, 2025.")),
    ],
}


def score(q: dict, answer: str, status: str = "ok") -> list[str]:
    return check(q, {"answer": answer, "citations": CITES, "status": status})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=str(DEFAULT_SET), help="question set to check")
    ap.add_argument("--id", action="append", help="check only these ids (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show scorer reasons on pass too")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):          # cp1252 consoles, as run_evals does
        sys.stdout.reconfigure(encoding="utf-8")

    questions = {q["id"]: q for q in json.loads(
        Path(args.file).read_text(encoding="utf-8"))["questions"]}

    ids = args.id or sorted(SPECIMENS)
    unknown = [i for i in ids if i not in questions]
    uncovered = sorted(i for i in questions if i not in SPECIMENS and (not args.id or i in ids))

    bad = 0
    limits = 0
    checked = 0
    for qid in ids:
        if qid not in questions or qid not in SPECIMENS:
            continue
        q = questions[qid]
        print(f"\n{qid}  {q['question'][:88]}")
        for spec in SPECIMENS[qid]:
            kind, label, payload = spec[0], spec[1], spec[2]
            answer, status = payload if isinstance(payload, tuple) else (payload, "ok")
            fails = score(q, answer, status)
            got = "FAIL" if fails else "PASS"
            want = "PASS" if kind is CORRECT else "FAIL"
            checked += 1

            if kind in LIMITS:
                # A documented defect asserts TODAY's behaviour. If it stops
                # misbehaving the question got better and its note went stale.
                limits += 1
                known = "PASS" if kind == LIMIT_FALSE_PASS else "FAIL"
                if got == known:
                    print(f"  [~] {label:52s} scores {got} — known limitation, documented "
                          f"in the question's note")
                else:
                    bad += 1
                    print(f"  !! {label:52s} scores {got}, documented as {known}")
                    print("        the limitation is GONE — remove it from the question's "
                          "note, which now overstates the defect")
                continue

            ok = got == want
            bad += not ok
            flag = "   " if ok else "!! "
            print(f"  {flag}{label:52s} want={want} got={got}"
                  f"{'' if ok else ('  <-- FALSE ' + ('PASS' if got == 'PASS' else 'FAIL'))}")
            if fails and (args.verbose or (not ok and got == "FAIL")):
                for f in fails:
                    print(f"        {f}")

    print(f"\n{'-' * 72}")
    print(f"{checked} specimens over {len([i for i in ids if i in SPECIMENS and i in questions])} "
          f"questions · {limits} documented limitations")
    if unknown:
        print(f"NOT IN THIS SET: {', '.join(unknown)}")
    if uncovered:
        print(f"NO SPECIMENS (never discrimination-checked): {', '.join(uncovered)}")
    if bad:
        print(f"FAILED: {bad} specimen(s) scored the wrong way. "
              f"The question cannot distinguish right from wrong.")
        return 1
    if not checked:
        # Green on zero coverage is the exact failure this harness exists to
        # catch, so it must not be reported as a pass.
        print("NOTHING WAS CHECKED — no specimens exist for any question in this set.")
        return 1
    print("OK — every question distinguishes a correct answer from a wrong one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
