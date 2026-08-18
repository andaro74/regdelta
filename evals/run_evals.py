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
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

HERE = Path(__file__).parent
GOLDEN = HERE / "golden_questions.json"
HISTORY = HERE / "history"

# This script prints ✅/❌/→, and a Windows console defaults to cp1252, which
# cannot encode any of them: the run died with UnicodeEncodeError on the
# banner line, before question one, with no scorecard and nothing to read. The
# repo is driven from PowerShell as often as from Git Bash (Makefile line 11
# says so about RERANK), so this is a supported path, not an exotic one.
# Reconfigure rather than downgrade the glyphs — the pass/fail column is the
# thing an operator reads first, and `errors="replace"` keeps a hostile
# terminal from taking the run down again for a different codec reason.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001 — provenance is best-effort; never fail a run over it
        return "nogit"


def git_dirty(exclude: tuple[str, ...] = ()) -> bool:
    """True if the working tree differs from HEAD.

    MOVED HERE from run_retrieval.py, which is where it was written and where
    its reasoning still reads best — but run_evals.py is already the home of
    `git_sha()` for both other harnesses (`from run_evals import git_sha` in
    run_parity.py and run_retrieval.py), so its twin belongs beside it rather
    than in a module that imports it.

    The reason, unchanged: a scorecard is evidence, and `git_sha()` reports
    HEAD whether or not the tree matches it — so recording from a dirty tree
    files a measurement under a commit that cannot reproduce it. That is worse
    than no evidence, because it survives into milestones/ and reads as a
    verified claim. Caught while recording the first Tier A run, which was
    labelled with the previous commit's sha.

    `evals/history/` is excluded. Scorecards are OUTPUTS: the two retrieval
    tier runs have to happen at the same commit (run_parity pairs them by sha),
    the second cannot happen until the hot tier is deployed, and committing the
    first run's card in between would move HEAD and guarantee the pair never
    matches. A card sitting in the tree changes nothing about what the code
    under measurement does.

    The golden-set runner had NO such guard while its sibling did, which is how
    a 90% agent-mode run at M03 came within one flag of being filed under a
    commit containing none of the graph that produced it.

    `exclude` takes further pathspecs on the same reasoning, for callers whose
    output does not live in evals/history. `run_demo_parity.py` passes
    `milestones/M04/answer-parity-*.json`: its two tier runs must happen at one
    sha, the second cannot happen until `make up` has flipped the tier, and the
    first run's artifact sits in the tree in between — so without this the
    second run would refuse to record because the first one succeeded. The
    pattern is the ARTIFACT, not the directory: an uncommitted edit to the
    milestone's README is exactly the kind of drift this guard exists to catch.
    """
    try:
        pathspecs = [":(exclude)evals/history"] + [f":(exclude){p}" for p in exclude]
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--", ".", *pathspecs],
            text=True, cwd=HERE.parent).strip())
    except Exception:  # noqa: BLE001 — same policy as git_sha: never fail a run over provenance
        return False


