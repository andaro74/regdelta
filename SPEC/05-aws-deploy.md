# SPEC/05 — Deploy + Lifecycle

## Stacks (infra/)
- regdelta-core (persistent): corpus bucket, S3 Vectors vector bucket +
  index, DynamoDB x2, ingestion (EventBridge/SQS/Lambdas), query Lambda +
  HTTP API, UI bucket + CloudFront, nightly eval Lambda, janitor.
- regdelta-search (ephemeral): AOSS VECTORSEARCH collection
  (standby_replicas=DISABLED), 3 policies, reindex Lambda + deploy Trigger,
  SSM endpoint param. Dedicated CFN execution role so the janitor can
  delete via PassRole (closes the TODO in core_stack.py).

## Lifecycle
make core | up | down | status | demo. `make up` fails if hydration
count-parity fails. Janitor: 01:00 UTC deletes regdelta-search if up.

## Security tightening (close all scaffold TODOs)
Bedrock IAM scoped to exact model ARNs; aoss:APIAccessAll scoped to the
collection ARN; AOSS data access policy split write(reindex)/read(query).

DynamoDB state-table access split: the query Lambda's role may read and write
`THREAD#*` and write `REVIEW#*`, and may **not** read `REVIEW#*` — that queue
carries the asker's question text and is the SME seat's to read (ROLES.md).
Deferred here from SPEC/04, which has no endpoint that touches it. Recorded in
both files deliberately: a deferral that exists only as a pointer in the
milestone deferring it is a deferral the receiving milestone never got.

## Done when
Fresh account: bootstrap → `make core && make up && make evals` green →
`make down && make evals` still green (S3 Vectors tier) → `make up` green
again. `cdk destroy regdelta-search` is never blocked by core.
