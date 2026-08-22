"""Remove the admin bypass from the branch ruleset, and read it back.

M07 step 4, and the last governance change of the milestone. Until now the
repository owner could merge past any required check with `--admin`, and did so
exactly once — PR #15, over a red `unit` that `main` had carried since M04.

THE ORDER MATTERS AND IT IS WHY THIS RUNS LAST. The bypass is the only way past
a red required check. Removing it while `golden-set` had never gone green would
have stranded every pull request in the repository with no recourse but to put
the bypass back — which is the same as never having removed it, plus a story
about having done so. So it comes off only now, with all three required checks
green on `main`:

    unit          pass    (PR #18)
    ruling-cited  pass
    golden-set    pass    18/20, no regression

WHAT IT ESTABLISHES, AND WHAT IT DOES NOT. `bypass_probe.py` already measured
that emptying `bypass_actors` flips the owner to `can_bypass: never`; this makes
that permanent rather than probing and restoring it. Neither establishes that a
merge is actually refused — that is settled only by a blocked pull request, and
that pull request is Door 1. SPEC/07's Done-when now requires the ruleset JSON
showing an empty `bypass_actors` to accompany Door 1's screenshot, precisely so
the caption cannot outrun the evidence.

REVERSING IT is one call, and the value to restore is printed below before
anything changes, so it is on the record rather than in someone's memory.

Run:  python milestones/M07/remove_bypass.py [--apply]
"""
from __future__ import annotations

import json
import subprocess
import sys

REPO = "andaro74/regdelta"
RULESET_ID = 20392406


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
            return sorted(c["context"] for c in
                          rule["parameters"]["required_status_checks"])
    raise SystemExit("no required_status_checks rule — refusing to guess")


def main() -> int:
    apply = "--apply" in sys.argv
    before = fetch()

    print("BEFORE")
    print("  bypass_actors        :", json.dumps(before.get("bypass_actors")))
    print("  current_user_can_bypass:",
          repr(before.get("current_user_can_bypass")))
    print("  required checks      :", checks_of(before))
    print("  rules                :", sorted(r["type"] for r in before["rules"]))
    print()
    print("TO REVERSE THIS, restore exactly:")
    print("  bypass_actors =", json.dumps(before.get("bypass_actors")))
    print()

    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply.")
        return 0

    # WHOLE OBJECT, PUT NOT PATCH. PUT replaces rather than merges: a body
    # carrying only `bypass_actors` drops `rules` and DELETES branch
    # protection. So this sends everything back and then compares field by
    # field — "it returned 200" is not the same claim as "nothing else moved".
    body = {
        "name": before["name"],
        "target": before["target"],
        "enforcement": before["enforcement"],
        "bypass_actors": [],
        "conditions": before["conditions"],
        "rules": json.loads(json.dumps(before["rules"])),
    }
    api(f"repos/{REPO}/rulesets/{RULESET_ID}", "-X", "PUT",
        body=json.dumps(body))

    after = fetch()
    ok = True
    print("AFTER")
    empty = after.get("bypass_actors") == []
    print("  bypass_actors        :", json.dumps(after.get("bypass_actors")),
          "OK" if empty else "STILL POPULATED")
    ok &= empty
    can = after.get("current_user_can_bypass")
    print("  current_user_can_bypass:", repr(can),
          "OK" if can == "never" else "NOT 'never'")
    ok &= can == "never"

    same_checks = checks_of(after) == checks_of(before)
    print("  required checks      :", checks_of(after),
          "unchanged" if same_checks else "CHANGED")
    ok &= same_checks

    for field in ("name", "target", "enforcement", "conditions"):
        same = json.dumps(after.get(field), sort_keys=True) == \
               json.dumps(before.get(field), sort_keys=True)
        print(f"  {field} unchanged: {same}")
        ok &= same

    same_rules = sorted(r["type"] for r in after["rules"]) == \
                 sorted(r["type"] for r in before["rules"])
    print("  the four rules survived:", same_rules)
    ok &= same_rules

    print()
    print("RESULT:", "OK" if ok else "SOMETHING CHANGED THAT SHOULD NOT HAVE")
    print()
    print("This says GitHub now reports the owner as unable to bypass. Whether")
    print("a merge is actually refused is settled by Door 1, not by this.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
