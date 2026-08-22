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
# ANCHORS BELOW ARE WRITTEN WITH LF. The working tree is CRLF on Windows
# (git stores LF), and .read_bytes() skips newline translation — so after
# one in-place rewrite of the target, every multi-line anchor silently
# matched 0 times and five mutations reported as NOT APPLIED.
#
# They reported as not-applied rather than as killed, which is the only
# reason that run was legible: a probe unable to apply its own mutation
# must never be indistinguishable from a guard doing its job. That
# distinction was built in deliberately and it is what caught this.
# Normalised here; the restore still writes ORIGINAL bytes verbatim.
TEXT = ORIGINAL.decode("utf-8").replace("\r\n", "\n")

MUTATIONS = [
    ("aud condition dropped — any GitHub repo in the world may assume it",
     '                        "token.actions.githubusercontent.com:aud":\n'
     '                            "sts.amazonaws.com",\n',
     "",
     "test_the_audience_claim_is_pinned_to_sts"),

    # ANCHOR UPDATED 2026-08-22, AND THE STALENESS IS THE POINT.
    # This mutation was recorded as applied-and-killed in
    # ci-eval-role-mutations.txt against a `sub` of
    # `repo:andaro74/regdelta:pull_request`. That string stopped existing
    # hours later, when the subject was re-pinned to GitHub's IMMUTABLE
    # form after PR #17 measured the claim actually issued
    # (oidc-claims.txt). The artifact was never re-run, so it went on
    # reading "0 survivors out of 5" about a file that no longer
    # contained what it mutated.
    #
    # Caught at close by re-running it, which is the only reason the
    # evidence pack does not ship a verified-looking claim about code that
    # changed underneath it. It was catchable ONLY because the runner
    # distinguishes NOT APPLIED from KILLED — had it counted an un-applied
    # mutation as a pass, this would have been invisible and permanent.
    # That distinction was built for the CRLF defect noted at the top of
    # this file and it has now paid for itself twice.
    #
    # The PROPERTY is unchanged — no wildcard in the sub, still scoped to
    # the event. Only the string it is written in moved, and the mutation
    # now widens the immutable form exactly as it widened the name form.
    ("sub widened to ...@1322516232:* — any ref in this repo",
     '                            "repo:andaro74@3157440/regdelta@1322516232"\n'
     '                            ":pull_request",',
     '                            "repo:andaro74@3157440/regdelta@1322516232"\n'
     '                            ":*",',
     "test_the_subject_claim_is_scoped_to_the_event_not_just_the_repo"),

    ("the explicit statement replaced by grant_read_data",
     "        ci_eval.add_to_policy(iam.PolicyStatement(\n"
     '            sid="ReadRegistryForCorpusFingerprint",\n'
     '            actions=["dynamodb:Scan"],\n'
     "            resources=[self.registry_table.table_arn]))",
     "        self.registry_table.grant_read_data(ci_eval)",
     "test_it_holds_exactly_one_statement_granting_exactly_one_action"),

    ("repository_id dropped — the sub claim alone survives a rename (L1)",
     '                        "token.actions.githubusercontent.com:repository_id":\n'
     '                            "1322516232",\n',
     "",
     "test_the_repository_is_pinned_by_id_and_not_only_by_name"),

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
        STACK.write_bytes(TEXT.replace(find, repl).encode("utf-8"))
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
