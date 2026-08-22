"""The full prose of q03's failing answers against a passing one.

The invariant probe found the banned literal lives ONLY in the prose `answer`
field and never in `answer_rows`. A structural check that reads rows therefore
looks at a place the defect has never appeared. Before ruling on that, the seat
needs the sentences themselves.

Reads only evals/history/. No API, no AWS, no cost.
"""
import json
import pathlib
import textwrap

HIST = pathlib.Path("evals/history")
CARDS = [
    ("superseded/1f46b92-aoss-full.run1.json", "FAIL — aoss run 1, 2026-08-20"),
    ("1f46b92-s3vectors-full.json", "FAIL — s3vectors, 2026-08-20"),
    ("1f46b92-aoss-full.json", "PASS — aoss run 2, same sha, same day"),
    ("1fa942a-aoss-full.json", "PASS — the 2026-08-19 baseline"),
]

for name, label in CARDS:
    doc = json.loads((HIST / name).read_text(encoding="utf-8"))
    entry = next(e for e in doc["questions"] if e["id"] == "q03")
    print("=" * 78)
    print(f"{label}\n{name}")
    print(f"fails: {entry.get('fails') or 'none'}")
    print("-" * 78)
    for para in (entry["response"].get("answer") or "").split("\n"):
        print(textwrap.fill(para, 76) if para.strip() else "")
    print()
