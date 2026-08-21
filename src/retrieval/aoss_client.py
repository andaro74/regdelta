"""Minimal SigV4 OpenSearch Serverless client — shared by the query path and
the reindex Lambda.

No new dependencies. `opensearch-py` + `requests-aws4auth` (the obvious
choice, and what the reindex TODO originally named) would need a Lambda layer
or a bundling step for two things botocore already does: sign a request and
send it. botocore ships in every Lambda runtime, so this file is ~60 lines
against ~40 MB of layer and a build step.

ONE copy, imported by both callers. The reindex Lambda and the query tier
must agree on the index name, the mapping and the document shape; the last
time this repo kept two copies of a mapping in sync by hand (_EDGE_PREDICATE,
M01c) they drifted and the failure surfaced after the writes had landed.
"""
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request

import botocore.session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from shared import config

INDEX_NAME = "chunks"

# Document shape. Field names match S3 Vectors metadata exactly
# (processor._put_vectors) so Chunk.from_metadata reads both tiers.
INDEX_MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {"properties": {
        "chunk_id":        {"type": "keyword"},
        "chunk_text":      {"type": "text"},
        "citation_path":   {"type": "text",
                            "fields": {"raw": {"type": "keyword"}}},
        "embedding":       {"type": "knn_vector", "dimension": config.EMBED_DIM,
                            "method": {"name": "hnsw", "engine": "faiss",
                                       "space_type": "cosinesimil"}},
        # What the chunker labelled this chunk: dates | summary | amdpar |
        # preamble | regtext. It was in the corpus JSONL from M01 and neither
        # index writer copied it, so retrieval had to rebuild "which paragraph
        # states what this document does" out of a DynamoDB citations GSI.
        "kind":            {"type": "keyword"},
        "doc_type":        {"type": "keyword"},
        "cfr_title":       {"type": "keyword"},
        "cfr_part":        {"type": "keyword"},
        "fr_doc_number":   {"type": "keyword"},
        "pub_date":        {"type": "date"},
        "effective_date":  {"type": "date"},
        "compliance_date": {"type": "date"},
        "version_date":    {"type": "date"},
    }},
}

# The endpoint arrives from SSM /regdelta/search/endpoint, which CDK writes.
# That is an account-controlled value rather than a response body, so this is
# not the SSRF boundary shared/fetch.py guards — but it is still a URL this
# code will sign a credentialed request to, and an SSM parameter is writable
# by anything holding ssm:PutParameter. Pinning the host shape means a
# tampered parameter cannot redirect signed AOSS requests to an arbitrary
# host: SigV4 headers scoped to service 'aoss' would be handed to whoever
# answered.
_ENDPOINT_RE = re.compile(
    r"\Ahttps://[a-z0-9]{3,64}\.[a-z0-9-]{1,32}\.aoss\.amazonaws\.com\Z")


class AossError(RuntimeError):
    pass


def check_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").rstrip("/")
    if not _ENDPOINT_RE.match(endpoint):
        raise AossError(
            f"refusing to sign a request to {endpoint!r}: not an AOSS "
            "collection endpoint (https://<id>.<region>.aoss.amazonaws.com)")
    return endpoint


#: The botocore session, built ONCE. Same idiom, and the same reason, as
#: `s3vectors_tier._clients`.
#:
#: `botocore.session.get_session()` CONSTRUCTS A NEW SESSION every call — it is
#: not a cached accessor, whatever the name suggests — and `get_credentials()`
#: then runs the whole resolver chain against it. `request()` did that once per
#: AOSS request.
#:
#: MEASURED OFFLINE, local CPU only, no network: 6.404 ms median, 64.5 ms max,
#: against 0.000 ms for frozen credentials off a reused session (n=30).
#: For comparison the SigV4 signing both tiers pay is 0.139 ms.
#:
#: This is a MEASUREMENT-VALIDITY defect and not a performance nicety, because
#: of where it lands and what it is made of. It is inside `router.retrieve()` —
#: the interval SPEC/06's disposition defines its p95 over — it is on the AOSS
#: path only, so Tier A never pays it, and it is pure Python, so it is
#: serialised on the GIL. At the clause's top step of 90 calls per second that
#: is 90 x 6.4 = 576 ms of CPU per second of wall clock in a 2048 MB Lambda
#: (~1.2 vCPU), which does not merely add 6 ms per call: it saturates and
#: queues, and everything behind it in the interpreter waits.
#:
#: Retiring Tier B on a number that includes it would be retiring it for this
#: repo's own client. Found while pricing the disposition, after
#: security-reviewer's connection-pool finding on the other tier.
#:
#: THE CONNECTION POOL IS THE LARGER HALF AND IS NOT FIXED HERE.
#: `urllib.request.urlopen` opens a fresh TCP + TLS connection on every call,
#: because nothing installs an opener holding a pool, while botocore keeps a
#: urllib3 pool per client. That is a structural difference between the two
#: tiers' transports, it is not measurable offline, and unlike this one it
#: cannot be fixed in four lines. It is raised with the seat rather than
#: changed unilaterally in the week Tier B is being disposed of.
_session = None
#: Same reason as `s3vectors_tier._clients_lock`: check-then-set, first
#: exercised by many threads at once. Benign here — the loser only rebuilds a
#: session — but duplicated work in the one window the memo exists to avoid.
_session_lock = threading.Lock()


