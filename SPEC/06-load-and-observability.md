# SPEC/06 — Load Test + Observability

## Observability
X-Ray (or Langfuse) span per graph node: retrieval ms, tokens, cache
hit/miss, tier, confidence. CloudWatch dashboard: p50/p95, cache hit rate,
Bedrock cost/query, HITL rate, current search-session cost. Nightly eval
Lambda: full set if hot tier up, else reduced graph-logic set; pass-rate
metric + regression alarm.

## Load test (loadtest/locustfile.py)
Profiles: 100 and 500 concurrent users, 80/20 repeated/unique questions.
Capture: p50/p95 by tier, cache hit-rate curve, Lambda concurrency,
throttle behavior — verify graceful degradation (honest message, not a
5xx storm) when Bedrock throttles.

## Done when
Both profiles produce report artifacts in loadtest/reports/; dashboard is
screenshot-ready; a Bedrock-throttle chaos test returns the
degraded-but-honest response.
