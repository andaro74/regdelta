"""Run the nightly check and record what it returned.

`pm-spec-reviewer` blocker B8: the nightly amendment's only load-bearing claim
— "verified live, 2026-08-20, for $0: 52 documents, 3/3 dated, no Bedrock
call" — cited neither a file nor a command, in a document where every other
measurement names an artifact a reader can check. A remembered result is not
evidence.

## In-process, and the distinction is the point

`NightlyCheckFn` is NOT DEPLOYED — nothing in this milestone is. So this runs
`ops.nightly.handler` in this process against the deployed environment, which
is what "verified live" actually meant last session and what the record should
have said. It exercises the same code the function will run and the same AWS
reads; what it does NOT exercise is the Lambda's own IAM role, its EventBridge
schedule, or EMF reaching CloudWatch. The artifact says so, so that a later
reader does not mistake this for a deployed-function verification.

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

    record = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha": git_sha(),
        "how": "IN-PROCESS. `ops.nightly.handler` run in this process against "
               "the deployed environment. NightlyCheckFn is not deployed, so "
               "this exercises the same code and the same AWS reads but NOT "
               "the Lambda's IAM role, its EventBridge schedule, or EMF "
               "reaching CloudWatch.",
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
    print(f"-> {OUT.relative_to(ROOT)}")

    if after != before:
        print("\n!! the nightly consumed Opus tokens. The amendment's claim "
              "that it is free is now false and must be corrected before the "
              "ruling.", file=sys.stderr)
        return 1
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
