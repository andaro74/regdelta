"""What `answer_rows` ACTUALLY look like on q03, across every recorded card.

Written before designing a structural check, not after. The M05 open thread
says the failing answer's `answer_rows[1].citations` was `[]` and that this
makes the defect checkable without reading wording. That claim is a premise,
and a check built on it has to be built on the observed shape rather than on
the sentence describing it.

Reads only evals/history/. No API, no AWS, no cost.
"""
import json
import pathlib
import sys

HIST = pathlib.Path("evals/history")
QID = sys.argv[1] if len(sys.argv) > 1 else "q03"

cards = sorted(HIST.glob("*-full.json")) + sorted(HIST.glob("superseded/*.json"))

for card in cards:
    doc = json.loads(card.read_text(encoding="utf-8"))
    for entry in doc.get("questions", []):
        if entry.get("id") != QID:
            continue
        resp = entry.get("response", {})
        rows = resp.get("answer_rows")
        print("=" * 78)
        print(f"{card.name}   {QID}  pass={entry.get('pass')}  "
              f"status={resp.get('status')}")
        if entry.get("fails"):
            print(f"  fails: {entry['fails']}")
        if rows is None:
            print("  answer_rows: ABSENT")
        elif not isinstance(rows, list):
            print(f"  answer_rows: NOT A LIST — {type(rows).__name__}")
        else:
            print(f"  answer_rows: {len(rows)} rows")
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    print(f"    [{i}] NOT A DICT — {type(row).__name__}: "
                          f"{str(row)[:120]}")
                    continue
                keys = sorted(row)
                cites = row.get("citations")
                print(f"    [{i}] keys={keys}")
                print(f"        citations={cites!r}")
                for k, v in row.items():
                    if k == "citations":
                        continue
                    print(f"        {k}: {str(v)[:200]}")
        ans = resp.get("answer") or ""
        print(f"  answer ({len(ans)} chars): {ans[:300]}")
        print(f"  top-level citations: "
              f"{[c.get('doc') if isinstance(c, dict) else c for c in resp.get('citations') or []]}")
