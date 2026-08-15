# RegDelta — lifecycle
# core   = persistent (~$2/mo idle, incl. S3 Vectors)
# search = ephemeral AOSS hot tier (~$0.24/hr while up)

STACK_CORE   := regdelta-core
STACK_SEARCH := regdelta-search
REGION       ?= us-west-2
SSM_ENDPOINT := /regdelta/search/endpoint
# SPEC/02 "Optional". Passed explicitly into the recipe rather than left to the
# environment: `RERANK=1 make ...` only works in a POSIX shell, and this repo is
# driven from PowerShell as often as from Git Bash. `make retrieval-evals
# RERANK=1` behaves identically in both. `?=` still honours an exported RERANK.
RERANK       ?= 0
# ADR-0009 Ruling 3(a): off is the default and the ruling. Passed through for the
# confirming measurement, which compares lane-off against lane-on at one sha —
# `make retrieval-evals LEXICAL_LANE=1`.
LEXICAL_LANE ?= 0
CDK          := cd infra && npx cdk

# The loopback shim reads its bucket names from the environment and exits if
# they are missing. Resolving them from the deployed stack rather than from the
# operator's shell is the idiom `up` already uses for devPrincipalArn and
# `retrieval-evals` for the tier: the value lives in one place, and a fresh
# clone can run the target. An exported value wins, so an operator pointing
# somewhere else is not overridden. Evaluated inside the recipe, never at parse
# time — `make help` must not need AWS credentials.
#
# This exists because both targets recorded a 0/10 scorecard on 2026-08-15 when
# VECTOR_BUCKET happened to be unset: the shim exited, the fixed `sleep` could
# not tell that from slow startup, and the run measured nothing but connection
# refusals. See evals/wait_ready.py for the other half of that fix.
STACK_Q         = --stack-name $(STACK_CORE) --region $(REGION) --output text --query
RESOLVE_BUCKETS = \
  export VECTOR_BUCKET=$${VECTOR_BUCKET:-$$(MSYS_NO_PATHCONV=1 aws cloudformation \
    describe-stacks $(STACK_Q) "Stacks[0].Outputs[?OutputKey=='VectorBucketName'].OutputValue")} \
    CORPUS_BUCKET=$${CORPUS_BUCKET:-$$(MSYS_NO_PATHCONV=1 aws cloudformation \
    describe-stacks $(STACK_Q) "Stacks[0].Outputs[?OutputKey=='CorpusBucketName'].OutputValue")};

.PHONY: help bootstrap core up down status smoke evals agent-evals discrimination lint test demo ingest-backfill synth diff \
        retrieval-evals retrieval-parity preflight rebuild-vectors

help:
	@echo "make core            - deploy/update persistent stack"
	@echo "make up / make down  - create/destroy AOSS hot tier"
	@echo "make status          - tier state"
	@echo "make smoke / evals   - golden-set checks (definition of done)"
	@echo "make agent-evals     - golden set vs the LOCAL agent graph (SPEC/03)"
	@echo "make discrimination  - can each question tell right from wrong? (no API)"
	@echo "make retrieval-evals - probe set vs the CURRENT tier (SPEC/02 A)"
	@echo "make retrieval-parity- cross-tier gate; needs both runs recorded"
	@echo "                       (ARGS=\"--rerank 1\" gates the RERANK=1 pair)"
	@echo "make preflight       - date-attribution check alone (cheap)"
	@echo "make rebuild-vectors - rebuild S3 Vectors from the corpus (no re-embed)"
	@echo "make lint            - ruff (same scope as the eval gate)"
	@echo "make test            - pytest"
	@echo "make ingest-backfill - one-shot backfill of the demo corpus"
	@echo "make demo            - up + smoke + print demo URL"

bootstrap:
	$(CDK) bootstrap

core:
	$(CDK) deploy $(STACK_CORE) --require-approval never

