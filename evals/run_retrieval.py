#!/usr/bin/env python3
"""RegDelta retrieval harness (SPEC/02 Done-when A).

Measures the retrieval contract in-process — router.retrieve(), not an
answering endpoint. The golden set is the wrong instrument here: those
questions assert on answer prose, so a failure cannot tell "the chunk never
came back" from "the model fumbled a chunk it had".

Usage:
  python evals/run_retrieval.py --tier s3vectors          # hot tier down
  python evals/run_retrieval.py --tier aoss               # hot tier up
  python evals/run_retrieval.py --tier s3vectors --record # write scorecard

Exit codes:
  0  all gating criteria pass
  1  a gating criterion failed (recall, must_not_return, resolved tier)
  2  the date-attribution preflight failed — no probe was run

Criteria 2 (partially) and 3 are CROSS-run and cannot be judged inside one
invocation: neither run can see the other's output. This asserts the half it
can see (resolved == requested) and records the rest; `run_parity.py` reads
both scorecards and is what exits non-zero on drift.
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

# The dev box is Windows and its console defaults to cp1252, which cannot
# encode ✅/❌. Without this the harness raises UnicodeEncodeError while
# printing a PASSING result — a green run that exits non-zero, from the
# reporting layer rather than the thing being reported.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from run_evals import git_sha  # noqa: E402  (path set above)

from shared import config  # noqa: E402
from shared.models import Filters  # noqa: E402

TRUTH = HERE / "retrieval_truth.json"
HISTORY = HERE / "history"
K = 8

# The document the date-attribution preflight is about. Named once: this is
# ADR-0006's worked case, not a general property being spot-checked.
ATTRIBUTION_DOC = "2025-03118"
ATTRIBUTION_CHUNKS_KEY = f"chunks/101/{ATTRIBUTION_DOC}.jsonl"


def resolve_stack_env() -> None:
    """Fill CORPUS_BUCKET / VECTOR_BUCKET / REGISTRY_TABLE from regdelta-core.

    The Lambdas get these from CDK; a laptop run has to find them. Resolving
    from the deployed stack rather than a .env means the harness cannot be
    pointed at a stale bucket by a leftover shell export — and `--tier` would
    still pass, because the tier assertion is about routing, not about which
    corpus answered.

    Explicit environment still wins, so a second stack can be targeted
    deliberately. Table names come from stack RESOURCES because the core stack
    exports the buckets but not the tables; adding outputs would work too and
    would need a redeploy to read them.
    """
    import boto3
    cfn = boto3.client("cloudformation", region_name=config.REGION)
    if not (config.CORPUS_BUCKET and config.VECTOR_BUCKET):
        outputs = {o["OutputKey"]: o["OutputValue"] for o in
                   cfn.describe_stacks(StackName="regdelta-core")["Stacks"][0]
                   .get("Outputs", [])}
        config.CORPUS_BUCKET = config.CORPUS_BUCKET or outputs["CorpusBucketName"]
        config.VECTOR_BUCKET = config.VECTOR_BUCKET or outputs["VectorBucketName"]
    if not config.REGISTRY_TABLE:
        resources = cfn.describe_stack_resources(
            StackName="regdelta-core")["StackResources"]
        config.REGISTRY_TABLE = next(
            r["PhysicalResourceId"] for r in resources
            if r["ResourceType"] == "AWS::DynamoDB::Table"
            and r["LogicalResourceId"].startswith("RegistryTable"))


def git_dirty() -> bool:
    """True if the working tree differs from HEAD.

    A scorecard is evidence, and `git_sha()` reports HEAD whether or not the
    tree matches it — so recording from a dirty tree files a measurement under
    a commit that cannot reproduce it. That is worse than no evidence: it
    survives into milestones/ and reads as a verified claim. Caught while
    recording the first Tier A run, which was labelled with the previous
    commit's sha.

    `evals/history/` is excluded. Scorecards are OUTPUTS: the two tier runs
    have to happen at the same commit (run_parity pairs them by sha), the
    second run cannot happen until the hot tier is deployed, and committing
    the first run's card in between would move HEAD and guarantee the pair
    never matches. A scorecard sitting in the tree changes nothing about what
    the code under measurement does.
    """
    import subprocess
    try:
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--",
             ".", ":(exclude)evals/history"], text=True).strip())
    except Exception:  # noqa: BLE001 — no git means no claim either way
        return False


def _json_attr(item: dict, key: str):
    """Read a META attribute the processor wrote with json.dumps().

    Tolerates an already-decoded list so the check does not depend on how the
    item was fetched, and raises on anything else rather than guessing — a
    shape this does not recognise means the store changed, which is a
    preflight failure and not something to route around.
    """
    raw = item.get(key)
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    return json.loads(raw)


# ------------------------------------------------------------- criterion 5
def preflight(verbose: bool = True) -> list[str]:
    """Assert 2025-03118 establishes no compliance date, in all three stores.

    Gating, and it runs BEFORE any probe: a corpus that fails this fails M02
    regardless of recall. The failure it guards against is not hypothetical —
    a fabricated 2028-01-01 compliance date was live in this corpus for two
    milestones (ADR-0006).

    Three stores because they have diverged before. META and the chunks
    disagreed about `effective_date` at M01c, so this also asserts those two
    agree — the divergence was invisible from either store alone.
    """
    import boto3
    resolve_stack_env()
    failures: list[str] = []

    def note(msg: str):
        failures.append(msg)

    ddb = boto3.resource("dynamodb", region_name=config.REGION)
    table = ddb.Table(config.REGISTRY_TABLE)
    item = table.get_item(Key={"pk": f"DOC#{ATTRIBUTION_DOC}",
                               "sk": "META"}).get("Item")
    if not item:
        note(f"DynamoDB META missing for DOC#{ATTRIBUTION_DOC}")
        meta_eff = None
    else:
        # META stores these as JSON STRINGS (processor writes json.dumps(...)),
        # so the raw attribute for an empty list is the two-character string
        # "[]" — which is truthy. A `if item["compliance_dates"]:` check reads
        # naturally, passes review, and reports a failure on exactly the value
        # ADR-0006 requires. Decode first; that is the whole point of
        # criterion 5 naming three stores rather than trusting one.
        comp = _json_attr(item, "compliance_dates")
        if comp:
            note(f"META compliance_dates is {comp!r}, expected []")
        eff_list = _json_attr(item, "effective_dates") or []
        meta_eff = eff_list[0].get("date") if eff_list else None

    s3 = boto3.client("s3", region_name=config.REGION)
    chunk_eff: set = set()
    keys: list[str] = []
    try:
        body = s3.get_object(Bucket=config.CORPUS_BUCKET,
                             Key=ATTRIBUTION_CHUNKS_KEY)["Body"].read()
    except Exception as e:  # noqa: BLE001 — any read failure is a failed preflight
        note(f"cannot read s3://{config.CORPUS_BUCKET}/{ATTRIBUTION_CHUNKS_KEY}: {e}")
    else:
        records = [json.loads(ln) for ln in body.decode().splitlines() if ln.strip()]
        if not records:
            note(f"{ATTRIBUTION_CHUNKS_KEY} is empty")
        for n, rec in enumerate(records):
            if rec.get("compliance_date"):
                note(f"{ATTRIBUTION_CHUNKS_KEY} line {n} has "
                     f"compliance_date={rec['compliance_date']!r}, expected null")
                break
        chunk_eff = {rec.get("effective_date") for rec in records}
        # The vector keys come from the chunks themselves rather than a
        # reconstructed id pattern: a guessed range would silently check
        # nothing if the chunker's numbering ever changed, and "checked
        # nothing" reads identically to "found nothing wrong".
        keys = [rec["chunk_id"] for rec in records]

    if not keys:
        note(f"no chunk ids for {ATTRIBUTION_DOC}; the S3 Vectors store was "
             "NOT checked — this is a failure, not a skip")
    else:
        sv = boto3.client("s3vectors", region_name=config.REGION)
        got = []
        for i in range(0, len(keys), 100):
            try:
                got += sv.get_vectors(
                    vectorBucketName=config.VECTOR_BUCKET,
                    indexName=config.VECTOR_INDEX,
                    keys=keys[i:i + 100], returnMetadata=True,
                    returnData=False).get("vectors", [])
            except Exception as e:  # noqa: BLE001 — a read failure is a failed preflight
                note(f"cannot read S3 Vectors metadata for {ATTRIBUTION_DOC}: {e}")
                break
        if not got:
            note(f"S3 Vectors holds no chunks for {ATTRIBUTION_DOC}")
        for v in got:
            if (v.get("metadata") or {}).get("compliance_date"):
                note(f"S3 Vectors {v['key']} has compliance_date="
                     f"{v['metadata']['compliance_date']!r}, expected absent")
                break

    # Cross-store agreement on the date that DOES exist. META and the chunks
    # diverged here once already, and neither store looked wrong alone.
    if chunk_eff and len(chunk_eff) == 1:
        only = next(iter(chunk_eff))
        if meta_eff != only:
            note(f"effective_date disagreement: META={meta_eff!r}, "
                 f"chunks={only!r}")
    elif len(chunk_eff) > 1:
        note(f"chunks disagree internally on effective_date: {sorted(chunk_eff)}")

    if verbose:
        print("✅ date-attribution preflight" if not failures
              else "❌ date-attribution preflight")
        for f in failures:
            print(f"     - {f}")
    return failures


# ------------------------------------------------------------------- probes
def score_probe(probe: dict, got: list[str]) -> dict:
    """Recall@8, must_not_return violations, MRR — for one probe.

    Recall is computed only over probes with a non-empty expected set: a
    pure-negative probe contributes no recall term (it would otherwise score
    1.0 for free and inflate the mean), and its must_not_return violations
    fail regardless.
    """
    expected = probe.get("expected_chunk_ids") or []
    forbidden = probe.get("must_not_return") or []
    top = got[:K]
    missing = [cid for cid in expected if cid not in top]
    leaked = [cid for cid in forbidden if cid in top]

    recall = None
    if expected:
        recall = (len(expected) - len(missing)) / len(expected)

    rr = 0.0
    for rank, cid in enumerate(top, start=1):
        if cid in expected:
            rr = 1.0 / rank
            break

    return {"probe_id": probe["probe_id"],
            "pass": not missing and not leaked,
            "missing": missing,
            "leaked": leaked,
            "recall": recall,
            "rr": rr if expected else None,
            "returned": top}


def run(tier_requested: str, record: bool, allow_dirty: bool = False) -> int:
    from retrieval import router

    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    probes = truth["probes"]

    dirty = git_dirty()
    if record and dirty and not allow_dirty:
        print("refusing to record from a dirty working tree: the scorecard "
              "would be filed under a commit that cannot reproduce it. "
              "Commit first, or pass --allow-dirty to stamp it as provisional.")
        return 1

    if preflight():
        print("\ndate_attribution_failed — no probe was run.")
        return 2

    router.reset_cache()
    print(f"\n→ {len(probes)} probes, k={K}, requested tier={tier_requested}\n")

    results = []
    resolved_tiers = set()
    fallbacks = []
    t0 = time.monotonic()
    for probe in probes:
        filters = Filters.from_dict(probe.get("filters"))
        chunks, resolution = router.retrieve_traced(probe["query"], filters, K)
        resolved_tiers.add(resolution.tier)
        if resolution.fallback_reason:
            fallbacks.append(f"{probe['probe_id']}: {resolution.fallback_reason}")
        r = score_probe(probe, [c.chunk_id for c in chunks])
        results.append(r)
        if r["pass"]:
            print(f"✅ {r['probe_id']}  {probe['query'][:60]}")
        else:
            print(f"❌ {r['probe_id']}  {probe['query'][:60]}")
            if r["missing"]:
                print(f"     missing: {r['missing']}")
            if r["leaked"]:
                print(f"     must_not_return leaked: {r['leaked']}")

    wall = round(time.monotonic() - t0, 1)
    scored = [r for r in results if r["recall"] is not None]
    recall = (sum(r["recall"] for r in scored) / len(scored)) if scored else None
    mrr = (sum(r["rr"] for r in scored) / len(scored)) if scored else None
    passed = sum(1 for r in results if r["pass"])

    # Criterion 2, the half a single run can see. The other half — that the
    # two recorded runs resolved to DIFFERENT tiers — is run_parity.py's.
    tier_ok = resolved_tiers == {tier_requested}
    print(f"\n{passed}/{len(results)} probes passed · "
          f"recall@{K}={recall if recall is None else round(recall, 3)} · "
          f"MRR={mrr if mrr is None else round(mrr, 3)} (reported, not gating) · "
          f"{wall}s")
    if not tier_ok:
        print(f"❌ resolved tier {sorted(resolved_tiers)} != requested "
              f"{tier_requested!r}")
        for f in fallbacks:
            print(f"     fallback: {f}")

    if record:
        HISTORY.mkdir(exist_ok=True)
        sha = git_sha()
        out = HISTORY / f"{sha}-retrieval-{tier_requested}.json"
        out.write_text(json.dumps({
            "sha": sha,
            "dirty": dirty,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "kind": "retrieval",
            "k": K,
            "tier_requested": tier_requested,
            "tier_resolved": sorted(resolved_tiers),
            "fallbacks": fallbacks,
            "corpus_snapshot": truth.get("corpus_snapshot"),
            # Recall is not answer quality. The M00b control measures answer
            # quality, so a recall number is not a delta against it and must
            # not be read as one (SPEC/02 "Scorecard namespace").
            "comparable_to_baseline": False,
            "recall_at_k": recall,
            "mrr": mrr,
            "mrr_is_gating": False,
            "passed": passed,
            "total": len(results),
            "wall_s": wall,
            "probes": results,
        }, indent=2), encoding="utf-8")
        print(f"recorded → {out}")

    return 0 if (passed == len(results) and tier_ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True, choices=["s3vectors", "aoss"],
                    help="the tier this run must resolve to; mismatch exits 1")
    ap.add_argument("--record", action="store_true",
                    help="write the scorecard run_parity.py reads")
    ap.add_argument("--preflight-only", action="store_true",
                    help="criterion 5 alone (cheap; no Bedrock calls)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty:true")
    args = ap.parse_args()
    if args.preflight_only:
        return 2 if preflight() else 0
    return run(args.tier, args.record, args.allow_dirty)


if __name__ == "__main__":
    sys.exit(main())
