"""Mutation check for the M05 hydration gate.

Each entry restores one piece of the pre-gate behaviour (or breaks one claim),
runs the suite, and records WHICH tests failed. A test that survives its own
mutation is not testing what it says it is.
"""
import io
import json
import subprocess
import sys

REINDEX = "src/retrieval/reindex.py"
STACK = "infra/search/search_stack.py"
GATE = "evals/check_hydration.py"

MUTATIONS = [
    # ---- the inside: reindex.py
    ("A1 no retire (parameter stays up during the rebuild)", REINDEX, [
        ("    retired = _retire_endpoint()\n", "    retired = False\n"),
    ]),
    ("A2 publish BEFORE the assertions (restores the M02 bug)", REINDEX, [
        ("""    _assert_knn_mapping(endpoint)

    # Both assertions passed. Only now does the hot tier exist as far as
    # `router.active_endpoint()` is concerned.
    _publish_endpoint(endpoint)
""", "    _assert_knn_mapping(endpoint)\n"),
        ("    _create_index(endpoint)\n\n    source = 0",
         "    _create_index(endpoint)\n    _publish_endpoint(endpoint)\n\n    source = 0"),
    ]),
    ("A3 publish without Overwrite", REINDEX, [
        ('        Overwrite=True,\n', ''),
    ]),
    ("A4 reindex spells the parameter name itself", REINDEX, [
        ("Name=config.SSM_SEARCH_ENDPOINT", 'Name="/regdelta/search/endpoint"'),
    ]),
    # ---- the template: search_stack.py
    ("B1 trigger no longer ordered after the parameter", STACK, [
        ("execute_after=[access, endpoint_param],", "execute_after=[access],"),
    ]),
    ("B2 no ssm grant on the reindex role", STACK, [
        ("""        reindex.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:PutParameter", "ssm:DeleteParameter"],
            resources=[self.format_arn(
                service="ssm", resource="parameter",
                resource_name=SSM_ENDPOINT_PARAM.lstrip("/"))]))
""", ""),
    ]),
    ("B3 ssm grant widened to every /regdelta parameter", STACK, [
        ('resource_name=SSM_ENDPOINT_PARAM.lstrip("/"))]))',
         'resource_name="regdelta/*")]))'),
    ]),
    # ---- the outside: check_hydration.py
    ("C1 short count is a warning, not a refusal", GATE, [
        ('        if counted and report["indexed"] != report["corpus"]:',
         '        if False and counted:'),
    ]),
    ("C2 mapping never checked", GATE, [
        ('        attempt("embedding_type", lambda: check_mapping(report["endpoint"]))',
         '        report["embedding_type"] = "knn_vector"'),
    ]),
    ("C3 endpoint read without dropping the 60s cache", GATE, [
        ("    router.reset_cache()\n", ""),
    ]),
    ("C4 stops at the first refusal", GATE, [
        ('''        except RefusalError as e:
            report["refusals"].append({"check": name, "reason": str(e)})
            return False''',
         '''        except RefusalError as e:
            if not report["refusals"]:
                report["refusals"].append({"check": name, "reason": str(e)})
            return False'''),
    ]),
    ("C5 empty corpus passes 0 == 0", GATE, [
        ("    if n == 0:", "    if False:"),
    ]),
    ("C6 guard holds its own copy of the expected mapping type", GATE, [
        ('''EXPECTED_EMBEDDING_TYPE = (
    aoss_client.INDEX_MAPPING["mappings"]["properties"]["embedding"]["type"])''',
         'EXPECTED_EMBEDDING_TYPE = "knn_vector"'),
    ]),
    ("C7 absent endpoint accepted", GATE, [
        ("    if not endpoint:", "    if False:"),
    ]),
]


def failing_tests() -> list[str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_hydration_gate.py",
         "-q", "--no-header", "-rf", "--tb=no"],
        capture_output=True, text=True)
    out = p.stdout + p.stderr
    names = sorted({
        line.split("::")[-1].split(" ")[0]
        for line in out.splitlines() if line.startswith("FAILED ")
    })
    if p.returncode == 0:
        return []
    if not names:
        return [f"<collection or import error, rc={p.returncode}>"]
    return names


def main() -> int:
    originals = {p: io.open(p, encoding="utf-8").read()
                 for p in (REINDEX, STACK, GATE)}
    results = {}
    try:
        for name, path, edits in MUTATIONS:
            src = originals[path]
            for old, new in edits:
                if old not in src:
                    print(f"!! {name}: anchor not found -> {old[:60]!r}")
                    results[name] = ["<ANCHOR NOT FOUND>"]
                    break
                src = src.replace(old, new, 1)
            else:
                io.open(path, "w", encoding="utf-8", newline="\n").write(src)
                results[name] = failing_tests()
                io.open(path, "w", encoding="utf-8",
                        newline="\n").write(originals[path])
            print(f"{name}\n   -> {results.get(name)}")
    finally:
        for p, s in originals.items():
            io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    io.open("milestones/M05/hydration-gate-mutations.json", "w",
            encoding="utf-8").write(
        json.dumps(results, indent=2))
    survivors = [k for k, v in results.items() if not v]
    print("\nSURVIVED (mutation caused no failure):", survivors or "none")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