# Deploys and prints the endpoint. It used to run `smoke` — i.e. the golden
# set through the SPEC/04 API — which made the AOSS half of SPEC/02's
# Done-when unrunnable: bringing the hot tier up required an answering
# endpoint that does not exist until M04. The smoke run moved to `demo`,
# which is where a human wants it. `up` is now a deploy, and nothing else.
#
# devPrincipalArn: AOSS data access is granted ONLY by the collection's data
# access policy, so the operator's own IAM principal needs naming there or
# `retrieval-evals` gets 403 on the AOSS tier. The harness runs in-process by
# design (SPEC/02), which means it runs as whoever invoked it. Resolved from
# STS at deploy time rather than hardcoded, and empty in CI — where nothing
# calls AOSS from a laptop.
up:
	$(CDK) deploy $(STACK_SEARCH) --require-approval never \
	  -c devPrincipalArn=$$(aws sts get-caller-identity --query Arn --output text)
	@echo "✅ Hot tier up ($(SSM_ENDPOINT))"
	@echo "   next: make retrieval-evals   (records the aoss scorecard)"

down:
	$(CDK) destroy $(STACK_SEARCH) --force
	@echo "✅ Hot tier destroyed — OCU billing stopped"

status:
	@aws opensearchserverless list-collections --region $(REGION) \
	  --query "collectionSummaries[?name=='regdelta'].{name:name,status:status}" \
	  --output table 2>/dev/null || true
	@MSYS_NO_PATHCONV=1 aws ssm get-parameter --name $(SSM_ENDPOINT) --region $(REGION) \
	  --query "Parameter.{endpoint:Value,since:LastModifiedDate}" --output table \
	  2>/dev/null || echo "Hot tier: DOWN → retrieval on S3 Vectors"

smoke:
	python evals/run_evals.py --subset smoke

evals:
	python evals/run_evals.py

# Measures the INSTRUMENT, not the system: replays run_evals.check() against
# hand-written right and wrong answers and requires it to tell them apart. No
# API, no corpus, no cost. Run it whenever a question is added or its scoring
# tokens change — the defects it finds are invisible to reading (ADR-0005; the
# 2026-08-12 q07 ruling, defect 4).
discrimination:
	python evals/check_discrimination.py $(ARGS)

# SPEC/02 Done-when (A). Measured at the retrieval contract, in-process —
# not through an answering endpoint, which is M04's.
#
# The tier is DERIVED from the live SSM parameter and then asserted, rather
# than chosen by the caller: `--tier` says what this run must resolve to, and
# the harness exits non-zero if the router resolved something else. That is
# criterion 2. Passing the tier by hand would let a down hot tier record two
# S3 Vectors runs as "both tiers pass".
# MSYS_NO_PATHCONV=1 is load-bearing, not defensive. Git Bash rewrites any
# argument that looks like a POSIX path, so `--name /regdelta/search/endpoint`
# reaches the CLI as `C:/Program Files/Git/regdelta/...` and returns
# ParameterNotFound. This silently reported "s3vectors" while the hot tier was
# up and running, and the harness then measured AOSS under the S3 Vectors
# label — overwriting a valid scorecard with the other tier's results.
#
# An unexpected error FAILS rather than defaulting. Defaulting to s3vectors on
# any failure is what made the mangled path invisible.
retrieval-evals:
	@out=$$(MSYS_NO_PATHCONV=1 aws ssm get-parameter --name $(SSM_ENDPOINT) \
	    --region $(REGION) --query Parameter.Value --output text 2>&1); \
	  if echo "$$out" | grep -q '^https://'; then tier=aoss; \
	  elif echo "$$out" | grep -q 'ParameterNotFound'; then tier=s3vectors; \
	  else echo "cannot determine the search tier: $$out" >&2; exit 1; fi; \
	  echo "→ hot tier $$tier (RERANK=$(RERANK) LEXICAL_LANE=$(LEXICAL_LANE))"; \
	  RERANK=$(RERANK) RETRIEVAL_LEXICAL_LANE=$(LEXICAL_LANE) \
	    python evals/run_retrieval.py --tier $$tier --record

