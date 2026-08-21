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

# The loopback shim runs the real graph in-process, so it needs the same
# configuration the deployed function has — buckets, tables, the search-endpoint
# parameter — and it exits if any of it is missing. Those values come from the
# DEPLOYED LAMBDA'S OWN ENVIRONMENT rather than from the operator's shell or from
# hand-picked CloudFormation outputs: it is what production runs with, CDK sets
# it, and a variable added to the function reaches this target with no change
# here. Already-exported values win. Evaluated inside the recipe, never at parse
# time — `make help` must not need AWS credentials.
#
# This exists because both targets recorded a 0/10 scorecard on 2026-08-15 with
# VECTOR_BUCKET unset, and then failed a second time on REGISTRY_TABLE, which the
# stack does not export at all. Chasing outputs one at a time was the wrong fix.
# See evals/local_env.py and evals/wait_ready.py.
RESOLVE_ENV = eval "$$(python evals/local_env.py)";
# The same thing, but FATAL when the resolve fails. `eval "$(...)"`
# discards the exit code, so a throttled `aws lambda list-functions` leaves
# REGISTRY_TABLE unset, `corpus_fingerprint()` records
# `{"available": false}`, and `corpus_drift()` returns None with nothing
# printed — the silent switch-off the targets below claim to prevent.
# Used where a run PRODUCES EVIDENCE or gates on it; the deploy targets
# keep the lenient form because the hydration gate already names an
# unresolved bucket as a refusal in its own report.
RESOLVE_ENV_STRICT = env=$$(python evals/local_env.py) || { echo "cannot resolve the deployed environment; refusing to record or gate on an unconfigured run" >&2; exit 1; }; eval "$$env";

.PHONY: help bootstrap layer core up down status smoke evals agent-evals discrimination replay-history lint test demo ingest-backfill synth diff \
        retrieval-evals retrieval-parity preflight rebuild-vectors demo-parity fault-drop \
        tier-disposition tier-disposition-price opus-headroom

help:
	@echo "make layer           - build the Lambda dependency layer (needed by core)"
	@echo "make core            - deploy/update persistent stack"
	@echo "make up / make down  - create/destroy AOSS hot tier"
	@echo "make status          - tier state"
	@echo "make fault-drop      - deploy with hydration deliberately broken;"
	@echo "                       FAILS if the endpoint ends up naming a short"
	@echo "                       index (SPEC/05 item 4)"
	@echo "make smoke / evals   - golden-set checks (definition of done)"
	@echo "make agent-evals     - golden set vs the LOCAL agent graph (SPEC/03)"
	@echo "make discrimination  - can each question tell right from wrong? (no API)"
	@echo "make replay-history  - would it have scored the answers we really got?"
	@echo "make retrieval-evals - probe set vs the CURRENT tier (SPEC/02 A)"
	@echo "make retrieval-parity- cross-tier gate; needs both runs recorded"
	@echo "                       (ARGS=\"--rerank 1\" gates the RERANK=1 pair)"
	@echo "make demo-parity     - answer-level cross-tier gate + Tier B latency"
	@echo "                       (SPEC/04; run once per tier, then it judges)"
	@echo "make tier-disposition- SPEC/06: dispose of Tier B. Run once per tier"
	@echo "                       across ONE up/down cycle at one sha"
	@echo "make tier-disposition-price - what that would cost. Invokes nothing"
	@echo "make opus-headroom   - Opus tokens left against the NON-ADJUSTABLE"
	@echo "                       daily cap (QUESTIONS=n). Free, read-only"
	@echo "make preflight       - date-attribution check alone (cheap)"
	@echo "make rebuild-vectors - rebuild S3 Vectors from the corpus (no re-embed)"
	@echo "make lint            - ruff (same scope as the eval gate)"
	@echo "make test            - pytest"
	@echo "make ingest-backfill - one-shot backfill of the demo corpus"
	@echo "make demo            - up + smoke + print demo URL"

bootstrap:
	$(CDK) bootstrap

