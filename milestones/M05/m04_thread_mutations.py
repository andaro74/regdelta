"""Mutation check for the two M04 instrument threads folded into M05.

Same shape as hydration_gate_mutations.py: each entry restores one piece of
the defective behaviour, runs the suite, and records which tests catch it. A
test that survives the mutation of the thing it names is not testing it.

Writes milestones/M05/m04-thread-mutations.json.
"""
import io
import json
import subprocess
import sys

RUN_EVALS = "evals/run_evals.py"
NODES = "src/graph/nodes.py"
TESTS = "tests/test_m04_instrument_threads.py"

MUTATIONS = [
    # ---- thread 3: record() overwriting at one sha
    ("D1 record() overwrites, as it did before", RUN_EVALS, [
        ('    result = {**result, "supersedes": _archive(path)}\n', ""),
    ]),
    ("D2 the losing card is archived beside the winner, not beneath it",
     RUN_EVALS, [
        ('SUPERSEDED_DIRNAME = "superseded"', 'SUPERSEDED_DIRNAME = "."'),
     ]),
    ("D3 the file is kept but the card does not say so", RUN_EVALS, [
        ('    result = {**result, "supersedes": _archive(path)}',
         '    _archive(path)\n    result = {**result, "supersedes": []}'),
    ]),
    # ---- thread 4: stopReason discarded in the agent path
    ("E1 _text_of throws the stop reason away again", NODES, [
        ('    _last_stop["reason"] = resp.get("stopReason")\n', ""),
    ]),
    ("E2 no reset, so a stale reason leaks into the next verdict", NODES, [
        ("    reset_stop_reason()\n    raw = (invoke or _converse)(",
         "    raw = (invoke or _converse)("),
    ]),
    ("E3 unobserved reported as not-truncated", NODES, [
        ('"truncated": (stop == "max_tokens") if stop else None,',
         '"truncated": stop == "max_tokens",'),
    ]),
    ("E4 verdict drops the fields on the floor", NODES, [
        ('''        "stop_reason": stop,
        "truncated": (stop == "max_tokens") if stop else None,
''', ""),
    ]),
]


def failing_tests() -> list[str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "--no-header", "-rf",
         "--tb=no"],
        capture_output=True, text=True)
    out = p.stdout + p.stderr
    names = sorted({
        line.split("::")[-1].split(" ")[0]
        for line in out.splitlines() if line.startswith("FAILED ")
    })
    if p.returncode == 0:
        return []
    return names or [f"<collection or import error, rc={p.returncode}>"]


def main() -> int:
    originals = {p: io.open(p, encoding="utf-8").read()
                 for p in (RUN_EVALS, NODES)}
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
    io.open("milestones/M05/m04-thread-mutations.json", "w",
            encoding="utf-8").write(json.dumps(results, indent=2))
    survivors = [k for k, v in results.items() if not v]
    print("\nSURVIVED (mutation caused no failure):", survivors or "none")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