def corpus_fingerprint() -> dict:
    """What the corpus looked like when this run happened.

    Retrieval scorecards carry a `corpus_snapshot`, but it is a human-authored
    string in retrieval_truth.json — fine when the corpus changed only when
    someone re-ingested it. It no longer does: the daily poller took the corpus
    from 4 FR documents to 34 between 2026-07-30 and 2026-08-12, unattended, and
    nobody edited a string. A golden-set number measured against a corpus that
    moves on its own is not reproducible unless the card says which corpus.

    `documents_sha` is the point — one short hash over the sorted document
    numbers, so "same corpus?" is a string comparison between two cards rather
    than a diff of two lists.

    Best-effort, like `git_sha`: no credentials, no table, or a transient error
    yields `{"available": False}` and the run still produces a scorecard. A
    missing fingerprint is visible; a run that died collecting one is not.
    """
    from shared import config

    if not config.REGISTRY_TABLE:
        return {"available": False, "reason": "REGISTRY_TABLE unset"}
    try:
        import boto3
        from boto3.dynamodb.conditions import Attr

        table = boto3.resource("dynamodb", region_name=config.REGION) \
            .Table(config.REGISTRY_TABLE)
        docs, dates, kwargs = [], [], {
            "FilterExpression": Attr("sk").eq("META"),
            "ProjectionExpression": "pk, pub_date",
        }
        while True:
            resp = table.scan(**kwargs)
            for item in resp.get("Items", []):
                docs.append(str(item["pk"]).removeprefix("DOC#"))
                if item.get("pub_date"):
                    dates.append(str(item["pub_date"]))
            if not resp.get("LastEvaluatedKey"):
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        docs.sort()
        digest = hashlib.sha256("\n".join(docs).encode()).hexdigest()[:12]
        return {
            "available": True,
            "documents": len(docs),
            "documents_sha": digest,
            "newest_pub_date": max(dates) if dates else None,
            "oldest_pub_date": min(dates) if dates else None,
        }
    except Exception as e:  # noqa: BLE001 — provenance must never fail a run
        return {"available": False, "reason": f"{type(e).__name__}: {e}"[:200]}


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
    except Exception:  # noqa: BLE001 — any failure here means "no endpoint", incl. no creds
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
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty=true (provisional)")
    args = ap.parse_args()

    # Checked BEFORE the run, not at record time: a golden-set run costs real
    # Bedrock calls, and discovering the refusal after paying for them would
    # push an operator toward --allow-dirty for the wrong reason.
    dirty = git_dirty()
    if args.record and dirty and not args.allow_dirty:
        sys.exit("refusing to record from a dirty working tree: the scorecard "
                 "would be filed under a commit that cannot reproduce it. "
                 "Commit first, or pass --allow-dirty to stamp it as provisional.")

    questions = json.loads(GOLDEN.read_text())["questions"]
    if args.subset:
        questions = [q for q in questions if args.subset in q.get("subset", [])]
    if not questions:
        sys.exit(f"No questions match subset {args.subset!r}")

    api_url = resolve_api_url(args.api_url)
    print(f"→ {len(questions)} questions vs {api_url}\n")

    passed = 0
    answered = 0          # questions that actually reached the API
    per_q = []
    provenance: dict = {}
    t0 = time.monotonic()
    for q in questions:
        resp = {}
        try:
            resp = ask(api_url, q["question"], args.mode)
            answered += 1
            fails = check(q, resp)
            # Which model / retrieval settings produced this scorecard.
            provenance = resp.get("provenance") or provenance
        except Exception as e:  # noqa: BLE001 — an error IS a failure
            fails = [f"request error: {e}"]
        # THE ANSWER IS RECORDED, not just the verdict. Cards used to carry
        # {id, pass, fails} and nothing else, which makes a PASS unauditable:
        # the 2026-08-15 discrimination sweep found 14 wrong answers that the
        # live questions score as passes, and there was then no way to ask
        # whether any recorded pass had actually been earned or merely given
        # away by a loose token. A failure was always legible — `fails` says
        # what was missing — so only the passes were dark, which is the wrong
        # way round for evidence. Everything check() scored is kept verbatim
        # and untruncated; a truncated answer would reintroduce the same gap
        # more quietly.
        per_q.append({
            "id": q["id"],
            "pass": not fails,
            "fails": fails,
            "response": {
                "answer": resp.get("answer"),
                "answer_rows": resp.get("answer_rows"),
                "citations": resp.get("citations"),
                "status": resp.get("status"),
            },
        })
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

    # NOTHING MEASURED IS NOT A SCORE OF ZERO. If no question ever reached the
    # API, the run says nothing about the system and a card recording it is
    # false evidence — worse than no card, because it looks like a measurement
    # and files under a real sha. This has happened: `make agent-evals` and
    # `make baseline` background the loopback shim and never check it came up,
    # so when serve_local.py refused to start on an unset VECTOR_BUCKET both
    # targets recorded a 0/10 card of pure connection errors. The dirty-tree
    # guard already refuses to record a run whose CODE is uncertain; this
    # refuses to record one whose RESULT is vacuous.
    if answered == 0:
        print(f"\nNOT RECORDING: no question reached {api_url} — every request "
              f"failed in transport, so this run measured nothing. A 0/{total} "
              f"card here would be false evidence, not a bad score.",
              file=sys.stderr)
        if args.record:
            return 2
        return 1

    if args.record:
        tier = "naive"
        if args.mode != "naive":
            try:
                with urllib.request.urlopen(f"{api_url.rstrip('/')}/health",
                                            timeout=10) as r:
                    tier = json.loads(r.read()).get("tier", "unknown")
            except Exception:  # noqa: BLE001 — tier is provenance, not a result
                tier = "unknown"
        out = record({
            "sha": git_sha(),
            # run_parity.py already refuses a retrieval card carrying this;
            # a golden-set card has to be able to say the same thing.
            "dirty": dirty,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tier": tier,
            "mode": args.mode,
            "subset": args.subset,
            # Which corpus answered. The poller changes this daily and without
            # it two cards cannot be compared — see corpus_fingerprint.
            "corpus": corpus_fingerprint(),
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