# THE DEPLOYED FUNCTION'S DEPENDENCIES. src/ ships first-party Python only
# (infra/asset_policy.py), so fastapi, mangum, langgraph and the pinned boto3
# reach Lambda through this layer or not at all. Until M04 they did not: the
# deployed query function answered every invoke with "No module named
# 'fastapi'", invisible because every end-to-end run drives the graph in-process
# with the function's environment rather than invoking the function.
#
# --platform/--implementation/--python-version because this is built from a
# Windows laptop for a linux runtime; without them pip resolves win_amd64 wheels
# and pydantic_core's compiled extension is the wrong architecture — a failure
# that only appears at invoke time, in the region, on the demo.
#
# --only-binary=:all: so a missing wheel FAILS here rather than silently
# building a source distribution against the local Python and shipping that.
LAYER_DIR := build/lambda-layer
layer:
	@rm -rf $(LAYER_DIR)
	python -m pip install --quiet \
	  --platform manylinux2014_x86_64 --implementation cp --python-version 3.14 \
	  --only-binary=:all: --target $(LAYER_DIR)/python -r requirements.txt
	@echo "✅ layer built → $(LAYER_DIR)/python ($$(du -sh $(LAYER_DIR) | cut -f1))"

# Depends on `layer`: the stack refuses to synth without it, which is better
# than deploying a function whose imports fail in the region.
core: layer
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
#
# SPEC/05 item 4 — THIS TARGET GATES ON THE INDEX, NOT ON `cdk deploy`.
# The deploy's exit code answers "did CloudFormation reach UPDATE_COMPLETE",
# and the question `make up` is asked is "can retrieval use the hot tier".
# M02 recorded a case where those differ (milestones/M02/README.md:591): a
# Trigger failure on an UPDATE rolls the Lambda's environment back but not the
# AOSS index contents, and the endpoint parameter from the previous successful
# deploy survives — so retrieval routes to a short index and answers with
# citations. `evals/check_hydration.py` reads the parameter the router reads
# and counts the index it names against the corpus.
#
# The gate runs EITHER WAY, which is why the deploy's status is captured
# instead of chained with &&. A failed deploy still gets a diagnosis rather
# than a stack trace, and — the case that matters — a deploy that exits 0 over
# an index nobody hydrated is refused.
#
# The deploy is SUBSHELLED. `$(CDK)` is `cd infra && npx cdk`, and everything
# here is one shell; without the parentheses the `cd` leaks and the gate runs
# from infra/, where `evals/check_hydration.py` does not exist.
up:
	@( $(CDK) deploy $(STACK_SEARCH) --require-approval never \
	     -c devPrincipalArn=$$(aws sts get-caller-identity --query Arn --output text) ); \
	  deployed=$$?; \
	  echo "--- cdk deploy exited $$deployed; the hydration gate below decides."; \
	  $(RESOLVE_ENV) \
	  python evals/check_hydration.py; \
	  gate=$$?; \
	  if [ $$gate -ne 0 ]; then \
	    echo "❌ Hot tier NOT usable (gate $$gate, deploy $$deployed)."; \
	    echo "   OCU is billing if the collection exists — 'make down' stops it."; \
	    exit $$gate; \
	  fi; \
	  echo "✅ Hot tier up and hydrated ($(SSM_ENDPOINT))"; \
	  echo "   next: make retrieval-evals   (records the aoss scorecard)"

