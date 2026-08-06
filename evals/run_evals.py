#!/usr/bin/env python3
"""RegDelta eval runner — the project's definition of done.

Usage:
  python evals/run_evals.py                     # full set vs deployed API
  python evals/run_evals.py --subset smoke      # 5-question smoke set
  python evals/run_evals.py --subset retrieval  # retrieval-only checks
  python evals/run_evals.py --api-url http://localhost:8000   # local dev

Reads API URL from --api-url, $REGDELTA_API_URL, or CloudFormation output.
Exit code 0 = all pass. Non-zero = failures (usable as a CI/hook gate).
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
GOLDEN = HERE / "golden_questions.json"
HISTORY = HERE / "history"


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "nogit"


def record(result: dict) -> Path:
    HISTORY.mkdir(exist_ok=True)
    path = HISTORY / f"{result['sha']}-{result['tier']}-{result['subset'] or 'full'}.json"
    path.write_text(json.dumps(result, indent=2))
    return path


def resolve_api_url(cli: str | None) -> str:
    if cli:
        return cli
    if url := os.environ.get("REGDELTA_API_URL"):
        return url
    try:  # fall back to the deployed stack's output
        import boto3
        out = boto3.client("cloudformation").describe_stacks(
            StackName="regdelta-core")["Stacks"][0]["Outputs"]
        return next(o["OutputValue"] for o in out if o["OutputKey"] == "ApiUrl")
    except Exception:
        sys.exit("No API URL. Use --api-url, $REGDELTA_API_URL, or deploy regdelta-core.")


def ask(api_url: str, question: str, mode: str | None, timeout: int = 120) -> dict:
    qs = "?mode=naive" if mode == "naive" else ""
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/query{qs}",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def flatten_answer(resp: dict) -> str:
    """Concatenate everything checkable: rows, prose, citations."""
    parts = [json.dumps(resp.get("answer_rows", "")), resp.get("answer", "")]
    parts += [json.dumps(c) for c in resp.get("citations", [])]
    return " ".join(parts)


def check(q: dict, resp: dict) -> list[str]:
    """Return list of failure reasons (empty = pass)."""
    fails: list[str] = []
    text = flatten_answer(resp)
    low = text.lower()

    for needle in q.get("must_contain", []):
        if needle.lower() not in low:
            fails.append(f"missing required: {needle!r}")

    for key in ("must_contain_any", "must_contain_any_2"):
        for group in ([q[key]] if isinstance(q.get(key, [None])[0], str) else q.get(key, [])):
            if group and not any(n.lower() in low for n in group):
                fails.append(f"none of {group} present")

    for needle in q.get("must_not_contain", []):
        if needle.lower() in low:
            fails.append(f"forbidden text present: {needle!r}")

    cite_text = " ".join(json.dumps(c) for c in resp.get("citations", []))
    if cites := q.get("must_cite_any"):
        if not any(c in cite_text or c in text for c in cites):
            fails.append(f"no citation from {cites}")

    if statuses := q.get("expect_status_any"):
        if resp.get("status") not in statuses:
            fails.append(f"status={resp.get('status')!r}, expected one of {statuses}")

    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default=None, help="smoke|retrieval|trap|... (tag match)")
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument("--mode", choices=["naive", "agent"], default="agent",
                    help="naive = M00b baseline path")
    ap.add_argument("--record", action="store_true",
                    help="append scorecard to evals/history/ (used at milestone close)")
    args = ap.parse_args()

    questions = json.loads(GOLDEN.read_text())["questions"]
    if args.subset:
        questions = [q for q in questions if args.subset in q.get("subset", [])]
    if not questions:
        sys.exit(f"No questions match subset {args.subset!r}")

    api_url = resolve_api_url(args.api_url)
    print(f"→ {len(questions)} questions vs {api_url}\n")

    passed = 0
    per_q = []
    provenance: dict = {}
    t0 = time.monotonic()
    for q in questions:
        try:
            resp = ask(api_url, q["question"], args.mode)
            fails = check(q, resp)
            # Which model / retrieval settings produced this scorecard.
            provenance = resp.get("provenance") or provenance
        except Exception as e:  # noqa: BLE001 — an error IS a failure
            fails = [f"request error: {e}"]
        per_q.append({"id": q["id"], "pass": not fails, "fails": fails})
        if fails:
            print(f"❌ {q['id']}: {q['question'][:70]}")
            for f in fails:
                print(f"     - {f}")
            if args.fail_fast:
                return 1
        else:
            passed += 1
            print(f"✅ {q['id']}")

    total = len(questions)
    print(f"\n{passed}/{total} passed ({100 * passed // total}%)")

    if args.record:
        tier = "naive"
        if args.mode != "naive":
            try:
                with urllib.request.urlopen(f"{api_url.rstrip('/')}/health",
                                            timeout=10) as r:
                    tier = json.loads(r.read()).get("tier", "unknown")
            except Exception:
                tier = "unknown"
        out = record({
            "sha": git_sha(),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tier": tier,
            "mode": args.mode,
            "subset": args.subset,
            "provenance": provenance,
            "passed": passed,
            "total": total,
            "wall_s": round(time.monotonic() - t0, 1),
            "questions": per_q,
        })
        print(f"recorded → {out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
