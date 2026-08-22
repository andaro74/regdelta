"""Can tests/test_eval_gate_workflow.py actually refuse anything?

Seven tests passing against the file as it stands proves nothing: a guard is a
hypothesis until something fails against it (ADR-0005), and a permissions test
that reads its expectations off the thing it is checking passes forever
(ADR-0013, and the `EXPECTED_EMBEDDING_TYPE == INDEX_MAPPING[...]` assertion at
M05 that survived mutation C6 by being "knn_vector" == "knn_vector").

So each mutation below breaks one thing the workflow claims about itself and
asserts the NAMED test goes red. A mutation that fails to apply is reported as
un-applied rather than counted as killed — a text edit that matched nothing
would otherwise look exactly like a guard doing its job.

Mutates .github/workflows/evals.yml in place, restores it in a finally, and
verifies the restore byte-for-byte. No API, no AWS, no cost.

    python milestones/M07/workflow_guard_mutations.py
"""
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WF = ROOT / ".github" / "workflows" / "evals.yml"
TESTS = ROOT / "tests" / "test_eval_gate_workflow.py"
ORIGINAL = WF.read_bytes()
TEXT = ORIGINAL.decode("utf-8")

# label -> (find, replace, test that must go red)
MUTATIONS = [
    ("workflow-level grant widened to contents: write",
     "\npermissions:\n  contents: read\n",
     "\npermissions:\n  contents: write\n",
     "test_the_workflow_level_grant_is_the_floor"),

    ("golden-set loses its own permissions block (the REPLACES defect)",
     "    permissions:\n      contents: read\n      pull-requests: write\n"
     "      id-token: write",
     "    # permissions block removed",
     "test_every_job_declares_its_own_permissions"),

    ("unit granted id-token: write it does not need",
     "    permissions:\n      contents: read\n    steps:\n      - uses: actions/checkout@v4\n"
     "      - uses: actions/setup-python@v5\n        with: { python-version: \"3.14\" }",
     "    permissions:\n      contents: read\n      id-token: write\n    steps:\n"
     "      - uses: actions/checkout@v4\n"
     "      - uses: actions/setup-python@v5\n        with: { python-version: \"3.14\" }",
     "test_unit_assumes_no_aws_role_and_reads_no_secrets"),

    ("golden-set loses pull-requests: write while still posting a comment",
     "      contents: read\n      pull-requests: write\n      id-token: write",
     "      contents: read\n      id-token: write",
     "test_each_job_holds_exactly_what_its_steps_need"),

    ("region reverted to us-east-1 against a us-west-2 stack",
     "aws-region: us-west-2",
     "aws-region: us-east-1",
     "test_the_gate_runs_in_the_region_the_stack_is_in"),

    ("REGISTRY_TABLE dropped — the scorecard goes corpus-blind",
     "          REGISTRY_TABLE: ${{ vars.REGISTRY_TABLE }}\n",
     "",
     "test_the_gate_can_fingerprint_the_corpus"),

    ("Enforce stops running on failure, so a failed comment skips the gate",
     "        if: always()",
     "        if: success()",
     "test_the_enforce_step_still_fails_closed"),

    ("the exit code is interpolated into the shell instead of read via env",
     '          exit "$EVAL_RC"',
     "          exit ${{ steps.evals.outputs.exit }}",
     "test_the_enforce_step_still_fails_closed"),
]


def run_test(name):
    p = subprocess.run(
        [sys.executable, "-m", "pytest", f"{TESTS}::{name}", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return p.returncode


print(f"{'mutation':64} {'applied':8} {'killed by named test':22}")
print("-" * 100)
survivors = []
try:
    # The suite must be green before any of this means anything.
    baseline = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS), "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    if baseline.returncode != 0:
        sys.exit(f"the guard is already red before mutation:\n{baseline.stdout[-800:]}")

    for label, find, repl, test in MUTATIONS:
        hits = TEXT.count(find)
        if hits != 1:
            survivors.append(f"{label} (anchor matched {hits}x, not applied)")
            print(f"{label:64} {'NO (' + str(hits) + 'x)':8} {'-- not attributable':22}")
            continue
        WF.write_text(TEXT.replace(find, repl), encoding="utf-8")
        red = run_test(test) != 0
        survivors += [] if red else [label]
        print(f"{label:64} {'yes':8} "
              f"{(test if red else 'SURVIVED: ' + test):22}")
finally:
    WF.write_bytes(ORIGINAL)
    restored = (hashlib.sha256(WF.read_bytes()).hexdigest()
                == hashlib.sha256(ORIGINAL).hexdigest())
    print(f"\nworkflow restored byte-for-byte: {restored}")
    if not restored:
        sys.exit("WORKFLOW NOT RESTORED — fix by hand before committing")

print(f"{len(survivors)} survivor(s) out of {len(MUTATIONS)}"
      f"{': ' + '; '.join(survivors) if survivors else ''}")
sys.exit(1 if survivors else 0)
