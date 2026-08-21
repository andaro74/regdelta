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
  3  the harness did not complete (crash) — NOTHING was measured, and no
     scorecard from this run is valid. Distinct from 1 so a caller cannot
     read "never measured" as "measured a failure".

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
import traceback
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

# The dev box is Windows and its console defaults to cp1252, which cannot
# encode ✅/❌. Without this the harness raises UnicodeEncodeError while
# printing a PASSING result — a green run that exits non-zero, from the
# reporting layer rather than the thing being reported.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from run_evals import (  # noqa: E402  (path set above)
    corpus_fingerprint,
    git_dirty,
    git_sha,
)

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
    rerank_notes = {}
    t0 = time.monotonic()
    for probe in probes:
        filters = Filters.from_dict(probe.get("filters"))
        chunks, resolution = router.retrieve_traced(probe["query"], filters, K)
        resolved_tiers.add(resolution.tier)
        if resolution.fallback_reason:
            fallbacks.append(f"{probe['probe_id']}: {resolution.fallback_reason}")
        # SPEC/02's RERANK adoption bar, condition 4: each card records the
        # candidate set the reranker scored and which side of diversify it came
        # from. Per probe, not once per run — a reranker that silently fell open
        # on three probes and worked on six is not a measured reranker, and the
        # aggregate would hide it.
        rerank_notes[probe["probe_id"]] = resolution.rerank
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

    if record and not tier_ok:
        # The scorecard is NAMED for the requested tier, so recording a
        # mismatched run files one tier's results under the other tier's name
        # and silently overwrites a valid card. That happened: a Makefile bug
        # reported the hot tier as down, and an AOSS run replaced a passing
        # S3 Vectors scorecard. Same failure class as the dirty-sha guard —
        # evidence labelled with something it is not.
        print("NOT recording: the router resolved a different tier than "
              "requested, so this run is not evidence about "
              f"{tier_requested!r}.")
    elif record:
        HISTORY.mkdir(exist_ok=True)
        sha = git_sha()
        # SPEC/02 "Scorecard namespace": the -rerank{0,1} suffix exists because
        # the adoption bar needs FOUR cards at one sha (two tiers x two flag
        # values) and the base <sha>-retrieval-<tier> namespace can only express
        # two — the second pair would silently overwrite the first.
        #
        # RETRIEVAL_LEXICAL_LANE gets a suffix on the same reasoning: ADR-0009
        # Ruling 3's confirming measurement compares a lane-off Tier B against a
        # lane-on one, and two cards at one sha cannot share a filename. `-lex1`
        # only when on, so the default configuration keeps the base name and
        # every card recorded before this flag existed stays readable.
        suffix = f"-rerank{int(config.RERANK)}" if config.RERANK else ""
        if config.RETRIEVAL_LEXICAL_LANE:
            suffix += "-lex1"
        # STILL OVERWRITES AT ONE SHA, and that is a deferral rather than a
        # closed thread. `run_evals.record()` gained supersession at M05 (the
        # M04 thread), so a golden-set run can no longer be repeated until it
        # goes green without leaving a trace; retrieval cards and
        # run_demo_parity's artifact still can. Not folded in because the M04
        # thread named the golden set specifically, and because `run_parity`
        # pairs cards by exact filename — giving these a trail means deciding
        # what the pair means when one half has been re-run, which is a
        # question about the parity gate, not about recording. Raised by
        # eng-code-reviewer at M05 so it does not read as already handled.
        out = HISTORY / f"{sha}-retrieval-{tier_requested}{suffix}.json"
        out.write_text(json.dumps({
            "sha": sha,
            "dirty": dirty,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "kind": "retrieval",
            "k": K,
            "tier_requested": tier_requested,
            "tier_resolved": sorted(resolved_tiers),
            "fallbacks": fallbacks,
            # Condition 4 of the adoption bar. `rerank_enabled` is the flag as
            # the run saw it; `rerank` is what actually happened per probe, so a
            # card cannot claim a reranked run that fell open.
            "rerank_enabled": config.RERANK,
            "rerank": rerank_notes,
            # Which retrieval configuration produced this card. ADR-0009 Ruling
            # 3 turned on a measured comparison between lane-on and lane-off, so
            # a card that cannot say which one it is is not evidence for either.
            # Tier A has no lexical lane; the field records the flag as the run
            # saw it, which is what makes a pair one configuration.
            "lexical_lane": config.RETRIEVAL_LEXICAL_LANE,
            # The probe set's own claim about when it was authored — a
            # HAND-WRITTEN string, and therefore a claim about the past that
            # nothing updates.
            "corpus_snapshot": truth.get("corpus_snapshot"),
            # What actually answered this run. The same argument that put a
            # fingerprint on golden-set cards applies here and applies harder:
            # this card asserts recall, and recall against WHICH corpus is the
            # whole content of the claim. The poller moved the corpus from 4
            # documents to 49 while the snapshot string above still said
            # 2026-08-08 (ADR-0011).
            "corpus": corpus_fingerprint(),
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
    # 1 is reserved for "measured a gating failure". An uncaught exception —
    # a missing CloudFormation output, an unreachable tier, a malformed card —
    # also exits 1 via traceback, so a caller cannot tell "the criterion failed"
    # from "nothing was ever measured". The second is not evidence, and a CI job
    # or a milestone record that treats it as evidence records a failure that
    # never happened.
    try:
        if args.preflight_only:
            return 2 if preflight() else 0
        return run(args.tier, args.record, args.allow_dirty)
    except Exception:  # noqa: BLE001 — the point is that ANY crash is not a measurement
        traceback.print_exc()
        print("\n❌ the harness did not complete — NOTHING was measured.\n"
              "   This is exit 3, not 1: no scorecard is valid from this run "
              "and no criterion was judged.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
