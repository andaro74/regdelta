"""Mutation check for the blocker both M05 reviewers found independently.

`search_stack` attaches the AOSS grant to the CORE stack's query role, which
puts an `AWS::IAM::Policy` in the EPHEMERAL stack whose `Roles:` list resolves
to `regdelta-core-QueryFnServiceRole…`. Deleting it calls
`iam:DeleteRolePolicy` against that role — and the deletion role was scoped to
`role/regdelta-search-*`, which does not match. `DeleteStack(RoleARN=…)` would
take AccessDenied and land in DELETE_FAILED with the AOSS collection still
billing, nightly, on the one path with no human watching.

Invisible to the SPEC/05 Done-when: `make down` is `cdk destroy` under the
bootstrap AdministratorAccess role and always succeeds.

F1 restores the defect and must kill
`test_the_deletion_role_reaches_every_foreign_role_search_writes_to`. If it
ever stops doing so, that test has stopped testing the property and is
matching on the name prefix again.

Writes milestones/M05/deletion-role-mutations.json.
"""
import io
import json
import subprocess
import sys

CORE = "infra/core/core_stack.py"
TESTS = "tests/test_janitor.py"

GRANT = '''        search_deleter.add_to_policy(iam.PolicyStatement(
            actions=["iam:DeleteRolePolicy", "iam:GetRolePolicy"],
            resources=[query_fn.role.role_arn]))
'''

MUTATIONS = [
    ("F1 the cross-stack grant removed (the blocker, restored)",
     [(GRANT, "")]),
    # Present but pointed at the name prefix — the shape a reader might
    # "tidy" it into, and the one a test that matched on prefixes would miss.
    ("F2 the grant narrowed back to the name prefix alone",
     [(GRANT,
       GRANT.replace(
           "resources=[query_fn.role.role_arn]))",
           'resources=[self.format_arn(\n'
           '                service="iam", region="", resource="role",\n'
           '                resource_name="regdelta-search-*")]))'))]),
]


def failing() -> list[str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "--no-header", "-rf",
         "--tb=no"], capture_output=True, text=True)
    out = p.stdout + p.stderr
    names = sorted({line.split("::")[-1].split(" ")[0]
                    for line in out.splitlines() if line.startswith("FAILED ")})
    if p.returncode == 0:
        return []
    return names or [f"<error rc={p.returncode}>"]


def main() -> int:
    original = io.open(CORE, encoding="utf-8").read()
    results = {}
    try:
        for name, edits in MUTATIONS:
            src = original
            for old, new in edits:
                if old not in src:
                    print(f"!! {name}: anchor not found")
                    results[name] = ["<ANCHOR NOT FOUND>"]
                    break
                src = src.replace(old, new, 1)
            else:
                io.open(CORE, "w", encoding="utf-8", newline="\n").write(src)
                results[name] = failing()
                io.open(CORE, "w", encoding="utf-8",
                        newline="\n").write(original)
            print(f"{name}\n   -> {results.get(name)}")
    finally:
        io.open(CORE, "w", encoding="utf-8", newline="\n").write(original)
    io.open("milestones/M05/deletion-role-mutations.json", "w",
            encoding="utf-8").write(json.dumps(results, indent=2))
    survivors = [k for k, v in results.items() if not v]
    print("\nSURVIVED:", survivors or "none")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
