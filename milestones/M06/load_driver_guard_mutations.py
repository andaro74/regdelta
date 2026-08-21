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

THE SECOND FAMILY EXISTS BECAUSE THE FIRST ONE WAS BIASED. M1-M7 all *widen* a
grant or *break* a behaviour some test already asserts positively, and
security-reviewer's verdict on them was that none is a specimen written to pass
— but that **not one of them removes a grant**. That asymmetry is not academic:
`granted <= allowed` and every membership assertion stay green when a grant
simply vanishes, and the reviewer demonstrated it by deleting the driver's
`aoss:APIAccessAll` and watching the entire suite pass.

AND THE THIRD BIAS, FOUND THE SAME WAY. R and T are both still "does an
existing guard notice a change to code it already reads." Neither family can
surface a property NO guard asserts — there is nothing to mutate for a clause
that was never written — so the harness measured guard STRENGTH and never guard
COVERAGE. security-reviewer found the gap by writing the mutations this file
did not contain: `t.join(timeout=120)` -> `timeout=0`, deleting the driver's
entire wait-for-stragglers behaviour, and the whole driver test file stayed
green. Every assertion in it was stated relative to `returned`, and the one use
of `dispatched` never compared the two.

So there is now an S family — "the sample set is complete" — and the clause
that kills it. S1 and S2 are security-reviewer's own two, kept verbatim.

