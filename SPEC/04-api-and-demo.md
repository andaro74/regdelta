# SPEC/04 — API + Demo UI

## API (src/api/api.py — FastAPI + Mangum on Lambda)
- POST /query {question, company_profile?} → {answer_rows[], citations[],
  confidence, status, trace_id}
- POST /resume/{checkpoint_id} {reviewer_decision} → final answer
- GET  /health → includes active retrieval tier (aoss|s3vectors)
- Response cache: DynamoDB exact-match on normalized question hash, TTL 1h.
  Semantic cache OFF by default (flag SEMANTIC_CACHE=1) — a wrong cache hit
  in compliance is worse than a slow answer.

## UI (ui/ — static, S3+CloudFront)
Single page: question box; 3 canned scenario buttons; verdict table with
citation links (federalregister.gov / ecfr.gov); confidence badges;
"needs human review" state; active-tier indicator + retrieval latency
readout (the live tier-switch demo moment).

## Done when
Canned query #1 renders the full Nordvale table in a browser against the
deployed stack; /health reports the correct tier before and after
`make up`; a cached repeat query returns < 500ms.