# SPEC/05's other half of the gate: prove it FAILS SAFE, with a real failed
# deploy rather than a unit test asserting that a raise raises.
#
# WHAT AN UPDATE-TIME FAULT ACTUALLY DOES, MEASURED 2026-08-20. Two earlier
# versions of this comment asserted outcomes this target cannot produce, and
# both were written from reading rather than running. Recorded in full because
# the mistake is more instructive than the fix:
#
#   Draft 1 claimed the COUNT-PARITY refusal. Unreachable: reindex retires the
#   parameter before touching the index and raises before republishing, so the
#   gate refuses at `endpoint` and never evaluates count_parity.
#   (eng-code-reviewer caught this before it ran.)
#
#   Draft 2 then claimed the ENDPOINT refusal. Also wrong, and only the live
#   run showed why. On an UPDATE of a healthy stack the deploy does fail — but
#   CloudFormation then rolls the Trigger back, and CDK's Trigger re-invokes
#   the PREVIOUS Lambda version, which has no REINDEX_FAULT_DROP. That version
#   re-hydrates completely and republishes the endpoint. Observed: version :2
#   failed, version :1 was invoked, and the gate found 1157/1157 with a live
#   endpoint. The gate was right; the assertion was wrong.
#
# So a failed update does not merely fail safe, it SELF-REPAIRS to the last
# known-good index. That is a stronger property than the one this target was
# written to demonstrate, and it is the reason the assertion below is stated as
# a FORBIDDEN STATE rather than an expected outcome.
#
# THE PROPERTY, which holds under both outcomes: after a deploy whose hydration
# was deliberately broken, `/regdelta/search/endpoint` must never name an index
# that is short. Either the parameter is absent (retrieval falls to S3 Vectors)
# or it names a fully-hydrated index (rollback repaired it). What must never
# happen is an endpoint over a partial index answering with citations — the M02
# residue this milestone closed.
#
# The endpoint-absent refusal is exercised live and free with the tier simply
# down, and count_parity is exercised offline in tests/test_hydration_gate.py.
# This target covers the case neither of those can: a real collection, a real
# hydration, and a real CloudFormation failure.
#
# THREE OUTCOMES, NOT TWO, and conflating them is how draft 3 of this target
# was wrong. `check_hydration` can refuse on five different checks, and only
# `endpoint` means the tier is out of service. A 403, a missing index, an
# unreadable mapping or an unresolved corpus bucket all leave the parameter
# LIVE while the index goes unverified — reporting that as "retrieval is on S3
# Vectors" is a false pass, and it is what grepping the report for one check
# name produced. The case below branches on the whole refusal SET:
#   ok, no refusals   -> rollback repaired it; the endpoint names a full index
#   exactly {endpoint} -> the parameter is gone; retrieval fell back
#   count_parity       -> FORBIDDEN; the endpoint names a mismatched index
#   anything else      -> INDETERMINATE, and treated as a failure
#
# THE COLLECTION SURVIVES THIS and keeps billing at ~$0.24/hr, whichever way it
# goes. `make down` or the janitor is what stops that.
DROP ?= 3
fault-drop:
	@( $(CDK) deploy $(STACK_SEARCH) --require-approval never \
	     -c faultDrop=$(DROP) \
	     -c devPrincipalArn=$$(aws sts get-caller-identity --query Arn --output text) ); \
	  deployed=$$?; \
	  echo "--- cdk deploy exited $$deployed (a FAILING deploy is the point here)"; \
	  if [ $$deployed -eq 0 ]; then \
	    echo "❌ the deploy SUCCEEDED with $(DROP) records dropped."; \
	    echo "   reindex.py's count assertion did not fire, so the fault"; \
	    echo "   hook or the assertion is broken — not the gate."; \
	    exit 1; \
	  fi; \
	  $(RESOLVE_ENV_STRICT) \
	  refused=$$(python evals/check_hydration.py --refusals); \
	  gate=$$?; \
	  python evals/check_hydration.py --json; \
	  echo "--- gate exit $$gate; refusals: [$$refused]"; \
	  case "$$gate|$$refused" in \
	    "0|") \
	      echo "✅ rollback RE-HYDRATED and the gate verified count parity."; \
	      echo "   CDK re-invoked the previous Lambda version, which has no"; \
	      echo "   fault hook. The endpoint names a complete index." ;; \
	    "1|endpoint") \
	      echo "✅ the gate REFUSED: the failed hydration left no endpoint."; \
	      echo "   Retrieval is on S3 Vectors." ;; \
	    *count_parity*) \
	      echo "❌ FORBIDDEN STATE: the endpoint names a MISMATCHED index."; \
	      echo "   This is the M02 residue — an index that answers with"; \
	      echo "   citations while missing chunks. SPEC/05 item 4 regressed."; \
	      exit 1 ;; \
	    *) \
	      echo "❌ INDETERMINATE: the gate could not verify the index the"; \
	      echo "   endpoint names (refusals: [$$refused])."; \
	      echo "   That is NOT evidence the tier is out of service — the"; \
	      echo "   parameter may still be live and pointing at an index"; \
	      echo "   nobody checked. Treat as a failure and run make down."; \
	      exit 1 ;; \
	  esac; \
	  echo "   NEXT: make down. The collection still exists and still bills;"; \
	  echo "   and after a rollback the Trigger's HandlerArn is unchanged, so"; \
	  echo "   a plain make up will NOT re-fire hydration."
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

