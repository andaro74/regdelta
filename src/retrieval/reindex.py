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
from shared import config, models

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


def iter_chunk_records(bucket: str):
    """Stream every chunk record in corpus/chunks/**/*.jsonl.

    Public because `evals/check_hydration.py` counts the corpus with it. The
    gate's whole claim is "the index holds every chunk record the corpus has",
    and a second walker with its own idea of what a chunk record is would make
    that claim about two different sets — reporting a mismatch that is really
    a disagreement between the instruments.
    """
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

    The metadata comes from models.to_index_metadata, the same function
    processor._put_vectors and rebuild_s3v use, so the two indexes cannot
    disagree about which keys a chunk carries. Only the id and the vector are
    added here, because only this index stores them that way.
    """
    return {
        "chunk_id": record["chunk_id"],
        "embedding": record["embedding"],
        **models.to_index_metadata(record),
    }


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
        if "index_not_found" not in str(e) and "-> 404" not in str(e):
            raise

    deadline = time.monotonic() + AUTHZ_PROPAGATION_S
    attempt = 0
    while True:
        attempt += 1
        try:
            aoss_client.request(endpoint, "PUT", aoss_client.INDEX_NAME,
                                aoss_client.INDEX_MAPPING)
            if attempt > 1:
                print(json.dumps({"index_created_after_403_retries": attempt}))
            return
        except aoss_client.AossError as e:
            if "-> 403" not in str(e) or time.monotonic() >= deadline:
                raise aoss_client.AossError(
                    f"{e}\n"
                    f"caller={_caller_arn()} endpoint={endpoint} "
                    f"attempts={attempt}\n"
                    "A bare `403 Forbidden` from aoss has THREE causes and the "
                    "response body distinguishes none of them:\n"
                    " (1) a missing x-amz-content-sha256 header — aoss "
                    "requires it and botocore's generic SigV4Auth does not "
                    "emit it (aoss_client sets it; check it is still there);\n"
                    " (2) the caller above is absent from the collection's "
                    "DATA ACCESS POLICY Principal list — an IAM policy "
                    "granting aoss:APIAccessAll is NOT sufficient on its own "
                    "(infra/search/search_stack.py);\n"
                    " (3) that policy has not propagated to the data plane "
                    f"yet — but this call was retried for "
                    f"{AUTHZ_PROPAGATION_S:.0f}s, so (3) is ruled out.\n"
                    "Confirm (2) against the CreateAccessPolicy event in "
                    "CloudTrail, which carries the exact policy submitted."
                ) from e
            time.sleep(AUTHZ_POLL_S)


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


def _count(endpoint: str) -> int | None:
    """Documents in the index — or None if the search path cannot see it yet.

    AOSS decouples ingest compute from search compute, and index metadata
    reaches them separately. So there is a window in which `_bulk` is accepted
    against `chunks` and `chunks/_count` answers 404 index_not_found: not "the
    index is empty" but "this path has not heard of it". Observed on a fresh
    collection — PUT, then a 500-document bulk, then 404 — 11s after the
    Lambda started.

    None rather than 0 because the two mean different things to the caller and
    only one of them is worth waiting out.
    """
    try:
        return aoss_client.request(
            endpoint, "POST", f"{aoss_client.INDEX_NAME}/_count")["count"]
    except aoss_client.AossError as e:
        if "index_not_found" in str(e):
            return None
        raise


def _assert_knn_mapping(endpoint: str) -> None:
    """The index we counted is the index we created.

    Guards the hole that tolerating index_not_found above would otherwise
    open. If a create ever silently no-ops, `_bulk` auto-creates `chunks` with
    a DYNAMIC mapping — the documents land, the count assertion passes, and
    `embedding` is a plain float array instead of a knn_vector. That deploy
    reports success and every kNN query fails afterwards, which is the same
    looks-healthy failure mode the count parity check exists for.

    Fails only on a POSITIVE observation. A dynamic mapping does carry
    `embedding`, typed from the data, so the hazard is still caught — but if
    AOSS ever returns a body this does not recognise, it says so in the log
    and lets the deploy stand. This runs after a full hydration has already
    passed the count assertion, and failing that on an unverified guess about
    a response shape would cost more than the guard is worth.
    """
    body = aoss_client.request(endpoint, "GET", aoss_client.INDEX_NAME)
    props = (body.get(aoss_client.INDEX_NAME, {})
             .get("mappings", {}).get("properties", {}))
    got = props.get("embedding", {}).get("type") if props else None
    if got is None:
        print(json.dumps({"knn_mapping_unverified": list(body)[:8]}))
        return
    if got != "knn_vector":
        raise RuntimeError(
            f"index {aoss_client.INDEX_NAME!r} maps `embedding` as {got!r}, "
            "not 'knn_vector' — it was created dynamically by _bulk rather "
            "than from INDEX_MAPPING. Failing the deploy: the documents are "
            "all there, so nothing else would notice until the first kNN "
            "query.")


COUNT_DEADLINE_S = 300.0
COUNT_POLL_S = 5.0

# How long to keep retrying a 403 on the FIRST write after deploy.
#
# AOSS data access policies are eventually consistent on the data plane.
# CloudFormation reports the policy CREATE_COMPLETE as soon as the control
# plane accepts it, and the CDK Trigger fires immediately after — so the very
# first index creation can be denied by a policy that already exists and is
# already correct. That is what killed the first `make up`: DELETE returned
# 404 (no index yet, evaluated before the policy) and the PUT came back
# `403 Forbidden`.
#
# Scoped deliberately. This retries ONLY 403, ONLY on index creation, and only
# inside this window; a 403 that outlives it still fails the deploy, carrying
# the caller ARN so a genuine principal mismatch reads as one instead of
# looking like slow propagation. Retrying 403 anywhere else would turn a
# permissions bug into a timeout, which is the same bug wearing a disguise.
AUTHZ_PROPAGATION_S = float(os.environ.get("AUTHZ_PROPAGATION_S", "180"))
AUTHZ_POLL_S = 5.0


def _caller_arn() -> str:
    """The identity this Lambda actually signs with. Needs no IAM permission.

    In the error path only: the whole ambiguity of an AOSS 403 is whether the
    calling principal is the one the data access policy names, and every
    minute spent guessing is a redeploy.
    """
    try:
        return boto3.client("sts").get_caller_identity()["Arn"]
    except Exception as e:  # noqa: BLE001 — diagnostics must never mask the 403
        return f"<sts failed: {e}>"


# ---------------------------------------------------------------- the gate
#
# THE ENDPOINT PARAMETER IS HYDRATION'S OUTPUT, NOT THE STACK'S.
#
# `regdelta-search` declares `/regdelta/search/endpoint` as a resource, so
# CloudFormation used to write it the moment the collection had an endpoint —
# with no `DependsOn` on the Trigger at all (verified in
# infra/cdk.out/regdelta-search.template.json). The parameter therefore said
# "the hot tier is up" when what it knew was "a collection exists".
#
# M02 found the consequence and deferred it here (milestones/M02/README.md:591):
# on a stack UPDATE, a Trigger failure rolls the Lambda's environment back but
# NOT the AOSS index contents, and the parameter from the earlier successful
# deploy survives. `router.active_endpoint()` reads only that parameter, so
# retrieval routes to a knowingly-short index and answers, with citations. A
# scorecard can be recorded against it.
#
# So the parameter is retired first and republished last. Between those two
# points there is no endpoint, and `router.active_endpoint()` returns None —
# which routes to S3 Vectors, the always-on tier that is never short. Every
# failure path in this module, including the ones that raise before reaching
# the publish, therefore leaves THE PARAMETER absent.
#
# THAT IS A CLAIM ABOUT THE PARAMETER, NOT ABOUT ITS READERS, and the
# difference is a real residual rather than a quibble. `router.py` memoises
# the endpoint for `_TTL = 60` seconds per container, so for up to a minute
# after the retire a WARM query container still routes to AOSS. The first
# seconds of that are safe — `_create_index` has deleted the index, so the
# tier raises and the router falls back with a `fallback_reason` — but once
# `_bulk` starts landing batches those same containers see a PARTIAL index,
# which answers with citations. That is the dangerous half, bounded at ~60s
# per hydration.
#
# NOT CLOSED HERE, deliberately. The fixes on the table — a hydration
# sentinel the tier checks, or a document-count floor in `aoss_tier` — are
# retrieval-path design, not deploy lifecycle, and this milestone's scope is
# the deploy. Raised by security-reviewer on the M05 branch and carried into
# the milestone's open threads with this cost written down, rather than fixed
# quietly at the end of a session. An earlier draft of this comment asserted
# the stronger claim; it was wrong.
#
# Two CloudFormation behaviours make this safe, and both were RUN rather than
# assumed (milestones/M05/orphan_param_probe.py):
#
#   * DeleteStack succeeds when the parameter is already gone. If it did not,
#     a failed hydration would strand the stack in DELETE_FAILED and an AOSS
#     collection would bill at ~$0.24/hr until someone noticed by hand — a
#     worse bug than the one this fixes.
#   * A later UPDATE that does not change the parameter does not re-create it.
#     If it did, a redeploy would republish the endpoint without re-running
#     hydration and the gate would leak.
#
# The consequence of the second one is worth stating plainly: after a failed
# hydration the parameter stays absent until a deploy actually re-runs this
# Lambda. `make down && make up` always does. A no-op redeploy does not, and
# leaves retrieval on S3 Vectors — the safe direction, and the honest one.

_ssm = None


def _ssm_client():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _retire_endpoint() -> bool:
    """Take the hot tier out of the router. Returns True if one was there.

    The SAME constant `router.active_endpoint()` reads, imported rather than
    spelled again: a writer and a reader that name the parameter separately
    can disagree, and the disagreement looks exactly like a hot tier that is
    down.
    """
    try:
        _ssm_client().delete_parameter(Name=config.SSM_SEARCH_ENDPOINT)
        return True
    except _ssm_client().exceptions.ParameterNotFound:
        return False


def _publish_endpoint(endpoint: str) -> None:
    """Hydration's last act. Reached only if every assertion above passed.

    Overwrite=True because the parameter may still exist: `_retire_endpoint`
    tolerates it being absent, but nothing guarantees a concurrent deploy did
    not put one back.
    """
    _ssm_client().put_parameter(
        Name=config.SSM_SEARCH_ENDPOINT, Value=endpoint, Type="String",
        Overwrite=True,
        Description="Written by the reindex Lambda AFTER count-parity and the "
                    "kNN mapping assert both passed. Absent means retrieval "
                    "routes to S3 Vectors.")


def _await_count(endpoint: str, expected: int,
                 deadline_s: float | None = None) -> int | None:
    """Poll until the index count settles. None = it never became visible.

    AOSS refreshes on its own schedule and does not expose the refresh API, so
    a count read immediately after bulk is meaningless — it is low because the
    index has not refreshed, not because documents are missing. Polling to a
    deadline is what makes the assertion a real one; reading once and raising
    would fail every healthy deploy, and reading once and warning would fail
    none.

    Waiting out a 404 from `_count` is the same argument one step earlier (see
    `_count`), and it is safe for the same reason the 403 retry in
    `_create_index` is: it can only DELAY a failure, never convert one into a
    success. If the index is still missing at the deadline this returns None
    and the handler raises.
    """
    start = time.monotonic()
    end = start + (COUNT_DEADLINE_S if deadline_s is None else deadline_s)
    visible = False
    while True:
        seen = _count(endpoint)
        if seen is not None and not visible:
            visible = True
            print(json.dumps({"index_visible_after_s":
                              round(time.monotonic() - start, 1)}))
        if (seen is not None and seen >= expected) or time.monotonic() >= end:
            return seen
        time.sleep(COUNT_POLL_S)


def handler(event, context):
    bucket = os.environ["CORPUS_BUCKET"]
    endpoint = aoss_client.check_endpoint(os.environ["COLLECTION_ENDPOINT"])

    # FIRST, before the index is touched. `_create_index` DELETEs the index as
    # its opening move, so from here until the republish below there is nothing
    # to serve — and any window in which the parameter still points at this
    # endpoint is a window where retrieval answers from an index being rebuilt.
    retired = _retire_endpoint()
    print(json.dumps({"endpoint_retired": retired,
                      "parameter": config.SSM_SEARCH_ENDPOINT}))

    _create_index(endpoint)

    source = 0
    sent = 0
    dropped = 0
    batch: list[dict] = []
    for record in iter_chunk_records(bucket):
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

    print(json.dumps({"bulk_complete": sent, "awaiting_count": source}))
    indexed = _await_count(endpoint, source)
    result = {"source": source, "sent": sent, "indexed": indexed,
              "dropped": dropped, "index": aoss_client.INDEX_NAME}
    if indexed is None:
        raise RuntimeError(
            f"index {aoss_client.INDEX_NAME!r} was never visible to the search "
            f"path: {sent} documents were accepted by _bulk, then "
            f"{COUNT_DEADLINE_S:.0f}s of _count polling returned 404 "
            f"index_not_found ({json.dumps(result)}). Ingest accepted writes "
            "for an index search cannot resolve, which is longer than "
            "propagation should ever take — suspect the create.")
    if indexed != source:
        raise RuntimeError(
            f"hydration count mismatch: {indexed} indexed vs {source} in the "
            f"corpus ({json.dumps(result)}). Failing the deploy — a partial "
            "index answers with citations and looks healthy.")
    _assert_knn_mapping(endpoint)

    # Both assertions passed. Only now does the hot tier exist as far as
    # `router.active_endpoint()` is concerned.
    _publish_endpoint(endpoint)
    result["endpoint_published"] = config.SSM_SEARCH_ENDPOINT
    result["endpoint_retired"] = retired
    print(json.dumps(result))
    return result
