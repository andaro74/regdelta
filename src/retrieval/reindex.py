"""Hydrate the AOSS hot tier from the corpus bucket (SPEC/02 Tier B).

Runs on every deploy of regdelta-search as a CDK Trigger. Pure I/O — chunk
records already carry their Titan v2 embeddings; NEVER re-embed here
(architecture rule).

Contract: raise on any count mismatch. A failed Trigger fails `make up`,
which is exactly right — never report success on a partial index. A partial
index does not look broken from the outside: it answers, with citations, and
the missing chunks are invisible.
"""
import json
import os
import time

import boto3

from retrieval import aoss_client

CORPUS_PREFIX = "chunks/"
BULK_BATCH = 500

# Deliberate-fault hook for SPEC/02 (B): drop this many chunk records so the
# count assertion fails and the deploy fails with it. The evidence M02 owes is
# a real failed CloudFormation event, not a unit test asserting that a raise
# raises.
#
# Deliberately one-directional: this can only cause a FAILING deploy. There is
# no switch anywhere in this file that relaxes or skips the count assertion, so
# the fault hook cannot produce the outcome it exists to test for — a partial
# index that reports success.
FAULT_DROP = int(os.environ.get("REINDEX_FAULT_DROP", "0"))

_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _iter_chunk_records(bucket: str):
    """Stream every chunk record in corpus/chunks/**/*.jsonl."""
    paginator = _s3_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=CORPUS_PREFIX):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".jsonl"):
                continue
            body = _s3_client().get_object(
                Bucket=bucket, Key=obj["Key"])["Body"].read()
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)


def _document(record: dict) -> dict:
    """Chunk JSONL record -> AOSS document.

    Key names match S3 Vectors metadata (processor._put_vectors) so
    Chunk.from_metadata reads both tiers. `text` is renamed to `chunk_text`
    for the same reason — the JSONL calls it `text`, S3 Vectors calls it
    `chunk_text`, and the tiers must not each learn both names.

    Null dates are omitted rather than sent as null: the mapping types them as
    `date`, and an explicit null would be accepted but a missing field is what
    makes a range query exclude the document. ADR-0006's rule (a document is
    selected only by a date it establishes) then falls out of the mapping.
    """
    doc = {
        "chunk_id": record["chunk_id"],
        "chunk_text": record.get("text") or "",
        "citation_path": record.get("citation_path") or "",
        "embedding": record["embedding"],
    }
    for key in ("doc_type", "cfr_title", "cfr_part", "fr_doc_number",
                "pub_date", "effective_date", "compliance_date", "version_date"):
        if record.get(key):
            doc[key] = record[key]
    return doc


def _create_index(endpoint: str) -> None:
    """Recreate the index from scratch.

    The hot tier is a pure function of the corpus bucket and the stack is
    ephemeral, so rebuilding is cheaper and far more honest than reconciling:
    a leftover document from a previous corpus is a citation to text that is
    no longer in the corpus. Recreating also means AOSS can assign its own
    document ids — `chunk_id` lives in the source, which sidesteps the
    serverless custom-document-id question entirely.
    """
    try:
        aoss_client.request(endpoint, "DELETE", aoss_client.INDEX_NAME)
    except aoss_client.AossError as e:
        if "index_not_found" not in str(e) and "404" not in str(e):
            raise
    aoss_client.request(endpoint, "PUT", aoss_client.INDEX_NAME,
                        aoss_client.INDEX_MAPPING)


def _bulk(endpoint: str, docs: list[dict]) -> None:
    header = json.dumps({"index": {"_index": aoss_client.INDEX_NAME}})
    lines = []
    for doc in docs:
        lines.append(header)
        lines.append(json.dumps(doc))
    payload = ("\n".join(lines) + "\n").encode()
    resp = aoss_client.request(endpoint, "POST", "_bulk", payload,
                               content_type="application/x-ndjson",
                               timeout=120)
    if resp.get("errors"):
        first = next((i["index"]["error"] for i in resp.get("items", [])
                      if i.get("index", {}).get("error")), None)
        raise aoss_client.AossError(f"bulk index reported errors: {first}")


def _count(endpoint: str) -> int:
    return aoss_client.request(endpoint, "POST",
                               f"{aoss_client.INDEX_NAME}/_count")["count"]


COUNT_DEADLINE_S = 300.0
COUNT_POLL_S = 5.0


def _await_count(endpoint: str, expected: int,
                 deadline_s: float | None = None) -> int:
    """Poll until the index count settles.

    AOSS refreshes on its own schedule and does not expose the refresh API, so
    a count read immediately after bulk is meaningless — it is low because the
    index has not refreshed, not because documents are missing. Polling to a
    deadline is what makes the assertion a real one; reading once and raising
    would fail every healthy deploy, and reading once and warning would fail
    none.
    """
    end = time.monotonic() + (COUNT_DEADLINE_S if deadline_s is None else deadline_s)
    while True:
        seen = _count(endpoint)
        if seen >= expected or time.monotonic() >= end:
            return seen
        time.sleep(COUNT_POLL_S)


def handler(event, context):
    bucket = os.environ["CORPUS_BUCKET"]
    endpoint = aoss_client.check_endpoint(os.environ["COLLECTION_ENDPOINT"])

    _create_index(endpoint)

    source = 0
    sent = 0
    dropped = 0
    batch: list[dict] = []
    for record in _iter_chunk_records(bucket):
        source += 1
        if dropped < FAULT_DROP:
            dropped += 1
            continue
        batch.append(_document(record))
        if len(batch) >= BULK_BATCH:
            _bulk(endpoint, batch)
            sent += len(batch)
            batch = []
    if batch:
        _bulk(endpoint, batch)
        sent += len(batch)

    if source == 0:
        raise RuntimeError(
            f"no chunk records under s3://{bucket}/{CORPUS_PREFIX} — refusing "
            "to report a healthy empty index (an empty hot tier answers every "
            "query with nothing and looks like a retrieval bug, not a deploy "
            "bug)")

    indexed = _await_count(endpoint, source)
    result = {"source": source, "sent": sent, "indexed": indexed,
              "dropped": dropped, "index": aoss_client.INDEX_NAME}
    if indexed != source:
        raise RuntimeError(
            f"hydration count mismatch: {indexed} indexed vs {source} in the "
            f"corpus ({json.dumps(result)}). Failing the deploy — a partial "
            "index answers with citations and looks healthy.")
    print(json.dumps(result))
    return result