# RESOLVE_ENV, and it is not cosmetic. `corpus_fingerprint()` needs
# REGISTRY_TABLE to record WHICH corpus answered, and without it a card carries
# `corpus: {"available": false}` — so two cards cannot be compared and
# `corpus_drift()` silently stops warning. Measured the hard way during the M05
# window: the first AOSS card of the run was recorded without it, and when a
# question regressed there was no fingerprint to rule the corpus in or out. The
# S3 Vectors card, recorded with the environment resolved, settled it in one
# line. The daily poller changes the corpus unattended (52 documents on
# 2026-08-19, from 4 on 2026-07-30), so this is the common case, not the edge.
# OPUS HEADROOM IS CHECKED BEFORE EITHER OF THESE SPENDS A TOKEN.
#
# The seat's instruction at the M06 window: Opus must not reach throttle.
# `L-ED2BADF9` is 2,592,000 tokens a day and reports `Adjustable: false`, so
# crossing it is not a bill — it is these two targets not working until 00:00
# UTC. At the measured 5,881.8 Opus tokens per uncached query the cap is 440
# queries a day for everything this account does, and a smoke run nobody
# thought twice about is what takes the last of it.
#
# CHAINED WITH `&&`, so a refusal (exit 1) or an unreadable meter (exit 2) stops
# the run. The meter is CloudWatch, summed from midnight UTC, and a read that
# fails refuses rather than reporting an empty day.
#
# The question counts are the subsets these targets actually ask. They are
# stated here rather than derived, so that a change to either subset shows up
# as a diff against this number instead of silently loosening the guard;
# `tests/test_eval_headroom_counts.py` pins them to the golden set.
smoke:
	@$(RESOLVE_ENV_STRICT) \
	  python evals/check_opus_headroom.py --questions 5 && \
	  python evals/run_evals.py --subset smoke

evals:
	@$(RESOLVE_ENV_STRICT) \
	  python evals/check_opus_headroom.py --questions 20 && \
	  python evals/run_evals.py $(ARGS)

# The guard alone, for deciding whether a window is affordable before opening
# one. Read-only and free.
opus-headroom:
	@$(RESOLVE_ENV_STRICT) python evals/check_opus_headroom.py \
	  --questions $(QUESTIONS) --json
QUESTIONS ?= 20

# Measures the INSTRUMENT, not the system: replays run_evals.check() against
# hand-written right and wrong answers and requires it to tell them apart. No
# API, no corpus, no cost. Run it whenever a question is added or its scoring
# tokens change — the defects it finds are invisible to reading (ADR-0005; the
# 2026-08-12 q07 ruling, defect 4).
discrimination:
	python evals/check_discrimination.py $(ARGS)

# The other half of the same job.  asks whether a question can
# tell a HAND-WRITTEN right answer from a wrong one; this asks whether it would
# have scored the answers the system ACTUALLY gave, replayed from the recorded
# scorecards. Hand-written specimens share an author with the scoring tokens and
# so share their blind spots — three questions were written on 2026-08-15 in a
# phrasing the model does not use, and all three passed the specimens. No API,
# no corpus, no cost.
replay-history:
	python evals/replay_history.py $(ARGS)

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

# SPEC/04's answer-level comparability criterion, and the Tier B latency number
# ADR-0001 asked for at M02. Writes milestones/M04/answer-parity-<sha>.json.
#
# Cross-run for the same reason retrieval-parity is: one invocation cannot see
# the other tier, and the tier only changes when `make up` / `make down` moves
# the SSM parameter. Run it with the hot tier DOWN, then UP, on the same
# commit; each run merges its half into the one artifact and re-judges. Exit 2
# means "only one tier recorded", which is not a pass.
#
# The tier is DERIVED from the live SSM parameter and then ASSERTED, copied
# from retrieval-evals above including MSYS_NO_PATHCONV — Git Bash rewrites
# `--name /regdelta/...` into a Windows path and the lookup returns
# ParameterNotFound, which reads as "hot tier down" while it is up. An
# unexpected error fails rather than defaulting, because defaulting to
# s3vectors is what made that mangled path invisible.
#
# RESOLVE_ENV because this drives the real graph in-process: same buckets,
# tables and search parameter the deployed function has.
#
# RERANK and LEXICAL_LANE are PASSED EXPLICITLY, exactly as retrieval-evals
# passes them. The criterion says a citation that changes "when only the
# infrastructure changed" is a bug, which is only a statement about the tiers
# if the retrieval configuration is held equal across the two halves — and
# those halves are minutes-to-hours apart across a `make up`, with an exported
# RERANK able to reach one and not the other. The harness also gates on it: the
# recorded configs must match or the comparison fails.
demo-parity:
	@out=$$(MSYS_NO_PATHCONV=1 aws ssm get-parameter --name $(SSM_ENDPOINT) \
	    --region $(REGION) --query Parameter.Value --output text 2>&1); \
	  if echo "$$out" | grep -q '^https://'; then tier=aoss; \
	  elif echo "$$out" | grep -q 'ParameterNotFound'; then tier=s3vectors; \
	  else echo "cannot determine the search tier: $$out" >&2; exit 1; fi; \
	  echo "→ hot tier $$tier (RERANK=$(RERANK) LEXICAL_LANE=$(LEXICAL_LANE))"; \
	  $(RESOLVE_ENV) \
	  RERANK=$(RERANK) RETRIEVAL_LEXICAL_LANE=$(LEXICAL_LANE) \
	  python evals/run_demo_parity.py --tier $$tier $(ARGS)

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
	@$(RESOLVE_ENV) \
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
	@$(RESOLVE_ENV) \
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


