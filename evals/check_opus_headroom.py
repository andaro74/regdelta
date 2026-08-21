"""Refuse an Opus-spending run that would approach the non-adjustable daily cap.

The human seat's instruction at the M06 window: **Opus must not reach
throttle.** This is that instruction as something that can say no.

## Which ceiling this is about

`L-ED2BADF9` — global cross-region model inference **tokens per day** for Claude
Opus 4.6 — is **2,592,000** and reports `Adjustable: false`. AWS will not raise
it, so crossing it is not a billing event, it is an outage: `make evals` stops
working until 00:00 UTC. At the 5,881.8 Opus tokens per uncached `/query`
measured at M06, that cap is **440 queries a day for everything this account
does**.

The per-minute quota (`L-0AD9BBE8`, 3,000,000/min) is NOT checked here and does
not need to be: the eval harnesses drive questions sequentially, one verdict
call at a time, so a twenty-question run cannot approach a per-minute ceiling
seventy times its own total. If a concurrent `/query` profile is ever run — both
are deferred at M06 — that quota becomes reachable and this file needs a second
check.

## The estimate is the measured mean, and the headroom is measured too

`spent_today` comes from CloudWatch `AWS/Bedrock`, summed from 00:00 UTC, so the
refusal is against what the account has ACTUALLY used rather than against a
fresh day. That distinction is the whole point: a plan that fits a fresh day
says nothing about a day in which someone already ran the golden set twice.

A CloudWatch read that FAILS is a refusal, not a pass. An unreadable meter is
indistinguishable from an empty one, and defaulting to "probably fine" is how a
cap that cannot be bought gets crossed.

Usage:
  python evals/check_opus_headroom.py --questions 5      # the smoke subset
  python evals/check_opus_headroom.py --questions 20     # the full golden set

Exit codes:
  0  the run fits, with the reserve intact
  1  it does not — nothing has been spent
  2  the meter could not be read, so nothing can be claimed about headroom
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from shared import config  # noqa: E402

#: Opus tokens per uncached `/query`, MEASURED — CloudWatch `AWS/Bedrock`,
#: 2026-08-20T14:00-16:00Z, 60 invocations on each of two models across three
#: golden runs. 5,246.3 input + 635.5 output.
#: (`milestones/M06/spec06-disposition-amendment.md`, Finding 1.)
OPUS_TOKENS_PER_QUERY = 5_881.8

#: How much of the day's cap to leave standing after the planned run.
#:
#: NOT a round number chosen for comfort: 15% of 2,592,000 is 388,800 tokens,
#: which is 66 uncached queries — three full golden sets and change. The reserve
#: exists so that a refusal here still leaves room to DIAGNOSE whatever caused
#: it, which a reserve of zero would not.
RESERVE_FRACTION = 0.15


def spent_today(model: str, *, now=None, client=None) -> int:
    """Opus tokens this account has used since 00:00 UTC, from CloudWatch.

    Raises rather than returning zero on any failure. `AWS/Bedrock` publishes
    `InputTokenCount` and `OutputTokenCount` per `ModelId`; both count against
    the same daily cap, so both are summed.
    """
    import boto3

    now = now or dt.datetime.now(dt.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cw = client or boto3.client("cloudwatch", region_name=config.REGION)

    # THE PROFILE ID IS NOT THE MODEL ID. `config.MODEL_VERDICT` is
    # `us.anthropic.claude-opus-4-6-v1`, a cross-region inference profile;
    # CloudWatch's `ModelId` dimension carries the FOUNDATION model the call
    # routed to. Both spellings are summed, because which one appears depends
    # on how the call was made and reading only one silently reports zero.
    ids = {model, model.removeprefix("us.")}
    total = 0
    for metric in ("InputTokenCount", "OutputTokenCount"):
        for model_id in ids:
            resp = cw.get_metric_statistics(
                Namespace="AWS/Bedrock", MetricName=metric,
                Dimensions=[{"Name": "ModelId", "Value": model_id}],
                StartTime=start, EndTime=now, Period=86400, Statistics=["Sum"])
            total += int(sum(p["Sum"] for p in resp.get("Datapoints", [])))
    return total


def check(questions: int, *, now=None, client=None) -> dict:
    cap = config.BEDROCK_DAILY_TOKEN_CAP[config.MODEL_VERDICT]
    used = spent_today(config.MODEL_VERDICT, now=now, client=client)
    planned = round(questions * OPUS_TOKENS_PER_QUERY)
    reserve = int(cap * RESERVE_FRACTION)
    remaining = cap - used
    fits = (used + planned + reserve) <= cap

    return {
        "model": config.MODEL_VERDICT,
        "daily_cap": cap,
        "cap_adjustable": False,
        "used_today": used,
        "used_today_basis": "CloudWatch AWS/Bedrock, summed from 00:00 UTC; a "
                            "read failure is a refusal, never a zero",
        "questions": questions,
        "tokens_per_query": OPUS_TOKENS_PER_QUERY,
        "tokens_per_query_basis": "MEASURED, 60 invocations, M06 Finding 1",
        "planned": planned,
        "reserve": reserve,
        "reserve_basis": f"{RESERVE_FRACTION:.0%} of the cap = "
                         f"{reserve // int(OPUS_TOKENS_PER_QUERY)} uncached "
                         "queries, so a refusal still leaves room to diagnose it",
        "remaining_before": remaining,
        "remaining_after": remaining - planned,
        "fits": fits,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=int, required=True,
                    help="uncached questions the planned run will ask")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.questions < 0:
        ap.error("--questions cannot be negative")

    try:
        report = check(args.questions)
    except Exception as e:                        # noqa: BLE001
        print(f"cannot read the Opus meter: {type(e).__name__}: {e}",
              file=sys.stderr)
        print("REFUSING. An unreadable meter is indistinguishable from an "
              "empty one, and this cap cannot be bought back.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))

    pct = 100 * report["used_today"] / report["daily_cap"]
    print(f"Opus today: {report['used_today']:,} / {report['daily_cap']:,} "
          f"({pct:.1f}%)  planned +{report['planned']:,}  "
          f"reserve {report['reserve']:,}")

    if not report["fits"]:
        print(f"\n❌ REFUSED. {args.questions} questions would leave "
              f"{report['remaining_after']:,} tokens against a reserve of "
              f"{report['reserve']:,}.\n"
              f"   L-ED2BADF9 is NON-ADJUSTABLE — crossing it is not a bill, "
              f"it is `make evals` not working until 00:00 UTC.\n"
              f"   Nothing has been spent.", file=sys.stderr)
        return 1

    print(f"✅ fits — {report['remaining_after']:,} tokens would remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
