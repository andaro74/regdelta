"""Mutations against tests/test_graph_state_declares_node_outputs.py.

A guard that has never refused anything is a guard nobody has checked. Each
mutation below breaks the property the guard claims to protect; the guard must
go RED for every one. A survivor means the guard is decoration.

Offline, free, no AWS. Every mutation is applied to a copy of the tree and
reverted in a `finally`, so a crash cannot leave the working tree edited.

Run: python milestones/M06/state_declaration_mutations.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "src" / "graph" / "state.py"
NODES = ROOT / "src" / "graph" / "nodes.py"
GRAPH = ROOT / "src" / "graph" / "graph.py"
TEST = "tests/test_graph_state_declares_node_outputs.py"

#: (id, file, find, replace, why it must be caught)
MUTATIONS = [
    ("M1-undeclare-stop-reason", STATE,
     "    stop_reason: str | None\n    truncated: bool | None\n",
     "    truncated: bool | None\n",
     "the exact M05 defect: verdict returns stop_reason, the schema does not "
     "declare it, LangGraph drops it and the API reports null"),

    ("M2-undeclare-truncated", STATE,
     "    truncated: bool | None\n",
     "",
     "the sibling field, lost the same way"),

    ("M3-undeclare-retrieval-ms", STATE,
     "    retrieval_ms: float | None\n",
     "",
     "SPEC/04's UI readout and SPEC/06's whole disposition measurement read "
     "this field; undeclared, it is silently null"),

    ("M4-new-undeclared-key-on-a-node", NODES,
     '    return {\n        "answer": answer,',
     '    return {\n        "spec06_tokens_placeholder": 1,\n        "answer": answer,',
     "the next field added to a node without a schema entry — the general "
     "case the guard exists for"),

    ("M5-node-returns-a-non-literal", NODES,
     "    return {\"company_profile\": profile,",
     "    return dict(_built_elsewhere) or {\"company_profile\": profile,",
     "a return shape the walker cannot read must FAIL, not be skipped — a "
     "walker that silently skips reports 'all declared' about code it never "
     "examined"),

    ("M6-unregister-a-node", GRAPH,
     '    builder.add_node("verdict", nodes.verdict)\n',
     "",
     "the node list is derived from graph.py; dropping a registration must "
     "not quietly shrink what the guard checks"),
]


def run_guard() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    return proc.returncode, (proc.stdout + proc.stderr)[-600:]


def main() -> int:
    baseline_rc, baseline_out = run_guard()
    if baseline_rc != 0:
        print("BASELINE IS RED — fix the guard before mutating it.")
        print(baseline_out)
        return 2
    print(f"baseline: green ({TEST})\n")

    results = []
    for mid, path, find, replace, why in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if find not in original:
            results.append({"id": mid, "outcome": "NOT-APPLIED",
                            "detail": "anchor text not found; the mutation "
                                      "does not describe today's source",
                            "why": why})
            print(f"  {mid:34s} NOT-APPLIED  (anchor missing)")
            continue
        try:
            path.write_text(original.replace(find, replace, 1), encoding="utf-8")
            rc, out = run_guard()
        finally:
            path.write_text(original, encoding="utf-8")
        outcome = "killed" if rc != 0 else "SURVIVED"
        results.append({"id": mid, "outcome": outcome, "exit": rc,
                        "why": why, "tail": out if rc == 0 else None})
        print(f"  {mid:34s} {outcome}")

    after_rc, _ = run_guard()
    survivors = [r for r in results if r["outcome"] != "killed"]
    report = {
        "guard": TEST,
        "baseline_green": baseline_rc == 0,
        "tree_restored_and_green": after_rc == 0,
        "mutations": len(MUTATIONS),
        "survivors": len(survivors),
        "results": results,
    }
    out_path = Path(__file__).with_suffix(".json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed  "
          f"-> {out_path.name}")
    if after_rc != 0:
        print("!! the tree did not come back green — check `git diff`")
        return 3
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
