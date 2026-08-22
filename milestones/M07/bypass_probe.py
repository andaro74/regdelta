"""Does removing the admin bypass actually bind the repository OWNER?

Door 1's whole claim rests on this and nothing in this repo has ever tested it.
The ruleset currently carries `bypass_actors: [RepositoryRole 5 (admin), mode
"always"]` and reports `current_user_can_bypass: "always"`. The plan is to
remove that actor so the gate binds everyone — but "rulesets apply to anyone
not listed as a bypass actor, including the repository owner" is a claim about
GitHub's semantics that I have read and not run.

ADR-0005 exists because exactly this kind of claim was believed twice. A
required check written in the UI's display format matched nothing and sat
pending forever; and the first version of that ADR explained the deadlock with
a plausible mechanism, called it "verified empirically" on an observation that
did not discriminate between two candidate causes, and was wrong. A gate is a
hypothesis until something fails against it.

WHAT THIS DOES. Reads the live ruleset, removes the bypass actor, reads it
back, and RESTORES the original in a finally — verified field by field. It
changes no branch, merges nothing, and spends nothing. What it establishes is
narrow and worth being precise about: that GitHub REPORTS the owner as no
longer able to bypass. Whether a merge is then actually refused is a claim only
a real blocked pull request can settle, and that is Door 1 itself.

    python milestones/M07/bypass_probe.py [--dry-run]
"""
import argparse
import json
import subprocess
import sys

REPO = "andaro74/regdelta"
RULESET = "20392406"
FIELDS = ("bypass_actors", "current_user_can_bypass")


def gh_json(*args):
    out = subprocess.run(["gh", "api", *args], check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out)


def read():
    return gh_json(f"repos/{REPO}/rulesets/{RULESET}")


def summarise(rs, label):
    print(f"{label}")
    print(f"    bypass_actors           : {json.dumps(rs.get('bypass_actors'))}")
    print(f"    current_user_can_bypass : {rs.get('current_user_can_bypass')!r}")
    print(f"    enforcement             : {rs.get('enforcement')!r}")
    checks = [r for r in rs["rules"] if r["type"] == "required_status_checks"]
    contexts = [c["context"] for r in checks
                for c in r["parameters"]["required_status_checks"]]
    print(f"    required checks         : {contexts}")
    return rs


def put_bypass(current, actors):
    """Update the ruleset, changing ONLY bypass_actors, by sending it whole.

    Two things learned by running this rather than reading about it:

    PATCH IS NOT THE VERB. The first version used PATCH and got a flat
    `404 Not Found` — the same status as a wrong repo or a missing ruleset, so
    it says nothing about what was wrong. The update endpoint is
    `PUT /repos/{owner}/{repo}/rulesets/{id}`. Nothing was modified by the
    failed call, verified against the live ruleset afterwards.

    THE BODY IS THE WHOLE RULESET, not just the key being changed. If PUT
    replaces rather than merges, a one-key body silently drops `rules` — which
    on THIS ruleset means deleting branch protection on `main` in order to run
    a probe about branch protection. Sending everything makes the outcome
    well-defined under either semantics, and `main_rules()` below asserts the
    rules survived rather than trusting that they did.
    """
    body = {
        "name": current["name"],
        "target": current["target"],
        "enforcement": current["enforcement"],
        "conditions": current["conditions"],
        "rules": current["rules"],
        "bypass_actors": actors,
    }
    proc = subprocess.run(
        ["gh", "api", "--method", "PUT", f"repos/{REPO}/rulesets/{RULESET}",
         "--input", "-"],
        input=json.dumps(body), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{proc.stderr[-800:]}\n{proc.stdout[-400:]}")
    return json.loads(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    original = read()
    before = {f: original.get(f) for f in FIELDS}
    summarise(original, "BEFORE - the ruleset as it stands")

    if args.dry_run:
        print("\ndry run - the bypass actor was not touched")
        return 0

    rules_before = json.dumps(original["rules"], sort_keys=True)
    print()
    try:
        after = summarise(put_bypass(original, []), "AFTER  - bypass_actors emptied")
        bound = after.get("current_user_can_bypass") in (None, "never", "")
        rules_kept = json.dumps(after["rules"], sort_keys=True) == rules_before
        print()
        print("FINDING: GitHub reports the repository owner as "
              f"{'BOUND' if bound else 'STILL ABLE TO BYPASS'} "
              f"(current_user_can_bypass={after.get('current_user_can_bypass')!r}).")
        print(f"  the four rules survived the update: {rules_kept}")
        if not bound:
            print("  So emptying bypass_actors is NOT sufficient, and Door 1")
            print("  cannot be made honest by this route alone. Do not film it.")
        print()
        print("  WHAT THIS DOES NOT ESTABLISH: that a merge is actually refused.")
        print("  This is GitHub's own report of a capability, which is the same")
        print("  KIND of claim that was wrong about `eval-gate / unit` matching")
        print("  a check context. Only a real blocked pull request settles it,")
        print("  and that pull request is Door 1.")
    finally:
        restored = put_bypass(original, original.get("bypass_actors") or [])
        same = ({f: restored.get(f) for f in FIELDS} == before
                and json.dumps(restored["rules"], sort_keys=True) == rules_before)
        print()
        summarise(restored, "RESTORED")
        print(f"\nrestored to the original ruleset, rules included: {same}")
        if not same:
            sys.exit("RULESET NOT RESTORED - fix by hand before doing anything else")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
