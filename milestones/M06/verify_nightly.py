"""Run the nightly check and record what it returned.

`pm-spec-reviewer` blocker B8: the nightly amendment's only load-bearing claim
— "verified live, 2026-08-20, for $0: 52 documents, 3/3 dated, no Bedrock
call" — cited neither a file nor a command, in a document where every other
measurement names an artifact a reader can check. A remembered result is not
evidence.

## Two runs, and the distinction is the point

`in_process` runs `ops.nightly.handler` here against the deployed environment.
That is what "verified live" actually meant last session and what the record
should have said: the same code and the same AWS reads, but NOT the Lambda's
own IAM role and NOT EMF reaching CloudWatch.

`deployed` invokes the real `NightlyCheckFn` and exercises both. It is skipped,
with the artifact saying so, when the stack has no such function — which was
the case when this script was first written, before the M06 window deployed it.

**Neither proves the EventBridge schedule fires.** A manual invoke cannot, and
no number of them will; that is owed at the first unattended 02:00 UTC run. The
artifact says which of the three is still open rather than letting "deployed
and invoked" stand in for "scheduled and fired".

## Free, and demonstrably so

DynamoDB reads, one SSM read, one CloudWatch `GetMetricStatistics`. No Bedrock,
no S3 Vectors query, no AOSS query. The artifact records the Bedrock token
counters before and after: if this function ever grows a model call, the
difference stops being zero and the claim stops being true.

Run with the deployed environment resolved:

    eval "$(python evals/local_env.py)"
    python milestones/M06/verify_nightly.py
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import check_opus_headroom as opus  # noqa: E402

from ops import nightly  # noqa: E402
from shared import config  # noqa: E402

OUT = Path(__file__).with_name("nightly-verification.json")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, cwd=ROOT).strip()
    except Exception:                              # noqa: BLE001
        return "nogit"


def deployed_function() -> str | None:
    """`NightlyCheckFn`'s physical name, or None if the stack has no such
    resource. Absent is a fact about the account, not an error."""
    try:
        names = subprocess.check_output(
            ["aws", "cloudformation", "describe-stack-resources",
             "--stack-name", "regdelta-core", "--region", config.REGION,
             "--query", "StackResources[?ResourceType=='AWS::Lambda::Function']"
                        ".PhysicalResourceId", "--output", "text"],
            text=True, cwd=ROOT).split()
    except Exception:                              # noqa: BLE001
        return None
    return next((n for n in names if "NightlyCheckFn" in n), None)


def invoke_deployed(name: str) -> dict:
    """Invoke the real function and return what it returned.

    THIS IS THE HALF THE IN-PROCESS RUN CANNOT DO. It exercises the Lambda's
    own IAM role and EMF reaching CloudWatch — two of the three things the
    nightly amendment recorded as unexercised. The third, EventBridge actually
    firing on schedule, is still not proven by a manual invoke and the record
    below says so.
    """
    import base64
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "nightly.json"
        proc = subprocess.run(
            ["aws", "lambda", "invoke", "--function-name", name,
             "--region", config.REGION, "--payload", "e30=",  # {} in base64
             "--log-type", "Tail", str(out)],
            capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            return {"error": proc.stderr.strip()[:600]}
        meta = json.loads(proc.stdout or "{}")
        payload = json.loads(out.read_text(encoding="utf-8") or "null")

    record = {
        "function": name,
        "status_code": meta.get("StatusCode"),
        "function_error": meta.get("FunctionError"),
        "payload": payload,
    }
    if meta.get("LogResult"):
        tail = base64.b64decode(meta["LogResult"]).decode("utf-8", "replace")
        # The EMF line is the evidence that metrics leave through stdout rather
        # than a PutMetricData grant the role does not hold.
        record["emf_lines"] = [ln for ln in tail.splitlines()
                               if '"_aws"' in ln][:4]
        record["log_tail"] = tail[-1200:]
    return record


def main() -> int:
    if not config.REGISTRY_TABLE:
        print("REGISTRY_TABLE is unset — run `eval \"$(python evals/local_env.py)\"` "
              "first. Refusing to record a verification of an unconfigured run.",
              file=sys.stderr)
        return 1

    # THE COST CLAIM, MEASURED RATHER THAN ASSERTED. If the nightly ever grows
    # a model call, this difference stops being zero.
    before = opus.spent_today(config.MODEL_VERDICT)
    result = nightly.handler({}, None)
    after = opus.spent_today(config.MODEL_VERDICT)

    fn = deployed_function()
    deployed = invoke_deployed(fn) if fn else None

    record = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha": git_sha(),
        "how": "TWO RUNS, and the distinction is the point. `in_process` is "
               "`ops.nightly.handler` called here against the deployed "
               "environment — same code, same AWS reads, but NOT the Lambda's "
               "own IAM role or EMF. `deployed` is an invocation of the real "
               "NightlyCheckFn, which exercises both. NEITHER proves the "
               "EventBridge schedule fires on its own; that is still owed and "
               "a manual invoke cannot supply it.",
        "deployed": deployed,
        "deployed_note": ("NightlyCheckFn was NOT deployed when this artifact "
                          "was first written on 2026-08-21; the M06 window "
                          "deployed it later the same day. The earlier record "
                          "said so and this one supersedes it."
                          if deployed else
                          "NightlyCheckFn is not in regdelta-core. Only the "
                          "in-process half exists."),
        "command": 'eval "$(python evals/local_env.py)" && '
                   "python milestones/M06/verify_nightly.py",
        "region": config.REGION,
        "registry_table": config.REGISTRY_TABLE,
        "opus_tokens_before": before,
        "opus_tokens_after": after,
        "opus_tokens_spent": after - before,
        "cost_claim": "the nightly makes no Bedrock call; `opus_tokens_spent` "
                      "is the measurement of that, not a restatement of it",
        "result": result,
    }
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    logic = result.get("graph_logic") or {}
    corpus = result.get("corpus") or {}
    print(f"status            : {result.get('status')}")
    print(f"tier              : {result.get('tier')}")
    print(f"corpus            : {corpus.get('documents')} documents, "
          f"sha {corpus.get('documents_sha')}")
    print(f"graph logic       : {len(logic.get('checked') or [])} checked, "
          f"{len(logic.get('undated') or [])} undated, "
          f"{len(logic.get('errors') or [])} errors")
    print(f"eval staleness    : {result.get('eval_staleness')}")
    print(f"Opus tokens spent : {after - before}")
    if deployed:
        print(f"deployed invoke   : {deployed.get('function')} -> "
              f"status {deployed.get('status_code')}, "
              f"error {deployed.get('function_error')}, "
              f"{len(deployed.get('emf_lines') or [])} EMF lines")
    else:
        print("deployed invoke   : NightlyCheckFn not in the stack")
    print(f"-> {OUT.relative_to(ROOT)}")

    if deployed and (deployed.get("function_error") or deployed.get("error")):
        print("\n!! the DEPLOYED function failed. The in-process half passing "
              "does not cover that — the role, the packaging or the "
              "environment differs.", file=sys.stderr)
        return 3

    if after != before:
        print("\n!! the nightly consumed Opus tokens. The amendment's claim "
              "that it is free is now false and must be corrected before the "
              "ruling.", file=sys.stderr)
        return 1
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
