"""Is deleting six q12 accept tokens a STRICT TIGHTENING, or does it flip a verdict?

sme-eval-triage (2026-08-22) found that six of the nine tokens in q12's first
`must_contain_any` group are substrings of their own negation, and the scorer
is a case-insensitive substring test (`evals/run_evals.py:442-460`). So an
answer asserting the OPPOSITE of ground truth can score PASS. It flagged its
own finding as unverified: "a hand-simulated token is not a ruled token."

This is that verification. It does two things and nothing else:

  1. Mechanically confirms each token is or is not a substring of its negation.
  2. Replays EVERY recorded answer in evals/history/ against q12's current
     accept group and against the proposed one, and reports any verdict that
     CHANGES. A tightening that flips a recorded PASS to FAIL is not a
     tightening, it is a new gate, and the SME seat must be told which it is.

Run: python milestones/M07/q12_token_probe.py
"""
from __future__ import annotations

import glob
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CURRENT = ["was fair", "fair at the time", "was reasonable",
           "reasonable at the time", "accurate at the time",
           "was a fair reading", "fair reading at the time", "fair then",
           "correct at the time"]
PROPOSED = ["was fair", "was reasonable", "was a fair reading"]
DELETED = [t for t in CURRENT if t not in PROPOSED]

# The negation a reader would actually write. Each is the token with a "not"
# inserted the way English puts it, which is the whole question.
NEGATIONS = {
    "was fair": "was not fair",
    "fair at the time": "was not fair at the time",
    "was reasonable": "was not reasonable",
    "reasonable at the time": "was not reasonable at the time",
    "accurate at the time": "was not accurate at the time",
    "was a fair reading": "was not a fair reading",
    "fair reading at the time": "not a fair reading at the time",
    "fair then": "was not fair then",
    "correct at the time": "was not correct at the time",
}


def flatten_answer(resp: dict) -> str:
    parts = [json.dumps(resp.get("answer_rows", "")), resp.get("answer", "")]
    parts += [json.dumps(c) for c in resp.get("citations", [])]
    return " ".join(parts)


def group_passes(group: list[str], low: str) -> bool:
    return any(n.lower() in low for n in group)


def main() -> int:
    print("PART 1 — is each token a substring of its own negation?")
    print("(if yes, an answer asserting the OPPOSITE scores PASS on it)\n")
    leaky = []
    for tok in CURRENT:
        neg = NEGATIONS[tok]
        bad = tok.lower() in neg.lower()
        if bad:
            leaky.append(tok)
        print(f"  {'LEAKS ' if bad else 'safe  '} {tok!r:<28} inside {neg!r}")
    print(f"\n  leaking: {len(leaky)} of {len(CURRENT)}")
    print(f"  proposed deletion: {sorted(DELETED)}")
    print(f"  deletion == leaking set: {sorted(leaky) == sorted(DELETED)}")

    print("\n\nPART 2 — replay every recorded answer. Does any verdict change?\n")
    changed, seen = [], 0
    for f in sorted(glob.glob(str(ROOT / "evals" / "history" / "*.json"))):
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        for q in d.get("questions", []):
            if q.get("id") != "q12":
                continue
            resp = q.get("response")
            if not isinstance(resp, dict):
                continue
            seen += 1
            low = flatten_answer(resp).lower()
            now, then = group_passes(CURRENT, low), group_passes(PROPOSED, low)
            matched = [t for t in CURRENT if t.lower() in low]
            tag = "same" if now == then else "CHANGED"
            if now != then:
                changed.append((Path(f).name, matched))
            print(f"  {Path(f).name:<34} group_now={str(now):<5} "
                  f"group_proposed={str(then):<5} {tag}  matched={matched}")

    print(f"\n  recorded q12 answers replayed: {seen}")
    print(f"  verdicts changed: {len(changed)}")
    if changed:
        print("  NOT A PURE TIGHTENING — these flipped:")
        for name, m in changed:
            print(f"    {name}  matched only {m}")
    else:
        print("  STRICT TIGHTENING: no recorded verdict moves. The deletion "
              "removes accept surface and flips nothing.")
    print("\n  NOTE: 'flips nothing' is about the answers this repo HAS "
          "recorded.\n  The reason to delete the tokens is the answer it has "
          "NOT recorded yet —\n  the recorded failing answer missed a false "
          "PASS by one word.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
