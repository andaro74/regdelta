"""Does the structural invariant hold across EVERY recorded q03 answer?

The M05 open thread proposes scoring q03 structurally, on the grounds that the
defect is "a TTB proposition carrying a Red No. 3 citation" and the failing
answer's `answer_rows[1].citations` was `[]`. That is one observation of one
card. Before a check is built on it, the same property has to be read off every
card there is — including the ones that PASSED, because a rule that only
distinguishes the fail is not a rule.

Prints, per recorded q03 answer:
  - whether answer_rows exists at all
  - for each row: whether it mentions the other agency, and whether it carries
    citations
  - where the banned literal 'TTB requires' actually sits (rows vs prose)

Reads only evals/history/. No API, no AWS, no cost.
"""
import json
import pathlib

HIST = pathlib.Path("evals/history")
BANNED = ("ttb requires", "ttb will require", "must obtain ttb approval",
          "ttb regulations require")
# The topic selector, NOT the verdict. Naming the other agency is CORRECT
# behaviour per the 2026-08-12 ruling; the verdict comes from the citations.
AGENCY = ("ttb", "another federal agency", "other agency", "alcohol and tobacco")

cards = sorted(HIST.glob("*-full.json")) + sorted(HIST.glob("superseded/*.json"))

print(f"{'card':38} {'mode':6} {'pass':5} {'rows':4} "
      f"{'agency-rows(cited/uncited)':26} banned-literal-in")
print("-" * 118)

shapes = {}
for card in cards:
    doc = json.loads(card.read_text(encoding="utf-8"))
    mode = doc.get("mode", "?")
    for entry in doc.get("questions", []):
        if entry.get("id") != "q03":
            continue
        resp = entry.get("response", {})
        rows = resp.get("answer_rows")
        prose = (resp.get("answer") or "").lower()
        rows_json = json.dumps(rows or "").lower()

        if not isinstance(rows, list):
            shape = "NO ROWS"
            cited = uncited = 0
        else:
            cited = uncited = 0
            for row in rows:
                blob = json.dumps(row).lower() if isinstance(row, dict) else str(row).lower()
                if not any(a in blob for a in AGENCY):
                    continue
                has_c = bool(isinstance(row, dict) and row.get("citations"))
                cited += has_c
                uncited += not has_c
            shape = f"{len(rows)} rows"
        shapes[shape] = shapes.get(shape, 0) + 1

        where = []
        if any(b in rows_json for b in BANNED):
            where.append("ROWS")
        if any(b in prose for b in BANNED):
            where.append("prose")
        print(f"{card.name:38} {mode:6} {str(entry.get('pass')):5} "
              f"{shape:4} {f'cited={cited} uncited={uncited}':26} "
              f"{','.join(where) or '-'}")

print()
print("row-count shapes observed:", shapes)