def _credentials():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = botocore.session.get_session()
    creds = _session.get_credentials()
    if creds is None:
        raise AossError("no AWS credentials available for SigV4")
    # FROZEN PER CALL, not cached. The frozen triple is a point-in-time copy,
    # and a container that outlives a credential refresh would sign with an
    # expired key — a 403 that reads exactly like a data-access-policy denial,
    # which is the failure mode this file's endpoint check already exists to
    # keep distinguishable. `get_credentials()` on a live session is the cheap
    # half; it was the session construction that cost 6.4 ms.
    return creds.get_frozen_credentials()


def request(endpoint: str, method: str, path: str, body=None,
            *, content_type: str = "application/json", timeout: int = 60):
    """Signed request. Returns the parsed JSON body.

    Raises AossError on any non-2xx, carrying the response body — an
    OpenSearch error is a JSON document explaining itself, and swallowing it
    turns a mapping typo into 'the index came back empty'.
    """
    endpoint = check_endpoint(endpoint)
    if body is None:
        data = None
    elif isinstance(body, bytes):
        data = body
    else:
        data = json.dumps(body).encode()

    url = f"{endpoint}/{path.lstrip('/')}"
    # x-amz-content-sha256 is REQUIRED by aoss, and its absence is reported as
    # a plain `403 Forbidden` with an OpenSearch-shaped body — indistinguishable
    # from a data-access-policy denial, which is what cost two deploys here.
    # botocore's generic SigV4Auth folds the payload hash into the canonical
    # request but never emits it as a header (only S3SigV4Auth does), so a
    # hand-rolled signer looks correct and is rejected. This is exactly what
    # opensearch-py's AWSV4SignerAuth special-cases for the 'aoss' service.
    #
    # Set BEFORE signing so it is covered by SignedHeaders. botocore hashes the
    # same bytes for the canonical request, so the two always agree.
    headers = {"Content-Type": content_type,
               "X-Amz-Content-Sha256": hashlib.sha256(data or b"").hexdigest()}
    aws = AWSRequest(method=method, url=url, data=data, headers=headers)
    # AOSS rejects UNSIGNED-PAYLOAD, so the body must be signed for real.
    SigV4Auth(_credentials(), "aoss", config.REGION).add_auth(aws)

    req = urllib.request.Request(url, data=data, method=method,
                                 headers=dict(aws.headers))
    # AossError is this tier's ENTIRE failure contract, and that is load-bearing
    # rather than tidy: router.retrieve_traced catches AossError and nothing
    # else, so anything escaping unwrapped defeats the "a deployed-but-broken hot
    # tier must not take the API down" fallback. Converting only HTTPError left
    # the fallback missing for the state it most needs to cover — SSM parameter
    # present, collection unreachable — which is the live window between
    # `make down` deleting the collection and the endpoint cache expiring.
    # HTTPError must be caught FIRST: it subclasses URLError.
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        raise AossError(f"{method} {path} -> {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # DNS failure, connection refused/reset, TLS failure, read timeout. No
        # status code exists, so the reason is all the caller gets — it still
        # reaches the scorecard's `fallbacks` field via the router.
        raise AossError(f"{method} {path} -> unreachable: "
                        f"{type(e).__name__}: {e}") from e
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        # A 200 with a non-JSON body — a proxy or error page in front of the
        # collection. Wrapped for the same reason: unwrapped it bypasses the
        # fallback and surfaces as a 500 at M04.
        raise AossError(f"{method} {path} -> 200 with a non-JSON body: "
                        f"{raw[:200]!r}") from e