# Criteria 2 and 3 are cross-run: neither invocation above can see the
# other's output. Run retrieval-evals once with the hot tier DOWN and once
# with it UP, on the same commit, then this.
#
# ARGS, not a bare flag: SPEC/02 writes this as `make retrieval-parity --rerank
# 1`, which make parses as its OWN option and rejects. Use
# `make retrieval-parity ARGS="--rerank 1"` — same passthrough as
# rebuild-vectors.
retrieval-parity:
	python evals/run_parity.py $(ARGS)

preflight:
	python evals/run_retrieval.py --tier s3vectors --preflight-only

# Tier A's counterpart to the AOSS reindex Lambda: rebuild the S3 Vectors
# index from the corpus bucket, reusing the embeddings computed at ingest.
# Never embeds, never calls Bedrock, never changes a chunk id. Run this after
# changing what metadata an indexed chunk carries — the alternative is
# re-ingesting, which re-runs the extraction model over documents that have
# not changed.
rebuild-vectors:
	cd src && python -m retrieval.rebuild_s3v $(ARGS)

# M00b control. Reproduces the permanent baseline scorecard: starts the
# loopback shim, runs the full golden set against mode=naive, records it.
baseline:
	@$(RESOLVE_BUCKETS) \
	  python evals/serve_local.py --port 8000 & echo $$! > .baseline.pid; \
	  python evals/wait_ready.py http://127.0.0.1:8000 \
	    || { kill $$(cat .baseline.pid) 2>/dev/null; rm -f .baseline.pid; exit 1; }; \
	  python evals/run_evals.py --mode naive --api-url http://127.0.0.1:8000 --record; \
	  status=$$?; kill $$(cat .baseline.pid) 2>/dev/null; rm -f .baseline.pid; exit $$status

# SPEC/03's Done-when, runnable. `make evals` resolves the API URL from the
# deployed stack, and that endpoint is src/api/api.py — SPEC/04's, still
# NotImplementedError — so the milestone whose exit criterion IS the golden set
# had no command that could run it. Same loopback shim as `baseline`, mode=agent
# instead of naive.
#
# The shim now refuses to share its port (evals/serve_local.py), so a stale
# instance fails this target loudly instead of quietly answering the run with
# the previous commit's code, which is how one scorecard already got filed
# under the wrong sha.
#
# ARGS="--record" to file the scorecard; omitted by default because recording
# is a milestone-close act, not something a routine check should do.
agent-evals:
	@$(RESOLVE_BUCKETS) \
	  python evals/serve_local.py --port 8000 & echo $$! > .agent.pid; \
	  python evals/wait_ready.py http://127.0.0.1:8000 \
	    || { kill $$(cat .agent.pid) 2>/dev/null; rm -f .agent.pid; exit 1; }; \
	  python evals/run_evals.py --mode agent --api-url http://127.0.0.1:8000 $(ARGS); \
	  status=$$?; kill $$(cat .agent.pid) 2>/dev/null; rm -f .agent.pid; exit $$status

# Same scope as the eval-gate `unit` job, so a green local run means a green
# gate. Keep the two in step.
lint:
	ruff check src evals infra tests

test:
	pytest -q

ingest-backfill:
	aws lambda invoke --region $(REGION) --cli-binary-format raw-in-base64-out \
	  --function-name \
	  $$(aws cloudformation describe-stacks --stack-name $(STACK_CORE) --region $(REGION) \
	     --query "Stacks[0].Outputs[?OutputKey=='PollerFnName'].OutputValue" --output text) \
	  --payload '{"mode":"backfill"}' backfill-out.json && cat backfill-out.json && rm -f backfill-out.json

# `up` no longer runs the golden set (see its comment). The smoke run lands
# here instead, so the coverage moved rather than disappearing.
demo: up
	@$(MAKE) --no-print-directory smoke
	@echo "Demo UI: $$(aws cloudformation describe-stacks --stack-name $(STACK_CORE) \
	  --region $(REGION) \
	  --query \"Stacks[0].Outputs[?OutputKey=='DemoUrl'].OutputValue\" --output text)"

synth:
	$(CDK) synth
diff:
	$(CDK) diff
