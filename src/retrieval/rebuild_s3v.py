"""Rebuild the S3 Vectors index from the corpus bucket (Tier A hydration).

The architecture rule says search indexes are pure functions of the corpus
bucket. Until now only AOSS had a rebuild path — `retrieval.reindex`, which
runs on every deploy of the ephemeral stack. Tier A's index was only ever
written as a side effect of ingestion, so changing what metadata it stores
meant re-ingesting: re-fetching every document, re-running Claude extraction
over it, and re-embedding. That is expensive, slow, and it puts the model back
in the loop for what is a pure reshaping of data already on disk.

This is the counterpart. It reads `corpus/chunks/**/*.jsonl`, which already
carries every chunk's embedding, and rewrites the vector index from it.

**It never embeds.** The vectors are the ones computed once at ingest
(architecture rule). PutVectors is an upsert keyed on chunk_id, so chunk ids
do not change and probes authored against them stay valid — which is what
makes this safe to run against a live index and a re-ingest not.

    python -m retrieval.rebuild_s3v --dry-run     # counts only, no writes
    python -m retrieval.rebuild_s3v
"""
import argparse
import json
import sys

import boto3

from shared import config, models

CORPUS_PREFIX = "chunks/"
PUT_BATCH = 100          # S3 Vectors PutVectors limit


def _clients():
    return (boto3.client("s3", region_name=config.REGION),
            boto3.client("s3vectors", region_name=config.REGION))


def iter_chunk_records(s3, bucket: str):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=CORPUS_PREFIX):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".jsonl"):
                continue
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)


def rebuild(dry_run: bool = False) -> dict:
    s3, sv = _clients()
    written = 0
    batch: list[dict] = []
    kinds: dict[str, int] = {}

    def flush():
        nonlocal written, batch
        if batch and not dry_run:
            sv.put_vectors(vectorBucketName=config.VECTOR_BUCKET,
                           indexName=config.VECTOR_INDEX, vectors=batch)
        written += len(batch)
        batch = []

    for record in iter_chunk_records(s3, config.CORPUS_BUCKET):
        embedding = record.get("embedding")
        if not embedding:
            # Refuse rather than skip. A chunk written without its vector is
            # unreachable by search while still present in the corpus, so
            # skipping it would quietly shrink the index and every downstream
            # count would still agree with itself.
            raise ValueError(
                f"{record.get('chunk_id')!r} has no embedding in the corpus; "
                "refusing to rebuild from an incomplete source (this utility "
                "never embeds — see the module docstring)")
        if len(embedding) != config.EMBED_DIM:
            raise ValueError(
                f"{record['chunk_id']!r} embedding is {len(embedding)}-dim, "
                f"expected {config.EMBED_DIM}")
        kinds[record.get("kind") or "<none>"] = \
            kinds.get(record.get("kind") or "<none>", 0) + 1
        batch.append({"key": record["chunk_id"],
                      "data": {"float32": embedding},
                      "metadata": models.to_index_metadata(record)})
        if len(batch) >= PUT_BATCH:
            flush()
    flush()

    if written == 0:
        raise RuntimeError(
            f"no chunk records under s3://{config.CORPUS_BUCKET}/"
            f"{CORPUS_PREFIX} — refusing to report a healthy empty rebuild")
    return {"written": written, "kinds": kinds, "dry_run": dry_run}


def main() -> int:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2] / "evals"))
    from run_retrieval import resolve_stack_env
    resolve_stack_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="read and validate the corpus, write nothing")
    args = ap.parse_args()
    print(json.dumps(rebuild(args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
