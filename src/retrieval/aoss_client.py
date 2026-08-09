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
import json
import re
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
    headers = {"Content-Type": content_type}
    aws = AWSRequest(method=method, url=url, data=data, headers=headers)
    creds = botocore.session.get_session().get_credentials()
    if creds is None:
        raise AossError("no AWS credentials available for SigV4")
    # AOSS requires the real payload hash — it rejects UNSIGNED-PAYLOAD.
    SigV4Auth(creds.get_frozen_credentials(), "aoss", config.REGION).add_auth(aws)

    req = urllib.request.Request(url, data=data, method=method,
                                 headers=dict(aws.headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        raise AossError(f"{method} {path} -> {e.code}: {detail}") from e
    return json.loads(raw) if raw else {}
