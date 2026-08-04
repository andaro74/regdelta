"""FastAPI surface (SPEC/04): POST /query, POST /resume/{id}, GET /health.
/health must report retrieval router's active_tier(). Exact-match response
cache in DynamoDB (TTL 1h); semantic cache behind SEMANTIC_CACHE flag."""


def handler(event, context):  # Mangum wraps the FastAPI app here
    raise NotImplementedError("SPEC/04")