# ------------------------------------------------------------------ SPEC/06
# TIER B'S DISPOSITION. Owed by ADR-0001, homed here by ADR-0012, and amended
# by milestones/M06/spec06-disposition-amendment.md — which is a DRAFT awaiting
# the seat's ruling, and this target implements it rather than deciding it.
#
# CROSS-RUN, exactly as demo-parity is and for the same reason: the tier is
# whatever /regdelta/search/endpoint names, and it only changes across a
# `make up` / `make down`. Run it with the hot tier DOWN, then UP, on the same
# commit; each run merges its half into the one report and re-judges.
#
#   make tier-disposition-price     # free; what the whole thing costs
#   make tier-disposition           # hot tier DOWN -> the s3vectors half
#   make up
#   make tier-disposition           # hot tier UP   -> the aoss half
#   make down
#
# THE TIER IS DERIVED AND THEN ASSERTED, never chosen by the caller — copied
# from retrieval-evals and demo-parity including MSYS_NO_PATHCONV, because Git
# Bash rewrites `--name /regdelta/...` into a Windows path and the lookup
# returns ParameterNotFound, which reads as "hot tier down" while it is up.
# That silently recorded one tier's numbers under the other's label once
# already. An unexpected error FAILS rather than defaulting to s3vectors, which
# is what made the mangled path invisible.
#
# The tier the parameter names is only half of it. The driver ALSO asserts, per
# call, that the tier which actually answered is the one the step was pointed
# at: the router falls back to S3 Vectors silently and by design, so a
# data-access-policy propagation delay after `make up` would otherwise record
# Tier A's latencies as Tier B's — and the clause's default outcome is
# retirement. See src/ops/retrieval_load.py.
#
# RESOLVE_ENV_STRICT because this run PRODUCES EVIDENCE and gates on it. Without
# REGISTRY_TABLE the corpus fingerprint records {"available": false}, the two
# halves cannot be shown to have answered from the same corpus, and the gate
# that says so silently stops gating.
#
# THE SIX EXIT CODES DO NOT SURVIVE MAKE, and this comment used to claim they
# did. GNU make exits 2 for ANY nonzero recipe status, so through this target
# exit 1 (a gate refused), 4 (a failed measurement — re-run once) and 5 (a
# second failure, disposed by the default outcome) are indistinguishable, and
# they are three completely different next actions. Verified, not assumed.
# eng-code-reviewer, M06.
#
# So the target ECHOES the code before make swallows it, and the artifact
# carries `disposition.verdict`, which is the field to read. The harness's own
# module docstring is the reference for what each means:
#   0 disposed (keep or retire)   1 gate refused        2 only one half
#   3 the harness crashed         4 failed measurement  5 second failure
tier-disposition:
	@out=$$(MSYS_NO_PATHCONV=1 aws ssm get-parameter --name $(SSM_ENDPOINT) \
	    --region $(REGION) --query Parameter.Value --output text 2>&1); \
	  if echo "$$out" | grep -q '^https://'; then tier=aoss; \
	  elif echo "$$out" | grep -q 'ParameterNotFound'; then tier=s3vectors; \
	  else echo "cannot determine the search tier: $$out" >&2; exit 1; fi; \
	  echo "→ hot tier $$tier (RERANK=$(RERANK) LEXICAL_LANE=$(LEXICAL_LANE))"; \
	  $(RESOLVE_ENV_STRICT) \
	  RERANK=$(RERANK) RETRIEVAL_LEXICAL_LANE=$(LEXICAL_LANE) \
	  python loadtest/retrieval_load.py --tier $$tier $(ARGS); \
	  code=$$?; \
	  echo "--- tier-disposition exit $$code (make will report 2 for any "; \
	  echo "    nonzero; read disposition.verdict in the report for the"; \
	  echo "    difference between a gate refusal and a failed measurement)"; \
	  exit $$code

# Free, offline, and the thing to run BEFORE asking anyone to approve a window.
# It prices all three components — Bedrock, Lambda and OCU — against the seat's
# ceiling, and refuses here rather than after the money is gone.
tier-disposition-price:
	python loadtest/retrieval_load.py --dry-run

synth:
	$(CDK) synth
diff:
	$(CDK) diff
