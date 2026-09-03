#!/usr/bin/env python
"""Mechanically validate the q11 + q18 token proposal. No API, no cost.

The q12 precedent's rule: "a hand-simulated token is not a ruled token." Four
questions this answers per question, each of which overturned some hand-read at
a previous triage:

  1. Does any PROPOSED accept token pass inside its own negation? The
     2026-08-22 q12 ruling found six of nine tokens leaking in a ruling that
     had explicitly claimed none did.
  2. Does the OBSERVED live answer go from FAIL to PASS?
  3. Does any discrimination specimen change verdict — i.e. does the proposal
     admit a WRONG answer or reject a CORRECT one?
  4. Do the proposed negation BANS fire on any correct answer? A ban a correct
     answer reproduces is a defect, not a guard (q12 ruling, rule 5).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from check_discrimination import CORRECT, SPECIMENS  # noqa: E402
from run_evals import check  # noqa: E402

GOLDEN = json.loads((ROOT / "evals" / "golden_questions.json").read_text(encoding="utf-8"))

#: What the DEPLOYED system actually said. q18: three consecutive probe runs
#: 2026-09-03 plus the CI run on PR #29, all four opening identically. q11: the
#: CI run on PR #29, recovered from the scorecard artifact that PR added.
#: Transcribed, not imagined.
OBSERVED = {
    "q18": ("Yes, your shelf-stable lentil soup labeled 'healthy' is directly affected "
            "by the updated definition of the term 'healthy' under the final rule "
            "published at 89 FR 106064 (Doc. 2024-29957, published 2024-12-27). This "
            "rule revises 21 CFR 101.65(d) to replace the old nutrient-threshold-based "
            "criteria with new food-group-equivalent (FGE) and nutrient-to-limit (NTL) "
            "requirements. The compliance date remains February 25, 2028."),
    # TRUNCATED AT 420 CHARS, AND THE TRUNCATION IS LOAD-BEARING. This is
    # exactly what the scorecard artifact holds and no more. An earlier version
    # of this file extrapolated the tail and wrote in "confirmed both dates" —
    # an ACCEPT TOKEN — which made the probe report `before: PASS` for an answer
    # CI had failed. A ruling resting on text the system never emitted is the
    # failure this whole mechanism exists to prevent, so the string stops where
    # the evidence stops.
    #
    # The full answer was 1,780 characters. `must_contain_any` group 2
    # (91 FR 50475 / 2026-15920) passed live and passes here through the
    # citations, which `flatten_answer` appends to the scored text.
    "q11": ("Your colleague is incorrect that the deadline moved. Here is what happened: "
            "1. **Original order (90 FR 4628, published 2025-01-16, doc 2025-00830):** "
            "FDA revoked the color additive listings for FD&C Red No. 3. The order set "
            "two effective dates: **January 15, 2027** for food uses (removal of 21 CFR "
            "74.303) and **January 18, 2028** for ingested drug uses (removal of 21 CFR "
            "74.1303). The order set no separate compliance"),
}
CITATIONS = {"q18": ["89 FR 106064", "90 FR 10592"],
             "q11": ["90 FR 4628", "91 FR 50475", "21 CFR 74.303"]}

PROPOSED_ACCEPT = {"q18": ["is directly affected"],
                   "q11": ["colleague is incorrect"]}

#: The compensating tightening. Today both questions catch a flat denial only by
#: the ABSENCE of an accept token, which is why q18's signature was ambiguous
#: enough to need three live Bedrock calls to diagnose.
PROPOSED_BANS = {
    "q18": ["is not affected", "are not affected", "is not directly affected",
            "does not apply to your"],
    "q11": ["colleague is correct", "colleague is right", "the deadline did move"],
}

#: Negations written out rather than generated, because a generated negation is
#: another hand-read.
NEGATIONS = {
    "you are affected": "you are not affected",
    "are affected": "are not affected",
    "it applies to your": "it does not apply to your",
    "applies to your": "does not apply to your",
    "does apply to your": "does not apply to your",
    "the rule applies to you": "the rule does not apply to you",
    "applies to you": "does not apply to you",
    "yes, it applies": "no, it does not apply",
    "yes, the rule applies": "no, the rule does not apply",
    "is affected": "is not affected",
    "is directly affected": "is not directly affected",
    "did not change": "did change",
    "unchanged": "changed",
    "not change": "change",
    "no change": "a change",
    "did not move": "did move",
    "not extended": "extended",
    "did not extend": "did extend",
    "no extension": "an extension",
    "still january 15, 2027": "no longer january 15, 2027",
    "remains january 15, 2027": "no longer january 15, 2027",
    "colleague is incorrect": "colleague is correct",
}


def _payload(spec):
    """q18 specimens carry (answer, status); q11 specimens carry a bare answer."""
    body = spec[2]
    return body if isinstance(body, tuple) else (body, "ok")


def run(qid: str) -> int:
    q = next(x for x in GOLDEN["questions"] if x["id"] == qid)
    after = json.loads(json.dumps(q))
    after["must_contain_any"][0] = list(q["must_contain_any"][0]) + PROPOSED_ACCEPT[qid]
    after["must_not_contain"] = list(q["must_not_contain"]) + PROPOSED_BANS[qid]
    bad = 0

    print(f"\n{'='*72}\n{qid}\n{'='*72}")
    print("1. does any accept token pass inside its own negation?")
    for t in after["must_contain_any"][0]:
        neg = NEGATIONS.get(t.lower())
        leak = neg is not None and t.lower() in neg
        bad += leak
        print(f"   {'LEAKS' if leak else 'safe '}  {t!r}")

    resp = {"answer": OBSERVED[qid], "status": "ok", "citations": CITATIONS[qid]}
    print("\n2. the observed live answer")
    print(f"   before: {check(q, resp) or 'PASS'}")
    print(f"   after : {check(after, resp) or 'PASS'}")
    bad += bool(check(after, resp))

    print("\n3. discrimination specimens")
    for spec in SPECIMENS.get(qid, []):
        text, status = _payload(spec)
        r = {"answer": text, "citations": CITATIONS[qid], "status": status}
        got, want = not check(after, r), spec[0] is CORRECT
        bad += got != want
        print(f"   {'!!' if got != want else '  '} "
              f"{'CORRECT' if want else 'WRONG  '} pass={got!s:5} {spec[1]}")

    print("\n4. do the proposed bans fire on a CORRECT specimen?")
    hits = [(spec[1], b) for spec in SPECIMENS.get(qid, []) if spec[0] is CORRECT
            for b in PROPOSED_BANS[qid] if b in _payload(spec)[0].lower()]
    bad += len(hits)
    print("   none fired" if not hits else f"   !! {hits}")
    return bad


if __name__ == "__main__":
    total = sum(run(q) for q in ("q11", "q18"))
    print(f"\n{'FAIL' if total else 'OK'}: {total} problem(s)")
    raise SystemExit(1 if total else 0)
