"""Hydrate the AOSS hot tier from the corpus bucket. Runs on every deploy
of regdelta-search (CDK Trigger). Pure I/O — chunk records already carry
their Titan v2 embeddings; NEVER re-embed here.

Contract (SPEC/02): raise on any count mismatch — a failed Trigger fails
`make up`, which is exactly right: never report success on a partial index.
"""
import json
import os

import boto3
# TODO(SPEC/02): layer deps -> opensearch-py + requests-aws4auth
# from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
# from requests_aws4auth import AWS4Auth

CORPUS_BUCKET = os.environ["CORPUS_BUCKET"]
ENDPOINT = os.environ["COLLECTION_ENDPOINT"]
INDEX_NAME = os.environ.get("INDEX_NAME", "chunks")

INDEX_MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {"properties": {
        "chunk_text":      {"type": "text"},
        "citation_path":   {"type": "text",
                            "fields": {"raw": {"type": "keyword"}}},
        "embedding":       {"type": "knn_vector", "dimension": 1024,
                            "method": {"name": "hnsw", "engine": "faiss",
                                       "space_type": "cosinesimil"}},
        "doc_type":        {"type": "keyword"},
        "cfr_title":       {"type": "keyword"},
        "cfr_part":        {"type": "keyword"},
        "fr_doc_number":   {"type": "keyword"},
        "pub_date":        {"type": "date"},
        "effective_date":  {"type": "date"},
        "compliance_date": {"type": "date"},
    }},
}

s3 = boto3.client("s3")


def handler(event, context):
    """TODO(SPEC/02):
    1. SigV4 ('aoss') OpenSearch client vs ENDPOINT.
    2. Create INDEX_NAME with INDEX_MAPPING if absent (idempotent).
    3. Stream s3://CORPUS_BUCKET/chunks/**/*.jsonl.
    4. helpers.bulk(), 500/batch, parallel by cfr_part prefix.
    5. Refresh; assert indexed == source count; return both counts.
    """
    raise NotImplementedError("Implement per SPEC/02-knowledge-base.md")
