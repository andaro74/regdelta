# RegDelta — lifecycle
# core   = persistent (~$2/mo idle, incl. S3 Vectors)
# search = ephemeral AOSS hot tier (~$0.24/hr while up)

STACK_CORE   := regdelta-core
STACK_SEARCH := regdelta-search
REGION       ?= us-west-2
SSM_ENDPOINT := /regdelta/search/endpoint
CDK          := cd infra && npx cdk

.PHONY: help bootstrap core up down status smoke evals test demo ingest-backfill synth diff

help:
	@echo "make core            - deploy/update persistent stack"
	@echo "make up / make down  - create/destroy AOSS hot tier"
	@echo "make status          - tier state"
	@echo "make smoke / evals   - golden-set checks (definition of done)"
	@echo "make test            - pytest"
	@echo "make ingest-backfill - one-shot backfill of the demo corpus"
	@echo "make demo            - up + smoke + print demo URL"

bootstrap:
	$(CDK) bootstrap

core:
	$(CDK) deploy $(STACK_CORE) --require-approval never

up:
	$(CDK) deploy $(STACK_SEARCH) --require-approval never
	@$(MAKE) --no-print-directory smoke
	@echo "✅ Hot tier up ($(SSM_ENDPOINT))"

down:
	$(CDK) destroy $(STACK_SEARCH) --force
	@echo "✅ Hot tier destroyed — OCU billing stopped"

status:
	@aws opensearchserverless list-collections --region $(REGION) \
	  --query "collectionSummaries[?name=='regdelta'].{name:name,status:status}" \
	  --output table 2>/dev/null || true
	@aws ssm get-parameter --name $(SSM_ENDPOINT) --region $(REGION) \
	  --query "Parameter.{endpoint:Value,since:LastModifiedDate}" --output table \
	  2>/dev/null || echo "Hot tier: DOWN → retrieval on S3 Vectors"

smoke:
	python evals/run_evals.py --subset smoke

evals:
	python evals/run_evals.py

test:
	pytest -q

ingest-backfill:
	aws lambda invoke --region $(REGION) --cli-binary-format raw-in-base64-out \
	  --function-name \
	  $$(aws cloudformation describe-stacks --stack-name $(STACK_CORE) --region $(REGION) \
	     --query "Stacks[0].Outputs[?OutputKey=='PollerFnName'].OutputValue" --output text) \
	  --payload '{"mode":"backfill"}' backfill-out.json && cat backfill-out.json && rm -f backfill-out.json

demo: up
	@echo "Demo UI: $$(aws cloudformation describe-stacks --stack-name $(STACK_CORE) \
	  --region $(REGION) \
	  --query \"Stacks[0].Outputs[?OutputKey=='DemoUrl'].OutputValue\" --output text)"

synth:
	$(CDK) synth
diff:
	$(CDK) diff
