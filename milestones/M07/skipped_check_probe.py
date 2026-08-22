"""Does a SKIPPED required status check block a merge?

ADR-0005 left this open TWICE and was explicit about why. Its first version
said a skipped check does not satisfy a required check and called that
"verified empirically". It was not: the observation behind it (PR #1 still
BLOCKED) was equally explained by a context string that never matched, and
nothing had been run to tell the two apart. The correction removed the claim
and left the question open, to be answered "when there is a job that can
actually skip".

There is now. `golden-set` is a required check on ruleset 20392406 and
`EVAL_GATE_ENABLED` is still 'false', so it reports SKIPPED on every PR.

WHAT MAKES THIS A SINGLE-VARIABLE READ, and the reason this is a script rather
than a glance at the merge button: mergeStateStatus is BLOCKED for any reason
at all, so reading it off a PR that has anything else wrong establishes
nothing. That is exactly the mistake ADR-0005 corrected. So this refuses to
report an answer unless every other required check is SUCCESS and the only
non-success is the skip.

Usage:  python milestones/M07/skipped_check_probe.py <pr-number>
"""
from __future__ import annotations

import json
import subprocess
import sys

REPO = "andaro74/regdelta"
EXPECT_SKIPPED = "golden-set"


def gh_json(*args: str):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh failed: {' '.join(args)}\n{r.stderr}")
    return json.loads(r.stdout)


def required_checks() -> list[str]:
    rs = gh_json("api", f"repos/{REPO}/rulesets/20392406")
    for rule in rs["rules"]:
        if rule["type"] == "required_status_checks":
            p = rule["parameters"]["required_status_checks"]
            return sorted(c["context"] for c in p)
    raise SystemExit("no required_status_checks rule")


def main() -> int:
    pr = sys.argv[1] if len(sys.argv) > 1 else "16"
    required = required_checks()
    data = gh_json("pr", "view", pr, "--repo", REPO, "--json",
                   "mergeStateStatus,mergeable,statusCheckRollup")
    rollup = {c["name"]: c.get("conclusion") for c in data["statusCheckRollup"]}

    print(f"PR #{pr}")
    print("  required checks on the ruleset:", required)
    for name in required:
        print(f"    {name:<14} {rollup.get(name, '<absent>')}")
    print("  mergeable        :", data["mergeable"])
    print("  mergeStateStatus :", data["mergeStateStatus"])
    print()

    others = [n for n in required if n != EXPECT_SKIPPED]
    confounded = [n for n in others if rollup.get(n) != "SUCCESS"]
    if rollup.get(EXPECT_SKIPPED) != "SKIPPED":
        print(f"NOT A VALID READ: {EXPECT_SKIPPED} is "
              f"{rollup.get(EXPECT_SKIPPED)!r}, not SKIPPED.")
        return 2
    if confounded:
        print("NOT A VALID READ: these required checks are not SUCCESS, so",
              "mergeStateStatus cannot be attributed to the skip:")
        for n in confounded:
            print(f"    {n} = {rollup.get(n)!r}")
        return 2

    blocked = data["mergeStateStatus"] == "BLOCKED"
    print("SINGLE-VARIABLE READ HOLDS: every other required check is SUCCESS")
    print(f"  and {EXPECT_SKIPPED} is SKIPPED.")
    print()
    print("ANSWER: a SKIPPED required status check",
          "DOES block the merge." if blocked else "does NOT block the merge.")
    print(f"  (mergeStateStatus = {data['mergeStateStatus']})")
    print()
    print("SCOPE. This is one repository, one ruleset, one skip mechanism (a")
    print("job-level `if:` that evaluates false). It does not speak to a job")
    print("skipped by a failed `needs:`, which is a different conclusion path")
    print("and worth its own read before anyone relies on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
