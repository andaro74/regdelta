"""Mutation check for the fixes made after the two M05 review passes.

Each entry restores the pre-review behaviour and records which tests catch it.
Writes milestones/M05/review-fix-mutations.json.
"""
import io
import json
import subprocess
import sys

JANITOR = "infra/lambdas/janitor/handler.py"
LOCAL_ENV = "evals/local_env.py"
API = "src/api/api.py"
SHIM = "evals/serve_local.py"
STACK_TEST_TARGET = "infra/core/core_stack.py"

SHAPE_FIELDS = '''        "stop_reason": state.get("stop_reason"),
        "truncated": state.get("truncated"),
'''

MUTATIONS = [
    ("H1 janitor matches the phrase without the error code", JANITOR, [
        ('        code = e.response.get("Error", {}).get("Code")\n'
         '        if code != "ValidationError" or "does not exist" not in str(e):',
         '        if "does not exist" not in str(e):'),
    ], "tests/test_janitor.py"),
    ("H2 the update CLEANUP transients fall out of _IN_FLIGHT", JANITOR, [
        ('              "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",\n'
         '              "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS")',
         ')'),
    ], "tests/test_janitor.py"),
    ("H3 UPDATE_FAILED / IMPORT_ROLLBACK_FAILED leave the deletable set",
     JANITOR, [
        ('    "UPDATE_FAILED",\n    "IMPORT_ROLLBACK_FAILED",\n', ""),
     ], "tests/test_janitor.py"),
    ("H4 the deletion-role walk only sees AWS::IAM::Policy again",
     "tests/test_janitor.py", [
        ('    attaches_to_roles = ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",\n'
         '                         "AWS::IAM::RolePolicy")',
         '    attaches_to_roles = ("AWS::IAM::Policy",)'),
     ], "tests/test_janitor.py"),
    ("I1 local_env stops filtering the settable redirects", LOCAL_ENV, [
        ('             "AWS_CONTAINER", "AWS_SHARED", "AWS_CONFIG", "AWS_WEB_IDENTITY",\n'
         '             "AWS_ROLE", "NODE_", "BASH_ENV", "ENV", "PERL", "RUBYOPT")',
         ')'),
    ], "tests/test_local_env_filter.py"),
    ("I2 local_env stops quoting values", LOCAL_ENV, [
        ('print(f"export {k}={shlex.quote(str(v))}")',
         'print(f"export {k}={v}")'),
    ], "tests/test_local_env_filter.py"),
    ("J1 stop_reason dropped from the API shape", API, [
        (SHAPE_FIELDS, ""),
    ], "tests/test_answering_tier.py"),
    ("J2 stop_reason dropped from the shim shape", SHIM, [
        (SHAPE_FIELDS, ""),
    ], "tests/test_answering_tier.py"),
]


def failing(test_file: str) -> list[str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-q", "--no-header", "-rf",
         "--tb=no"], capture_output=True, text=True)
    out = p.stdout + p.stderr
    names = sorted({line.split("::")[-1].split(" ")[0]
                    for line in out.splitlines() if line.startswith("FAILED ")})
    if p.returncode == 0:
        return []
    return names or [f"<error rc={p.returncode}>"]


def main() -> int:
    paths = {m[1] for m in MUTATIONS}
    originals = {p: io.open(p, encoding="utf-8").read() for p in paths}
    results = {}
    try:
        for name, path, edits, test_file in MUTATIONS:
            src = originals[path]
            for old, new in edits:
                if old not in src:
                    print(f"!! {name}: anchor not found")
                    results[name] = ["<ANCHOR NOT FOUND>"]
                    break
                src = src.replace(old, new, 1)
            else:
                io.open(path, "w", encoding="utf-8", newline="\n").write(src)
                results[name] = failing(test_file)
                io.open(path, "w", encoding="utf-8",
                        newline="\n").write(originals[path])
            print(f"{name}\n   -> {results.get(name)}")
    finally:
        for p, s in originals.items():
            io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    io.open("milestones/M05/review-fix-mutations.json", "w",
            encoding="utf-8").write(json.dumps(results, indent=2))
    survivors = [k for k, v in results.items() if not v]
    print("\nSURVIVED:", survivors or "none")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
