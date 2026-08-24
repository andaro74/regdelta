#!/usr/bin/env python3
"""Why does `supervisor()` mark q04, q10, q16 and q19 insufficient?

THE QUESTION THIS ANSWERS, and the reason it exists rather than a ruling.
`milestones/M09/sme-ruling-pause-suppression.md` ruling 3a records, from three
recorded full runs, that the HITL gate fires on four golden questions and that
all four score PASS. It does NOT rule which of the four pauses are wrong,
because the reading behind that — "the classifier fires on the words us/our" —
was a hypothesis drawn from reading outputs, and nothing had been run to tell
it from the alternatives.

That distinction is the whole point. ADR-0005 answered a question, said
"verified empirically", and was wrong: the observation behind it had two
equally good explanations and no probe had separated them.
`milestones/M07/eval-gate-flake-gap.md` records three successive misdiagnoses
made before anyone read the metrics. This is the probe that comes first.

WHAT IT ISOLATES. `supervisor()` alone — one MODEL_FAST call per question, no
retrieval, no verdict model, no graph. So the answer cannot be confounded by
anything downstream, and the raw model output is captured rather than only the
parsed verdict: if the classifier is returning well-formed JSON with the wrong
judgement, that is a PROMPT defect; if it is returning something the parser
falls back on, that is a PARSING defect, and they need different fixes. Reading
only `profile_sufficient` cannot tell them apart, which is exactly the mistake
this file exists to avoid making a fourth time.

THREE HYPOTHESES IT CAN SEPARATE:
  H1  the prompt asks the wrong question, and the model answers it correctly
      -> raw JSON parses, `profile_sufficient: false`, and a human reading the
         prompt agrees the model's reading of it is fair
  H2  the model misjudges questions of law as questions about the asker
      -> raw JSON parses, `profile_sufficient: false`, and the prompt does NOT
         ask for that
  H3  the raw output does not parse and `_json_object` falls back
      -> `profile_sufficient` is false because the key is missing, not because
         the model said so. Nothing about the prompt is at fault.

CONTROLS, without which this measures nothing:
  · q18 is included and is NOT one of the four. It is q10's twin WITH a
    sufficient profile in the question text, and it must come back sufficient.
    If it does not, the classifier is broken generally and the four-question
    reading is the wrong subject entirely.
  · q01 is included as a second control: a question that has never paused.
  · Each question is asked THREE times. `run_evals` already treats
    run-to-run variance as real (ADR-0015, the admission register), so a
    single call per question could not distinguish "always insufficient" from
    "insufficient once". A verdict that is not unanimous is reported as
    unstable rather than averaged away.

COST. 18 MODEL_FAST calls. No Opus, no verdict model, no retrieval, no
embeddings. Run `make opus-headroom` if you want the number in context; this
does not move it.

USAGE
    eval "$(python evals/local_env.py)"      # or: make ui-tests-style resolve
    python milestones/M09/supervisor_probe.py            # prints + writes json
    python milestones/M09/supervisor_probe.py --runs 1   # cheaper, no stability
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The four that pause, plus two controls. Ids and stems are read from the
# golden set rather than transcribed — a probe that carries its own copy of a
# question is measuring a question nobody runs.
PAUSING = ["q04", "q10", "q16", "q19"]
CONTROLS = ["q18", "q01"]


def stems() -> dict[str, str]:
    src = json.loads((ROOT / "evals" / "golden_questions.json").read_text(encoding="utf-8"))
    questions = src["questions"] if isinstance(src, dict) else src
    by_id = {q["id"]: q["question"] for q in questions}
    missing = [i for i in PAUSING + CONTROLS if i not in by_id]
    if missing:
        sys.exit(f"golden set has no {missing} — the probe's subject moved; "
                 "re-derive it rather than hardcoding a stem here.")
    return {i: by_id[i] for i in PAUSING + CONTROLS}


def probe(runs: int) -> dict:
    from graph import nodes

    captured: list[str] = []

    def capture(*args, **kwargs):
        """Wrap `_converse` so the RAW model output is kept, not just the parse.

        This is the whole reason the probe is not a one-liner over
        `supervisor()`: `profile_sufficient` false tells you nothing about
        whether the model said so or the parser defaulted.
        """
        raw = nodes._converse(*args, **kwargs)
        captured.append(raw)
        return raw

    out: dict[str, dict] = {}
    for qid, stem in stems().items():
        calls = []
        for _ in range(runs):
            captured.clear()
            state = {"query": stem, "company_profile": {}}
            result = nodes.supervisor(state, invoke=capture)
            raw = captured[-1] if captured else ""
            parsed = nodes._json_object(raw)
            calls.append({
                "profile_sufficient": bool(result.get("profile_sufficient")),
                "intent": result.get("intent"),
                "products": result.get("company_profile", {}).get("products"),
                "claims": result.get("company_profile", {}).get("claims"),
                # H3's discriminator: did the model SAY it, or did the parser
                # fall back to a dict that has no such key?
                "key_present_in_raw": "profile_sufficient" in parsed,
                "raw_parsed": bool(parsed),
                "raw": raw[:1200],
            })
        verdicts = {c["profile_sufficient"] for c in calls}
        out[qid] = {
            "question": stems()[qid],
            "control": qid in CONTROLS,
            "sufficient": calls[0]["profile_sufficient"] if len(verdicts) == 1 else None,
            "stable": len(verdicts) == 1,
            "calls": calls,
        }
    return out


def report(results: dict) -> int:
    print("\nsupervisor() alone — profile_sufficient per question\n")
    print(f"  {'id':5} {'ctl':4} {'stable':7} {'sufficient':11} {'json':5} intent")
    print("  " + "-" * 62)
    for qid, r in results.items():
        first = r["calls"][0]
        print(f"  {qid:5} {'yes' if r['control'] else '':4} "
              f"{'yes' if r['stable'] else 'NO':7} "
              f"{r['sufficient']!s:11} "
              f"{'ok' if first['raw_parsed'] else 'FAIL':5} {first['intent']}")

    print("\n--- what this separates ---")
    unparsed = [q for q, r in results.items() if not r["calls"][0]["raw_parsed"]]
    keyless = [q for q, r in results.items()
               if r["calls"][0]["raw_parsed"] and not r["calls"][0]["key_present_in_raw"]]
    unstable = [q for q, r in results.items() if not r["stable"]]

    if unparsed:
        print(f"H3 (PARSING): raw output did not parse for {unparsed}. "
              "profile_sufficient is false by fallback, not by judgement.")
    if keyless:
        print(f"H3 (PARSING): parsed, but no `profile_sufficient` key for {keyless} — "
              "same conclusion, different mechanism.")
    if unstable:
        print(f"UNSTABLE across runs: {unstable}. A single-call probe would have "
              "reported one of these as settled.")

    controls = {q: r for q, r in results.items() if r["control"]}
    bad_control = [q for q, r in controls.items()
                   if q == "q18" and r["sufficient"] is not True]
    if bad_control:
        print("\nCONTROL FAILED: q18 carries a product and a claim in the question "
              "text and must come back sufficient. It did not, so the classifier is "
              "wrong generally and the four-question reading is the wrong subject. "
              "STOP — do not read the table above as a finding about q04/q16/q19.")
        return 2

    if not (unparsed or keyless):
        print("NOT H3: every verdict is the model's own, not a parser fallback. "
              "So each verdict above is either the prompt asking for it (H1) or the "
              "model misjudging it (H2) — read `_SUPERVISOR_PROMPT` beside the raw "
              "outputs in the json to tell them apart. This line says what the probe "
              "ruled OUT; it does not say the table is right.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3,
                    help="calls per question (default 3; 1 skips stability)")
    ap.add_argument("--out", type=Path, default=HERE / "supervisor-probe.json")
    args = ap.parse_args()

    results = probe(args.runs)
    code = report(results)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    try:
        shown = args.out.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.out
    print(f"\nwritten: {shown}")
    print("This probe answers 3b's PREREQUISITE. It does not rule 3b.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
