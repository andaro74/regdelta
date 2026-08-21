"""Put real `/query` traffic on the dashboard, at the smallest honest cost.

SPEC/06's Done-when asks for a dashboard that is screenshot-ready. Five of its
panels are fed only by `/query`: latency p50/p95, cache hit rate, Bedrock cost
per query, HITL rate, and Lambda concurrency on the query path. The retrieval
panel is fed by the disposition run, which makes no model call at all.

## Why not `make smoke`

`make smoke` asks five golden questions, which is ten Claude calls, $0.24, and
1.1% of a NON-ADJUSTABLE daily Opus cap. It also sends `no_cache: true` on every
one — deliberately, because at M04 a run scored 5/5 entirely from cached answers
the other tier had written and was reported as evidence
(`tests/test_eval_cache_control.py`). So a smoke run produces five misses and
zero hits, and leaves the cache-hit panel reading 0%.

## What this does instead

ONE question, asked TWICE, with the cache left on:

  * the first call is a MISS and costs one Sonnet + one Opus call
  * the second is a HIT, costs no model call at all, and is the only way the
    cache-hit panel gets a hit in it

Two Claude calls instead of ten: **$0.048 and 0.23% of the cap**, and it fills
a panel five smoke questions structurally cannot. The seat chose this at the
M06 window.

It is NOT a correctness check and does not pretend to be — no answer is scored
and no scorecard is written. That job is `make evals`, and the golden set is
where it belongs.

## What it refuses

The Opus headroom guard runs first, exactly as `make smoke` would. And the
second call must come back `cache: hit`: if it does not, the cache is off or
broken, this run cost twice what it should have, and saying so is the point —
a silent second miss would be recorded as "the panel has data" while the panel
had the wrong data.

Run:
    eval "$(python evals/local_env.py)"
    python milestones/M06/dashboard_traffic.py
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import check_opus_headroom as opus  # noqa: E402

from shared import config  # noqa: E402

OUT = Path(__file__).with_name("dashboard-traffic.json")

#: q05 from the smoke subset. Chosen because it needs no `company_profile` —
#: an applicability question would exercise a branch this run is not measuring
#: — and because it is a question the corpus can actually answer, so the
#: dashboard shows a normal request rather than a `needs_input`.
QUESTION = ("What are the two main criteria a food must meet to use the "
            "'healthy' claim?")

#: The deployed API takes two minutes per request at worst (QueryFn's own
#: timeout). Read timeout above it so a slow answer is the API's error and not
#: this script's.
TIMEOUT_S = 150


#: The API id, replaced before anything is written to disk.
#:
#: THIS ARTIFACT IS COMMITTED TO A PUBLIC REPOSITORY and `/query` is
#: unauthenticated by design (SPEC/04 declares auth out of scope;
#: `core_stack.py:529`). Its only bounds are an API Gateway throttle of 20 rps
#: / 40 burst — commented in that file as "a demo's shape … not a capacity
#: plan" — and the fact that nobody knows the host. Publishing the host removes
#: the second one.
#:
#: The arithmetic is this run's own: at the $0.0601 per cache miss measured
#: here, 20 rps is ~$1.20/s, and it does not stop at the money. The Opus daily
#: cap is `Adjustable: false`, so an exhausted cap is a day with no golden set
#: and no demo. The response cache does not help — `key()` hashes the question,
#: so varying it misses every time.
#:
#: Nothing in this artifact's claims depends on the id: it records cache
#: hit/miss, latency and token spend. security-reviewer, M06.
REDACTED_HOST = "https://<api-id>.execute-api.<region>.amazonaws.com"


def redact(url: str) -> str:
    """The API's public address, reduced to its shape."""
    import re
    return re.sub(r"https://[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com",
                  REDACTED_HOST, url or "")


def api_url() -> str:
    out = subprocess.check_output(
        ["aws", "cloudformation", "describe-stacks",
         "--stack-name", "regdelta-core", "--region", config.REGION,
         "--query", "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue",
         "--output", "text"], text=True, cwd=ROOT).strip()
    if not out.startswith("https://"):
        raise RuntimeError(f"regdelta-core exports no usable ApiUrl: {out!r}")
    return out


def ask(url: str) -> dict:
    """One `/query`, WITHOUT a bypass flag, so the cache is live."""
    body = json.dumps({"question": QUESTION}).encode()
    req = urllib.request.Request(f"{url}/query", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as e:
        payload, status = {"error": e.read().decode("utf-8", "replace")[:400]}, e.code
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "http_status": status,
        "wall_ms": wall_ms,
        "cache": payload.get("cache"),
        "status": payload.get("status"),
        "confidence": payload.get("confidence"),
        "citations": len(payload.get("citations") or []),
        "retrieval_tier": payload.get("retrieval_tier"),
        "retrieval_ms": payload.get("retrieval_ms"),
        "error": payload.get("error"),
    }


def main() -> int:
    headroom = opus.check(1)
    if not headroom["fits"]:
        print("REFUSED by the Opus headroom guard; nothing has been spent.",
              file=sys.stderr)
        return 1
    print(f"Opus today: {headroom['used_today']:,} / "
          f"{headroom['daily_cap']:,}; this run plans "
          f"{headroom['planned']:,}")

    url = api_url()
    # The console is the operator's own terminal, not the artifact; the id is
    # printed there so a failure can be diagnosed. It is `redact`ed on the way
    # to disk, which is the copy that gets committed.
    print(f"api: {url}\nquestion: {QUESTION!r}\n")

    before = opus.spent_today(config.MODEL_VERDICT)
    first = ask(url)
    print(f"call 1: http {first['http_status']}  cache={first['cache']}  "
          f"{first['wall_ms']} ms  tier={first['retrieval_tier']}  "
          f"citations={first['citations']}")

    second = ask(url)
    print(f"call 2: http {second['http_status']}  cache={second['cache']}  "
          f"{second['wall_ms']} ms")
    after = opus.spent_today(config.MODEL_VERDICT)

    record = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "purpose": "populate the /query dashboard panels at the smallest "
                   "honest cost; NOT a correctness check and no scorecard is "
                   "written",
        "ruled": "the human seat chose this over `make smoke` at the M06 "
                 "window: 2 Claude calls instead of 10",
        "question": QUESTION,
        "api": redact(url),
        "api_redacted": "the host is removed deliberately; see `redact` in "
                        "milestones/M06/dashboard_traffic.py. /query is "
                        "unauthenticated and this file is public.",
        "calls": [first, second],
        "opus_tokens_before": before,
        "opus_tokens_after": after,
        "opus_tokens_spent": after - before,
        "opus_daily_cap": headroom["daily_cap"],
        "opus_cap_adjustable": False,
    }
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"\nOpus tokens spent: {after - before:,} "
          f"({100 * (after - before) / headroom['daily_cap']:.2f}% of the cap)")
    print(f"-> {OUT.relative_to(ROOT)}")

    if first["http_status"] != 200 or second["http_status"] != 200:
        print("\n❌ the API did not answer; the panels have no usable data.",
              file=sys.stderr)
        return 2
    if second["cache"] != "hit":
        # THE POINT OF THE SECOND CALL. A silent second miss doubles the cost
        # and leaves the cache panel showing what this run was chosen to avoid.
        print(f"\n❌ the second call came back cache={second['cache']!r}, not "
              "'hit'. The cache is off or broken, this run cost twice what it "
              "should have, and the cache-hit panel has no hit in it.",
              file=sys.stderr)
        return 3
    print("✅ one miss and one hit — both cache states are on the dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
