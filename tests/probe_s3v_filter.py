#!/usr/bin/env python3
"""Reproduce which S3 Vectors metadata filter operators actually work.

NOT a pytest test — it needs live AWS, and pytest does not collect
`probe_*.py`. It exists because s3vectors_tier.py makes a load-bearing claim
about the service ("range operators are rejected on string metadata") and a
claim like that in a comment is an unverified assertion until something can
re-run it. ADR-0005's second-order lesson, applied.

    python tests/probe_s3v_filter.py

Expected output as of 2026-08-08 (us-west-2):
    OK    eq / and / exists
    FAIL  gte / lte  -> ValidationException: Invalid filter
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import boto3  # noqa: E402

from shared import config  # noqa: E402

CASES = {
    "eq":         {"cfr_part": {"$eq": "101"}},
    "eq-bare":    {"cfr_part": "101"},
    "and":        {"$and": [{"cfr_title": {"$eq": "21"}},
                            {"cfr_part": {"$eq": "101"}}]},
    "exists":     {"compliance_date": {"$exists": True}},
    "gte":        {"compliance_date": {"$gte": "2028-01-01"}},
    "gte-lte":    {"compliance_date": {"$gte": "2028-01-01",
                                       "$lte": "2028-12-31"}},
}


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))
    from run_retrieval import resolve_stack_env
    resolve_stack_env()

    sv = boto3.client("s3vectors", region_name=config.REGION)
    vector = [0.0] * config.EMBED_DIM
    vector[0] = 1.0
    worked = []
    for name, flt in CASES.items():
        try:
            resp = sv.query_vectors(
                vectorBucketName=config.VECTOR_BUCKET,
                indexName=config.VECTOR_INDEX, topK=3,
                queryVector={"float32": vector}, filter=flt,
                returnMetadata=True)
        except Exception as e:  # noqa: BLE001 — the failure IS the result
            print(f"FAIL {name:8} {type(e).__name__}: {str(e)[:90]}")
        else:
            worked.append(name)
            print(f"OK   {name:8} {len(resp.get('vectors', []))} hits")
    print(f"\nsupported: {worked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
