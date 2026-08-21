"""Mutations against the guards added for SPEC/06's load driver.

A guard that has never refused anything is a guard nobody has checked
(ADR-0013). Each mutation below is a plausible edit — several of them the
OBVIOUS edit — that breaks a property one of these guards claims to protect.
Every one must turn the guard RED. A survivor means the guard is decoration.

Three of the four guards here are about IAM, and IAM does not read comments.
The driver's blast radius is stated at length in `tests/test_load_driver_iam.py`
and in `infra/core/core_stack.py`; this file is what makes those statements
checkable:

  * M1 is the obvious edit — reuse `_bedrock_model_arns()`, which is right
    there and returns the list every other Lambda uses. It hands a
    90-call-per-second driver a grant on Opus 4.6.
  * M3 is a one-word edit: `index_writers` instead of `index_readers`.
  * M5 removes the `finally` from the span sink, which is the difference
    between "every errored call reported its span status" and "every errored
    call was reported as having emitted nothing".

Offline, free, no AWS: every guard here reads a synthesised CloudFormation
template or runs an in-process node. Every mutation is applied to a copy of the
file's text and reverted in a `finally`, so a crash cannot leave the tree
edited — and the run re-checks that the tree came back green.

Run: python milestones/M06/load_driver_guard_mutations.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "infra" / "core" / "core_stack.py"
SEARCH = ROOT / "infra" / "search" / "search_stack.py"
OBS = ROOT / "infra" / "core" / "observability.py"
INSTRUMENT = ROOT / "src" / "graph" / "instrument.py"

IAM_TEST = "tests/test_load_driver_iam.py"
ACCESS_TEST = "tests/test_search_stack_access.py"
JANITOR_TEST = "tests/test_janitor.py"
SINK_TEST = "tests/test_instrument_span_sink.py"

#: (id, file, guard, find, replace, why it must be caught)
MUTATIONS = [
    ("M1-driver-gets-every-model", CORE, IAM_TEST,
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[self._embed_model_arn()]))""",
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=self._bedrock_model_arns()))""",
     "THE obvious edit: the helper every other Lambda uses is right there and "
     "returns five ARNs including Opus 4.6. One minute of Opus at this "
     "account's per-minute quota is $23.63 and exceeds a NON-ADJUSTABLE daily "
     "cap, and the driver dispatches 90 calls a second"),

    ("M2-driver-loses-tracing", CORE, IAM_TEST,
     "        enable_xray(load_driver)\n",
     "",
     "SPEC/06 defines the measured interval as the one carried on the per-node "
     "span; with no daemon every span reads `off` and the report measures "
     "nothing the clause names"),

    ("M3-driver-becomes-an-index-writer", SEARCH, ACCESS_TEST,
     "        index_readers = [query_lambda_role_arn, load_driver_role_arn]",
     "        index_writers.append(load_driver_role_arn)\n"
     "        index_readers = [query_lambda_role_arn]",
     "one word. The driver would hold aoss:* — DeleteIndex and WriteDocument "
     "on the corpus index the cited deadlines are drawn from"),

    ("M4-janitor-cannot-detach-the-driver", CORE, JANITOR_TEST,
     """        search_deleter.add_to_policy(iam.PolicyStatement(
            actions=["iam:DeleteRolePolicy", "iam:GetRolePolicy"],
            resources=[load_driver.role.role_arn]))""",
     "",
     "the M05 defect, one role along: regdelta-search attaches a policy to "
     "this core-owned role, so DeleteStack under the janitor's role takes "
     "AccessDenied, lands in DELETE_FAILED, and a collection bills all night. "
     "Invisible in dev — `make down` runs as the bootstrap admin role"),

    ("M5-span-sink-only-fires-on-success", INSTRUMENT, SINK_TEST,
     """        finally:
            # `span is not None` guards the window before `node_span` yields.
            # Nothing there can raise today; a NameError in a `finally` would
            # replace the node's real exception with a lie about this shim.
            if on_span is not None and span is not None:
                on_span(span.span_result)
        return result""",
     """        except Exception:
            raise
        if on_span is not None and span is not None:
            on_span(span.span_result)
        return result""",
     "an errored retrieval still emits its span — that is node_span's own "
     "argument — so a success-only sink reports every failed call as having "
     "emitted nothing, which is a false claim in the report the clause asks for"),

    ("M6-span-sink-reads-a-stale-result", INSTRUMENT, SINK_TEST,
     """        span = None
        try:
            with observability.node_span(name) as span:
                result = fn(state, *args, **kwargs)
                _carry(span, result if isinstance(result, dict) else {})""",
     """        span = None
        try:
            with observability.node_span(name) as span:
                result = fn(state, *args, **kwargs)
                _carry(span, result if isinstance(result, dict) else {})
                on_span and on_span(span.span_result)""",
     "`span_result` is assigned in node_span's own `finally`; a sink called "
     "from INSIDE the with-block reads the initial ('off', None) every time — "
     "a report saying the spans never left while the datagrams went out"),

    ("M7-xray-exemption-grows", OBS, IAM_TEST,
     '        actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"],',
     '        actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords",\n'
     '                 "xray:GetSamplingRules", "xray:GetSamplingTargets"],',
     "the four actions CDK's own Tracing.ACTIVE would attach. The wildcard "
     "exemption is pinned at two and has to be argued for to grow; picking up "
     "two more as a side effect is the widening the pin exists to stop"),
]


def run_guard(test: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    return proc.returncode, (proc.stdout + proc.stderr)[-800:]


def main() -> int:
    guards = sorted({m[2] for m in MUTATIONS})
    baseline = {}
    for guard in guards:
        rc, out = run_guard(guard)
        baseline[guard] = rc
        if rc != 0:
            print(f"BASELINE IS RED for {guard} — fix it before mutating it.")
            print(out)
            return 2
    print("baseline: green for " + ", ".join(guards) + "\n")

    results = []
    for mid, path, guard, find, replace, why in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if find not in original:
            results.append({"id": mid, "guard": guard, "outcome": "NOT-APPLIED",
                            "detail": "anchor text not found; the mutation does "
                                      "not describe today's source",
                            "why": why})
            print(f"  {mid:36s} NOT-APPLIED  (anchor missing)")
            continue
        try:
            path.write_text(original.replace(find, replace, 1), encoding="utf-8")
            rc, out = run_guard(guard)
        finally:
            path.write_text(original, encoding="utf-8")
        outcome = "killed" if rc != 0 else "SURVIVED"
        results.append({"id": mid, "guard": guard, "outcome": outcome,
                        "exit": rc, "why": why, "tail": out if rc == 0 else None})
        print(f"  {mid:36s} {outcome:9s} ({guard})")

    after = {g: run_guard(g)[0] for g in guards}
    survivors = [r for r in results if r["outcome"] != "killed"]
    report = {
        "guards": guards,
        "baseline_green": all(v == 0 for v in baseline.values()),
        "tree_restored_and_green": all(v == 0 for v in after.values()),
        "mutations": len(MUTATIONS),
        "survivors": len(survivors),
        "results": results,
    }
    out_path = Path(__file__).with_suffix(".json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed  "
          f"-> {out_path.name}")
    if not report["tree_restored_and_green"]:
        print("!! the tree did not come back green — check `git diff`")
        return 3
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
