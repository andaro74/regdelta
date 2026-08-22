"""Add `golden-set` and `ruling-cited` to the branch ruleset's required checks.

Three things in this file are not incidental, and each of them cost the project
once already.

1. BARE JOB NAMES. `golden-set`, not `eval-gate / golden-set`. The second form
   is the DISPLAY format GitHub shows in the checks UI; the required-checks API
   matches on the job name alone. ADR-0005 records a required check written in
   display format that matched nothing, sat pending forever, and deadlocked
   PR #1 for four days.

2. PUT, NOT PATCH. PATCH on this endpoint returns a flat 404 whose body says
   nothing about why.

3. THE WHOLE OBJECT. PUT replaces rather than merges. A body carrying only the
   key being changed silently drops `rules`, which DELETES branch protection.
   So this reads the live ruleset, edits one list inside it, and sends
   everything back — then reads it again and diffs field by field.

Run:  python milestones/M07/add_required_checks.py [--apply]
Without --apply it prints the change and exits without writing.
"""
from __future__ import annotations

import json
import subprocess
import sys

REPO = "andaro74/regdelta"
RULESET_ID = 20392406
ADD = ["golden-set", "ruling-cited"]

# MERGE COMMITS ONLY. A squash on PR #13 orphaned f651aea and forced the
# preservation tag `m06-disposition`, because a squash rewrites the commits it
# lands and this project's commit messages ARE the record — the milestone
# READMEs say so and say to read them for the detail. Leaving squash available
# and writing "never squash" in a README makes the record depend on someone
# reading it. Set to None to leave the field alone.
MERGE_METHODS = ["merge"]


def api(*args: str, body: str | None = None) -> dict:
    cmd = ["gh", "api", *args]
    if body is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=body, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh api failed: {' '.join(args)}\n{r.stderr}")
    return json.loads(r.stdout)


def fetch() -> dict:
    return api(f"repos/{REPO}/rulesets/{RULESET_ID}")


def checks_of(rs: dict) -> list[str]:
    for rule in rs["rules"]:
        if rule["type"] == "required_status_checks":
            p = rule["parameters"]["required_status_checks"]
            return [c["context"] for c in p]
    raise SystemExit("no required_status_checks rule — refusing to guess")


def main() -> int:
    apply = "--apply" in sys.argv
    before = fetch()
    print("BEFORE  required checks:", checks_of(before))
    print("        rules:", sorted(r["type"] for r in before["rules"]))
    print("        bypass_actors:", json.dumps(before.get("bypass_actors")))

    # Build the PUT body from the LIVE object, not from a literal.
    body = {
        "name": before["name"],
        "target": before["target"],
        "enforcement": before["enforcement"],
        "bypass_actors": before.get("bypass_actors", []),
        "conditions": before["conditions"],
        "rules": json.loads(json.dumps(before["rules"])),   # deep copy
    }
    for rule in body["rules"]:
        if rule["type"] == "pull_request" and MERGE_METHODS is not None:
            rule["parameters"]["allowed_merge_methods"] = list(MERGE_METHODS)
        if rule["type"] == "required_status_checks":
            got = rule["parameters"]["required_status_checks"]
            have = {c["context"] for c in got}
            for name in ADD:
                if name not in have:
                    got.append({"context": name})

    want = sorted(set(checks_of(before)) | set(ADD))
    print("AFTER   required checks (intended):", want)
    print("AFTER   allowed_merge_methods (intended):", MERGE_METHODS)
    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    api(f"repos/{REPO}/rulesets/{RULESET_ID}", "-X", "PUT",
        body=json.dumps(body))

    after = fetch()
    ok = True
    print("\nREAD BACK")
    print("  required checks:", sorted(checks_of(after)),
          "OK" if sorted(checks_of(after)) == want else "MISMATCH")
    ok &= sorted(checks_of(after)) == want
    if MERGE_METHODS is not None:
        got = [r for r in after["rules"] if r["type"] == "pull_request"][0]
        got = got["parameters"]["allowed_merge_methods"]
        print("  allowed_merge_methods:", got,
              "OK" if sorted(got) == sorted(MERGE_METHODS) else "MISMATCH")
        ok &= sorted(got) == sorted(MERGE_METHODS)
    for field in ("name", "target", "enforcement", "conditions", "bypass_actors"):
        same = json.dumps(after.get(field), sort_keys=True) == \
               json.dumps(before.get(field), sort_keys=True)
        print(f"  {field} unchanged: {same}")
        ok &= same
    same_rules = sorted(r["type"] for r in after["rules"]) == \
                 sorted(r["type"] for r in before["rules"])
    print("  the four rules survived:", same_rules)
    ok &= same_rules
    print("\nRESULT:", "OK" if ok else "SOMETHING CHANGED THAT SHOULD NOT HAVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