A MISSING grant is the milestone's worst case, not a benign one. The driver
would take a bare 403 on every AOSS call, `router._resolve` would fall back to
S3 Vectors silently and by design, and the Tier B half of a disposition whose
DEFAULT OUTCOME IS RETIREMENT would carry Tier A's latencies with zero errors.
So R1-R8 remove one grant each, and T1-T5 attack the check that now refuses
that run.

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
DRIVER_TEST = "tests/test_retrieval_load_driver.py"
DRIVER = ROOT / "src" / "ops" / "retrieval_load.py"

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

    # ------------------------------------------------------------ R: removals
    # One grant deleted per mutation. THE GUARD MUST NOTICE AN ABSENCE, which
    # is the half `granted <= allowed` and every membership assertion are blind
    # to.

    ("R1-driver-loses-its-aoss-iam-grant", SEARCH, ACCESS_TEST,
     """        driver_role = iam.Role.from_role_arn(
            self, "LoadDriverRole", load_driver_role_arn, mutable=True)
        driver_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))""",
     "",
     "SECURITY-REVIEWER'S M8, and the reason this family exists: deleting "
     "these four lines left the ENTIRE SUITE green. The data-access policy is "
     "the sufficient half and IAM is the necessary half; without it every AOSS "
     "call is denied, the router falls back silently, and Tier B is retired on "
     "Tier A's numbers"),

    ("R2-query-role-loses-its-aoss-iam-grant", SEARCH, ACCESS_TEST,
     """        query_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))""",
     "",
     "the same absence on the role that has carried the grant since SPEC/05 — "
     "the parameterised family must cover both roles, not just the new one"),

    ("R3-driver-drops-out-of-index-readers", SEARCH, ACCESS_TEST,
     "        index_readers = [query_lambda_role_arn, load_driver_role_arn]",
     "        index_readers = [query_lambda_role_arn]",
     "the other necessary half. An IAM grant with no data-access entry is the "
     "same bare 403 by the other route"),

    ("R4-driver-loses-the-embedding-grant", CORE, IAM_TEST,
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[self._embed_model_arn()]))""",
     "",
     "every retrieval embeds; without this every call fails identically on "
     "BOTH tiers, which is the one failure mode that would read as a tie — and "
     "ties retire"),

    ("R5-driver-loses-the-ssm-grant", CORE, IAM_TEST,
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(
                service="ssm", resource="parameter",
                resource_name=SSM_ENDPOINT_PARAM.lstrip("/"))]))""",
     "",
     "the router reads the endpoint parameter to pick a tier; denied, it "
     "resolves to S3 Vectors and both halves measure Tier A"),

    ("R6-driver-loses-a-vector-index-action", CORE, IAM_TEST,
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["s3vectors:QueryVectors", "s3vectors:GetVectors"],""",
     """        load_driver.add_to_role_policy(iam.PolicyStatement(
            actions=["s3vectors:GetVectors"],""",
     "the Tier A half's own backend, removed one action at a time — the shape "
     "a subset bound cannot see"),

    ("R7-driver-loses-the-registry-read", CORE, IAM_TEST,
     "        self.registry_table.grant_read_data(load_driver)\n",
     "",
     "`retrieval/expansion.py` reads the registry on the retrieval path, so a "
     "driver without it measures a retrieval that half-failed — on both tiers, "
     "equally, which again reads as a tie"),

    ("R8-driver-picks-up-a-managed-policy", CORE, IAM_TEST,
     "        enable_xray(load_driver)",
     "        enable_xray(load_driver)\n"
     "        load_driver.role.add_managed_policy(\n"
     "            iam.ManagedPolicy.from_aws_managed_policy_name("
     '"AdministratorAccess"))',
     "the M04 finding on QueryFn, which this role did not inherit until now: "
     "every inline-policy assertion in the file reads identically with "
     "AdministratorAccess attached"),

    # ------------------------------------------------------ T: the tier check
    # The guard that stops a Tier B run which never reached Tier B from being
    # recorded as one. The clause's default outcome is retirement, so a false
    # pass here is the most expensive single failure in the milestone.

    ("T1-eligibility-ignores-the-tier", DRIVER, DRIVER_TEST,
     '    eligible = (within and retries["total"] == 0 and tier_ok and complete\n'
     '                and bool(latencies))',
     '    eligible = (within and retries["total"] == 0 and complete\n'
     '                and bool(latencies))',
     "the state the code was in when security-reviewer measured it: "
     "tiers_observed ['s3vectors'], errors 0, dispositive_eligible true, on a "
     "step pointed at aoss"),

    ("T2-tier-check-becomes-a-membership-test", DRIVER, DRIVER_TEST,
     "    return tiers_observed == [expected]",
     "    return expected in tiers_observed",
     "a partial propagation delay makes SOME calls fall back; a membership "
     "test accepts a p95 computed over a mixture of both tiers and labelled as "
     "one of them"),

    ("T3-a-fallback-reason-stops-counting", DRIVER, DRIVER_TEST,
     "    tier_ok = _tier_is_as_asked(tiers, expected_tier) and not fallbacks",
     "    tier_ok = _tier_is_as_asked(tiers, expected_tier)",
     "a per-call fallback that lands back on the expected tier still means the "
     "router did not do what was asked"),

    ("T4-the-handler-guesses-the-expected-tier", DRIVER, DRIVER_TEST,
     '                      expected_tier=str(event["expected_tier"]),',
     "                      expected_tier=str(event.get('expected_tier') or "
     "router.active_tier()),",
     "defaulting to active_tier() compares the SSM parameter against itself "
     "and passes for any fallback at all — the assertion becomes a tautology"),

    # ------------------------------------------ S: is the sample set complete
    # THE FAMILY THE OTHER TWO COULD NOT CONTAIN. A dropped call is in no
    # sample at all, so it is invisible in `n` AND in the error rate, and the
    # p95 becomes a statistic about the calls that survived — the sample
    # exclusion the amended clause refuses in writing, performed invisibly and
    # biased toward the tier that failed more.

    ("S1-stragglers-are-abandoned", DRIVER, DRIVER_TEST,
     "        t.join(timeout=JOIN_TIMEOUT_S)",
     "        t.join(timeout=0)",
     "SECURITY-REVIEWER'S OWN, kept verbatim: deleting the driver's entire "
     "wait-for-stragglers behaviour left the whole driver test file green, "
     "because every assertion in it was relative to `returned` and nothing "
     "compared `returned` to `dispatched`"),

    ("S2-only-a-tenth-of-the-calls-are-waited-for", DRIVER, DRIVER_TEST,
     "    for t in threads:\n        t.join(timeout=JOIN_TIMEOUT_S)",
     "    for t in threads[:max(1, len(threads) // 10)]:\n"
     "        t.join(timeout=JOIN_TIMEOUT_S)",
     "the same defect as a subset rather than as a wholesale drop: a p95 over "
     "whichever tenth happened to be waited for"),

    ("S3-eligibility-stops-requiring-a-complete-account", DRIVER, DRIVER_TEST,
     "    complete = returned == dispatched and dispatched > 0",
     "    complete = True",
     "the clause the S family exists to protect. Measured before it existed: "
     "2 of 20 calls returned, error_rate 0.0, dispositive_eligible true"),

    ("S4-a-step-with-no-successful-call-is-eligible", DRIVER, DRIVER_TEST,
     "    eligible = (within and retries[\"total\"] == 0 and tier_ok and complete\n"
     "                and bool(latencies))",
     "    eligible = (within and retries[\"total\"] == 0 and tier_ok and complete)",
     "every call raised: a complete account, a real fact about the tier, and "
     "no latency measurement at all"),

    ("S5-the-throttle-exclusion-goes-away", DRIVER, DRIVER_TEST,
     "    eligible = (within and retries[\"total\"] == 0 and tier_ok and complete",
     "    eligible = (within and tier_ok and complete",
     "the amended clause's other completion condition, and the module "
     "docstring calls it load-bearing: `shared.util.retry` absorbs a Titan "
     "throttle into 2/4/8 seconds of sleep INSIDE the measured interval"),

    ("S6-coordinated-omission-stops-disqualifying", DRIVER, DRIVER_TEST,
     "    eligible = (within and retries[\"total\"] == 0",
     "    eligible = (retries[\"total\"] == 0",
     "'a driver that could not keep up must be distinguishable from a tier "
     "that was fast' — the third conjunct, unmutated until now"),

    ("T5-the-fallback-list-is-uncapped-again", DRIVER, DRIVER_TEST,
     '        "fallbacks": len(fallbacks),\n'
     '        "fallback_sample": fallbacks[:5],',
     '        "fallbacks": fallbacks,',
     "5,400 reasons of up to 300 characters on ONE CloudWatch log event, which "
     "caps at 256 KiB: the record is truncated and span_status, error_rate and "
     "dispositive_eligible are what get lost"),
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
