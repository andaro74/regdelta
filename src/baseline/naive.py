"""M00b naive-RAG baseline — THE CONTROL. See SPEC/00b + ADR-0002.

Deliberately simple: embed query -> S3 Vectors top-8 (no filters, no
fusion, no amendment graph) -> single Claude call -> answer.
Its job is to lose correctly on q01-q04. DO NOT IMPROVE THIS FILE.
Exposed via POST /query?mode=naive forever, so any commit can be compared
against the baseline.

The two seams below (`search=`, `invoke=`) exist so unit tests can run
without AWS. They are not features — nothing in the answer path branches
on them.
"""
import json

import boto3

from shared import config
from shared.citations import extract_citations
from shared.util import retry

_clients: dict = {}


def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name, region_name=config.REGION)
    return _clients[name]


# No domain rules, no date semantics, no supersession handling — that is
# exactly the point. Later milestones earn their delta against this.
_PROMPT = """Answer the question using the passages below.

Passages:
{passages}

Question: {question}
"""


def _embed(text: str) -> list[float]:
    resp = retry(lambda: _client("bedrock-runtime").invoke_model(
        modelId=config.EMBED_MODEL,
        body=json.dumps({"inputText": text[:30000],
                         "dimensions": config.EMBED_DIM,
                         "normalize": True})))
    return json.loads(resp["body"].read())["embedding"]


def _search(question: str, k: int) -> list[dict]:
    """Top-k nearest chunks. No metadata filter, by design."""
    vec = _embed(question)  # hoisted: _embed retries on its own, and
    # embedding inside the lambda would re-embed on every query retry.
    resp = retry(lambda: _client("s3vectors").query_vectors(
        vectorBucketName=config.VECTOR_BUCKET,
        indexName=config.VECTOR_INDEX,
        queryVector={"float32": vec},
        topK=k,
        returnMetadata=True,
        returnDistance=True))
    return resp.get("vectors", [])


def _invoke(prompt: str) -> tuple[str, str]:
    resp = retry(lambda: _client("bedrock-runtime").converse(
        modelId=config.NAIVE_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1500, "temperature": 0}))
    blocks = resp["output"]["message"]["content"]
    text = next((b["text"] for b in blocks if "text" in b), "")
    return text, resp.get("stopReason", "")


def answer_naive(question: str, search=None, invoke=None) -> dict:
    hits = (search or _search)(question, config.NAIVE_TOP_K)

    passages = []
    for h in hits:
        md = h.get("metadata") or {}
        if not md.get("chunk_text"):
            continue
        cite = md.get("citation_path") or md.get("fr_doc_number") or h.get("key", "")
        passages.append(f"[{cite}]\n{md['chunk_text']}")

    # No passages means retrieval failed (unhydrated index, wrong bucket).
    # Answering anyway would let the model reply from parametric memory —
    # it knows these regulations — and the control would be scoring world
    # knowledge instead of naive RAG. Fail visibly instead.
    if not passages:
        return {"answer": "", "citations": [], "status": "no_context",
                "mode": "naive", "retrieved": [h.get("key") for h in hits]}

    answer, stop_reason = (invoke or _invoke)(
        _PROMPT.format(passages="\n\n".join(passages), question=question))

    return {
        "answer": answer,
        # "whatever the model emits" (SPEC/00b) — no verification that a
        # cited section actually supports the claim. That gap is the point.
        "citations": extract_citations(answer),
        "status": "answered",
        "mode": "naive",
        # A max_tokens cut-off would drop a required date and look like a
        # substantive miss in a scorecard we can never re-run identically.
        "truncated": stop_reason == "max_tokens",
        "retrieved": [h.get("key") for h in hits],
        # Provenance: the baseline scorecard is a permanent reference point,
        # so the run must record which model and k produced it.
        "provenance": {"model": config.NAIVE_MODEL, "top_k": config.NAIVE_TOP_K},
    }
