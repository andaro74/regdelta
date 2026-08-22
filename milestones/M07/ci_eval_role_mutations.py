"""Can tests/test_ci_eval_role.py refuse a badly-scoped OIDC role?

The two failure modes this role has are both silent and both common in
published examples: an omitted `aud` condition, which lets any GitHub
repository in the world assume it, and a `sub` of `repo:owner/name:*`, which
lets any ref in this repo do it. Neither breaks a deploy and neither shows up
in a working CI run — so a passing test suite says nothing until each has been
made to fail.

Mutates infra/core/core_stack.py in place, restores it in a finally, and
verifies the restore byte-for-byte. Each mutation asserts a NAMED test goes
red; a mutation whose anchor does not match is reported un-applied rather than
counted as killed.

CDK synth is slow (~30s), so this is a milestone artifact rather than a test.
No AWS calls, no deploy, no cost.

    python milestones/M07/ci_eval_role_mutations.py
"""
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
STACK = ROOT / "infra" / "core" / "core_stack.py"
TESTS = ROOT / "tests" / "test_ci_eval_role.py"
ORIGINAL = STACK.read_bytes()
TEXT = ORIGINAL.decode("utf-8")

MUTATIONS = [
    ("aud condition dropped — any GitHub repo in the world may assume it",
     '                        "token.actions.githubusercontent.com:aud":\n'
     '                            "sts.amazonaws.com",\n',
     "",
     "test_the_audience_claim_is_pinned_to_sts"),

    ("sub widened to repo:andaro74/regdelta:* — any ref in this repo",
     '                            "repo:andaro74/regdelta:pull_request",',
     '                            "repo:andaro74/regdelta:*",',
     "test_the_subject_claim_is_scoped_to_the_event_not_just_the_repo"),

    ("the explicit statement replaced by grant_read_data",
     "        ci_eval.add_to_policy(iam.PolicyStatement(\n"
     '            sid="ReadRegistryForCorpusFingerprint",\n'
     '            actions=["dynamodb:Scan"],\n'
     "            resources=[self.registry_table.table_arn]))",
     "        self.registry_table.grant_read_data(ci_eval)",
     "test_it_holds_exactly_one_statement_granting_exactly_one_action"),

    ("an execute-api grant added to 'fix' the role",
     "        cdk.CfnOutput(self, \"CiEvalRoleArn\", value=ci_eval.role_arn,",
     "        ci_eval.add_to_policy(iam.PolicyStatement(\n"
     '            actions=["execute-api:Invoke"], resources=["*"]))\n'
     "        cdk.CfnOutput(self, \"CiEvalRoleArn\", value=ci_eval.role_arn,",
     "test_it_grants_nothing_for_the_api"),
]


def run_test(name):
    p = subprocess.run(
        [sys.executable, "-m", "pytest", f"{TESTS}::{name}", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return p.returncode


print(f"{'mutation':66} {'applied':8} killed by named test")
print("-" * 104)
survivors = []
try:
    baseline = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS), "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    if baseline.returncode != 0:
        sys.exit(f"the guard is already red before mutation:\n"
                 f"{baseline.stdout[-800:]}")

    for label, find, repl, test in MUTATIONS:
        hits = TEXT.count(find)
        if hits != 1:
            survivors.append(f"{label} (anchor matched {hits}x)")
            print(f"{label:66} {'NO':8} -- not attributable")
            continue
        STACK.write_text(TEXT.replace(find, repl), encoding="utf-8")
        red = run_test(test) != 0
        survivors += [] if red else [label]
        print(f"{label:66} {'yes':8} "
              f"{test if red else 'SURVIVED: ' + test}")
finally:
    STACK.write_bytes(ORIGINAL)
    restored = (hashlib.sha256(STACK.read_bytes()).hexdigest()
                == hashlib.sha256(ORIGINAL).hexdigest())
    print(f"\ncore_stack.py restored byte-for-byte: {restored}")
    if not restored:
        sys.exit("STACK NOT RESTORED — fix by hand before committing")

print(f"{len(survivors)} survivor(s) out of {len(MUTATIONS)}"
      f"{': ' + '; '.join(survivors) if survivors else ''}")
sys.exit(1 if survivors else 0)
