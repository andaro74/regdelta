"""Record the response-cache outage from the log group, before the fix ends it.

`milestones/M06/dashboard_traffic.py` asked one question twice on 2026-08-21 and
got two misses. The reason was not in the response — `response_cache.get` and
`.put` swallow every failure by design, so a denied cache read is reported as
`cache: "miss"`, which is what a healthy cache says the first time — it was in
`QueryFn`'s log group:

    cache read failed, treating as miss: AccessDeniedException ... dynamodb:GetItem
    cache write failed, answer still served: AccessDeniedException ... dynamodb:PutItem

THIS EVIDENCE IS PERISHABLE, which is why it is captured rather than cited. Once
`CACHE#*` is granted the warnings stop, and CloudWatch retention will age these
events out. A reader six months from now cannot re-run the command and see what
the fix was for; they can read this artifact and check its shape against the
code that emitted it (`src/api/response_cache.py`).

Run BEFORE `make core` applies the fix:

    eval "$(python evals/local_env.py)"
    python milestones/M06/capture_cache_outage.py

Free: one CloudWatch `FilterLogEvents` read. No Bedrock, no DynamoDB.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shared import config  # noqa: E402

OUT = Path(__file__).with_name("cache-outage.json")

#: How far back to look. The traffic run is minutes old at capture time; a
#: three-hour window covers this session without dragging in unrelated days.
LOOKBACK_S = 3 * 3600

#: The two log lines `response_cache` emits when it is denied. Both are
#: WARNINGs and neither reaches the caller — that silence is the defect's
#: whole character and the reason it survived from M05 to M06.
PATTERNS = ("cache read failed", "cache write failed")


def query_fn_log_group() -> str:
    name = subprocess.check_output(
        ["aws", "cloudformation", "describe-stack-resources",
         "--stack-name", "regdelta-core", "--region", config.REGION,
         "--query", "StackResources[?ResourceType=='AWS::Lambda::Function']"
                    ".PhysicalResourceId", "--output", "text"],
        text=True, cwd=ROOT).split()
    fn = next((n for n in name if "QueryFn" in n), None)
    if not fn:
        raise RuntimeError(f"no QueryFn among the core stack's functions: {name}")
    return f"/aws/lambda/{fn}"


def main() -> int:
    import boto3

    logs = boto3.client("logs", region_name=config.REGION)
    group = query_fn_log_group()
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(seconds=LOOKBACK_S)

    events = []
    for pattern in PATTERNS:
        resp = logs.filter_log_events(
            logGroupName=group,
            startTime=int(start.timestamp() * 1000),
            endTime=int(end.timestamp() * 1000),
            filterPattern=f'"{pattern}"')
        for e in resp.get("events") or []:
            events.append({
                "at": dt.datetime.fromtimestamp(
                    e["timestamp"] / 1000, dt.timezone.utc).isoformat(timespec="seconds"),
                "pattern": pattern,
                "message": e["message"].strip()[:600],
            })
    events.sort(key=lambda e: e["at"])

    record = {
        "at": end.isoformat(timespec="seconds"),
        "what": "the SPEC/04 response cache was AccessDenied on both read and "
                "write from M05's IAM scoping until M06. QueryFn's state-table "
                "grants were conditioned on dynamodb:LeadingKeys THREAD#* and "
                "REVIEW#*; response_cache keys on CACHE#<sha256> in the same "
                "table, and CACHE# was not in the enumeration.",
        "why_it_was_silent": "response_cache.get and .put treat ANY failure as "
                             "a miss so a broken cache cannot break a request. "
                             "The response therefore said cache: 'miss', which "
                             "is what a working cache says on a first ask. "
                             "Nothing on the outside distinguished the two.",
        "how_it_was_found": "milestones/M06/dashboard_traffic.py asks one "
                            "question TWICE and exits 3 if the second is not a "
                            "hit. Two misses, exit 3, 2026-08-21.",
        "blast_radius": "repeat /query callers inside the 1h TTL — the demo and "
                        "UI path. NOT the golden set: evals/run_evals.py sends "
                        "no_cache=True and x-regdelta-no-cache on every "
                        "question by design (SPEC/04 parity control 1), so "
                        "`make evals` never consulted the cache and its costs "
                        "are unaffected.",
        "fix": "CACHE#* added to both state-table statements in "
               "infra/core/core_stack.py; tests/test_query_fn_iam.py gains "
               "test_every_state_table_prefix_in_src_is_granted, which derives "
               "the prefix list from src/ instead of restating it.",
        "region": config.REGION,
        "log_group": group,
        "window": {"from": start.isoformat(timespec="seconds"),
                   "to": end.isoformat(timespec="seconds")},
        "command": 'eval "$(python evals/local_env.py)" && '
                   "python milestones/M06/capture_cache_outage.py",
        "event_count": len(events),
        "events": events,
    }
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    for e in events:
        print(f"{e['at']}  {e['message'][:150]}")
    print(f"\n{len(events)} denial events captured -> "
          f"{OUT.relative_to(ROOT)}")

    if not events:
        # Capturing nothing and filing it as evidence of an outage would be
        # worse than not capturing: the artifact would assert a defect it does
        # not show. Either the fix already landed or the window is wrong.
        print("no denial events in the window; nothing here evidences the "
              "outage. Did the fix already deploy?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
