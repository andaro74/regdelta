"""regdelta-core — the persistent stack. Idle target: < $2/month.

Everything bills per-request: S3 (+S3 Vectors), DynamoDB on-demand, Lambda.
Nothing here may reference regdelta-search.
"""
import sys
from pathlib import Path

import asset_policy
import aws_cdk as cdk

# src/ on the path so the IAM policy can grant exactly the model ids the code
# reads. Copied into this file they drift from the ones the Lambda calls, and
# the drift surfaces as an AccessDenied in the region rather than a failed build
# — the worst place to learn about it.
#
# APPEND, not insert(0). Position 0 would let any top-level name under src/
# win over the installed distributions for every module infra/app.py loads.
# Nothing collides today, which makes it latent rather than live — and latent is
# the kind that surfaces during a deploy. Note this runs application code inside
# the deploy toolchain: shared/config.py is `import os` and nothing else, and
# that property is now load-bearing.
sys.path.append(asset_policy.SRC)
from aws_cdk import (
    CfnResource,
    Duration,
    RemovalPolicy,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as apigw_int,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_sqs as sqs,
)
from constructs import Construct

from shared import config

# Resolved from this file, not the process CWD — same reason as
# asset_policy.SRC, and the reason `../src` was wrong here.
JANITOR_SRC = str(Path(__file__).resolve().parent.parent / "lambdas" / "janitor")
UI_SRC = str(Path(__file__).resolve().parents[2] / "ui")
# THE CANNED SCENARIOS THE DEMO PAGE PUTS A BUTTON ON. SPEC/04 says "one canned
# scenario button per entry in evals/scenarios.json", so the page fetches this
# file rather than carrying a transcribed copy — a list hand-copied into the
# HTML is a criterion whose subject can move without a diff, which is the
# trap-census defect class `evals/scenarios.json` itself was created to close.
SCENARIOS_SRC = Path(__file__).resolve().parents[2] / "evals" / "scenarios.json"
# The fields the page needs, and only those. The source file also carries the
# PM- and SME-seat commentary that justifies each scenario (`_meta`,
# `demonstrates`, `grounded_in`, `note`); CloudFront serves this bucket to
# anonymous callers, and internal review prose is not part of the demo.
SCENARIO_PUBLIC_FIELDS = ("id", "label", "question", "company_profile")

# The demo page's Content-Security-Policy. Written as one string here, beside
# the files it names, so that adding a script or a stylesheet to `ui/` and
# forgetting the policy is a broken page in review rather than a silent
# widening — `default-src 'none'` fails closed.
#
# NO 'unsafe-inline' ANYWHERE, which is the whole point: with it, `script-src`
# permits exactly the injected <script> the policy exists to stop, and the
# header becomes decoration. `ui/` carries no inline script, no inline style
# and no `style=` attribute for that reason, and `tests/test_ui_verdict.py`
# pins all three so the policy cannot quietly stop matching the page.
CSP = "; ".join([
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    # The page's own fetches to /api/query, /api/health and scenarios.json.
    "connect-src 'self'",
    # No <img> anywhere; 'self' covers only the favicon a browser asks for
    # unprompted.
    "img-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
])
# Built by `make layer`, not committed: ~101MB of wheels reproducible from a
# pinned requirements.txt. See the LayerVersion below for why it has to exist.
LAYER_SRC = Path(__file__).resolve().parents[2] / "build" / "lambda-layer"

def _public_scenarios() -> str:
    """`evals/scenarios.json`, projected to the fields the demo page renders.

    Read at synth from the canonical file, so a scenario added, removed or
    reworded reaches the page on the next deploy with no second edit. The
    projection is a whitelist rather than a blacklist: a field added to the
    source for the SME or PM seat does not become public by default.

    THE WHITELIST IS TOP-LEVEL ONLY. `company_profile` is copied whole, so a
    reviewer note nested inside a profile would publish. Harmless today — the
    three profiles hold `company`, `products`, `claims`, `colour_additives` and
    nothing else — and recorded rather than deepened, because a recursive
    projection would need a schema for a field whose shape is the PM seat's to
    choose. `security-reviewer`, M04, LOW.

    Raises rather than shipping an empty list. A page with no buttons still
    renders, and "one button per entry" is then satisfied by a file with no
    entries — the vacuous-green shape this milestone has already found four
    times.
    """
    import json

    data = json.loads(SCENARIOS_SRC.read_text(encoding="utf-8"))
    scenarios = [{k: s[k] for k in SCENARIO_PUBLIC_FIELDS if k in s}
                 for s in data.get("scenarios") or []]
    if not scenarios:
        raise ValueError(f"{SCENARIOS_SRC} defines no scenarios; the demo page "
                         "would deploy with no buttons and no error")
    return json.dumps({"scenarios": scenarios}, indent=1, sort_keys=False)


SSM_ENDPOINT_PARAM = "/regdelta/search/endpoint"
# The HTTP API stage name, which is also the first path segment the API answers
# on (/api/query) and the prefix CloudFront forwards. Named once: the Lambda has
# to strip it from rawPath before FastAPI routes, and it receives it as
# API_BASE_PATH below rather than hardcoding a second copy.
API_STAGE_NAME = "api"
VECTOR_INDEX_NAME = "chunks"
EMBED_DIM = 1024

# Regions a `us.` cross-region inference profile routes to, read off the live
# profile rather than assumed:
#     aws bedrock get-inference-profile \
#       --inference-profile-identifier us.anthropic.claude-sonnet-4-6
#     -> foundation-model ARNs in us-east-1, us-east-2, us-west-2
#
# This matters because an inference profile is NOT itself the thing Bedrock
# authorises. It evaluates InvokeModel against the FOUNDATION MODEL in whichever
# region it routes the call to, so a policy naming only the profile fails
# intermittently — in exactly the regions it happens to pick, and not in the
# ones a smoke test hits.
INFERENCE_PROFILE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")

# Prefixes AWS uses for cross-region inference profiles. `us.anthropic.foo` is a
# profile whose underlying foundation model is `anthropic.foo`.
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


class RegDeltaCoreStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # Source of truth: corpus bucket (raw XML, parsed JSON, chunk JSONL —
        # each chunk record INCLUDES its Titan v2 embedding). Versioned = audit
        # trail. Both search tiers are pure functions of this bucket.
        # ------------------------------------------------------------------
        self.corpus_bucket = s3.Bucket(
            self, "CorpusBucket",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ------------------------------------------------------------------
        # Always-on retrieval tier: S3 Vectors (vector bucket + index).
        # Raw CfnResource so this synths on any aws-cdk-lib version; swap to
        # the aws_s3vectors L1/L2 constructs once your pinned lib has them.
        # ------------------------------------------------------------------
        vector_bucket = CfnResource(
            self, "VectorBucket",
            type="AWS::S3Vectors::VectorBucket",
            properties={"VectorBucketName": f"regdelta-vectors-{self.account}"},
        )
        vector_index = CfnResource(
            self, "VectorIndex",
            type="AWS::S3Vectors::Index",
            properties={
                "VectorBucketName": f"regdelta-vectors-{self.account}",
                "IndexName": VECTOR_INDEX_NAME,
                "DataType": "float32",
                "Dimension": EMBED_DIM,
                "DistanceMetric": "cosine",
                # Keep bulky/non-filter fields out of the filterable set:
                "MetadataConfiguration": {
                    "NonFilterableMetadataKeys": ["chunk_text", "citation_path"]
                },
            },
        )
        vector_index.add_dependency(vector_bucket)

        # ------------------------------------------------------------------
        # DynamoDB: registry + amendment graph, and graph state + cache.
        # Registry keys (SPEC/01):
        #   DOC#<fr_doc_number>   | META
        #   CFR#<title>#<section> | VERSION#<date>
        #   DOC#<doc>             | SUPERSEDES#<target>   (attrs incl. scope)
        # GSI "citations": citation -> chunk ids (exact-match assist, SPEC/02).
        # ------------------------------------------------------------------
        self.registry_table = ddb.Table(
            self, "RegistryTable",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.registry_table.add_global_secondary_index(
            index_name="citations",
            partition_key=ddb.Attribute(name="citation", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="chunk_id", type=ddb.AttributeType.STRING),
        )

        self.state_table = ddb.Table(
            self, "StateTable",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # Ingestion: EventBridge daily -> poller -> SQS(+DLQ) -> processor.
        # Never targets AOSS; writes corpus + S3 Vectors + registry (SPEC/01).
        # ------------------------------------------------------------------
        dlq = sqs.Queue(self, "IngestDLQ", retention_period=Duration.days(14))
        queue = sqs.Queue(
            self, "IngestQueue",
            visibility_timeout=Duration.minutes(15),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        common_env = {
            "CORPUS_BUCKET": self.corpus_bucket.bucket_name,
            "REGISTRY_TABLE": self.registry_table.table_name,
            "VECTOR_BUCKET": f"regdelta-vectors-{self.account}",
            "VECTOR_INDEX": VECTOR_INDEX_NAME,
        }

        # EVERY Lambda here ships through asset_policy.python_source(): an
        # allowlist of **/*.py under the DOCKER ignore mode. Until M04 these
        # three called `Code.from_asset("../src")` with no filter, staging 75
        # files of which 39 were not Python — .pytest_cache/, every
        # __pycache__/*.pyc — into the persistent stack's functions. A code zip
        # is readable by anyone with lambda:GetFunction, so that is disclosure,
        # not untidiness. The path was also CWD-relative and only resolved when
        # cdk ran from infra/. security-reviewer, M04.
        poller = _lambda.Function(
            self, "PollerFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="ingestion.poller.handler",
            code=asset_policy.python_source(),
            timeout=Duration.minutes(5),
            environment={**common_env, "QUEUE_URL": queue.queue_url},
        )
        queue.grant_send_messages(poller)
        self.registry_table.grant_read_data(poller)
        events.Rule(
            self, "DailyIngest",
            schedule=events.Schedule.cron(minute="0", hour="12"),
            targets=[targets.LambdaFunction(poller)],
        )

        processor = _lambda.Function(
            self, "ProcessorFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="ingestion.processor.handler",
            code=asset_policy.python_source(),
            timeout=Duration.minutes(15),
            memory_size=1024,
            environment=common_env,
        )
        processor.add_event_source_mapping(
            "IngestSource", event_source_arn=queue.queue_arn, batch_size=1)
        queue.grant_consume_messages(processor)
        self.corpus_bucket.grant_read_write(processor)
        self.registry_table.grant_read_write_data(processor)
        processor.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=["*"]))  # TODO SPEC/05: scope
        processor.add_to_role_policy(iam.PolicyStatement(
            actions=["s3vectors:PutVectors", "s3vectors:GetVectors",
                     "s3vectors:ListVectors", "s3vectors:QueryVectors"],
            # Scoped alongside the query role's: leaving `*` next to a helper
            # verified against the live bucket is harder to justify than the
            # SPEC/05 deferral was. `bedrock:InvokeModel` above stays wildcard
            # for now — but note "not internet-facing" is the wrong summary of
            # why that is safe. The processor is not reachable by attacker
            # -controlled INVOCATION; it is reachable by attacker-controlled
            # CONTENT, since it runs Federal Register text through Converse.
            resources=[self._vector_bucket_arn(),
                       f"{self._vector_bucket_arn()}/index/{VECTOR_INDEX_NAME}"]))

        # ------------------------------------------------------------------
        # Query plane: LangGraph Lambda. Routes AOSS/S3Vectors via SSM param;
        # absent param => S3 Vectors tier (never a 5xx). SPEC/03-04.
        # ------------------------------------------------------------------
        # THE DEPENDENCIES. src/ is first-party Python only — the asset policy
        # ships `**/*.py` and nothing else — so fastapi, mangum, langgraph and
        # our pinned boto3 have to arrive some other way. Until M04 they did
        # not arrive at all: the deployed function answered every invoke with
        # `Unable to import module 'api.api': No module named 'fastapi'`, which
        # nothing noticed because every "end to end" run in this repo drives the
        # graph IN-PROCESS with the deployed function's environment variables
        # rather than invoking the function.
        #
        # A LAYER, NOT VENDORED INTO src/. `pip install -t src/` would put
        # pydantic_core's compiled .so and every .dist-info under the `**/*.py`
        # allowlist, which drops them — a subtler broken deploy that every asset
        # test still passes, since the modules they name are all present.
        # security-reviewer named that trap explicitly.
        #
        # BOTO3 IS SHIPPED rather than taken from the runtime, which costs
        # ~27MB of botocore. The Lambda Python runtime bundles its own boto3 at
        # a version AWS chooses, and this stack calls `boto3.client("s3vectors")`
        # — a service new enough that an older bundled botocore does not know it
        # exists. That failure would arrive as a retrieval error in the demo,
        # not as a dependency error. The pin in requirements.txt is what the
        # evals run against, and the deployed function should run the same one.
        if not LAYER_SRC.is_dir():
            # Explicit rather than an empty layer: a missing directory would
            # otherwise synth a layer with nothing in it and deploy a function
            # that fails exactly the way this whole block exists to prevent.
            raise FileNotFoundError(
                f"{LAYER_SRC} does not exist — run `make layer` first. It holds "
                "the Lambda dependency layer built from requirements.txt and is "
                "deliberately not committed.")
        deps_layer = _lambda.LayerVersion(
            self, "DepsLayer",
            # A DENYLIST here, deliberately, where src/ gets an allowlist. A
            # wheel is not just .py — pydantic_core ships a compiled .so and
            # every package ships .dist-info metadata importlib.metadata reads —
            # so `**/*.py` would break the layer. What is safe to drop is pip's
            # own bytecode caches, which are rebuilt on import.
            code=_lambda.Code.from_asset(str(LAYER_SRC),
                                         exclude=["**/__pycache__/**"]),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_14],
            description="fastapi, mangum, langgraph and the pinned boto3, from "
                        "requirements.txt via `make layer`",
        )

        query_fn = _lambda.Function(
            self, "QueryFn",
            # Only the query path needs these. The poller and processor import
            # boto3 and the standard library and nothing else, so a layer on
            # them would be 101MB of cold start for no import.
            layers=[deps_layer],
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="api.api.handler",
            code=asset_policy.python_source(),
            timeout=Duration.minutes(2),
            memory_size=2048,
            environment={
                **common_env,
                "STATE_TABLE": self.state_table.table_name,
                "SEARCH_ENDPOINT_PARAM": SSM_ENDPOINT_PARAM,
                # What Mangum strips from rawPath. Same constant as the stage.
                "API_BASE_PATH": f"/{API_STAGE_NAME}",
                # PINNED so the IAM grant below and the runtime call are
                # provably the same string. `config` resolves these from the
                # environment, and the policy resolves them in the SYNTH process
                # — the operator's shell — while the function resolved them
                # again from its own, which set none of them. They agreed only
                # when the deployer had nothing exported, and config.py invites
                # the divergence ("Raise MODEL_VERDICT to Opus 4.7 once account
                # model access is granted"): export it, deploy, and the policy
                # grants 4.7 to a function still invoking 4.6. Under the old
                # `Resource: "*"` that was impossible — the narrowing introduced
                # it. Security review of the M04 IAM scoping, finding 2.
                "MODEL_FAST": config.MODEL_FAST,
                "MODEL_VERDICT": config.MODEL_VERDICT,
                "EMBED_MODEL": config.EMBED_MODEL,
            },
        )
        self.corpus_bucket.grant_read(query_fn)
        self.registry_table.grant_read_data(query_fn)
        # THE REVIEW QUEUE IS NOT THIS ROLE'S TO READ. SPEC/05, deferred there
        # from SPEC/04 which had no endpoint touching it.
        #
        # `write_review_item` (src/graph/checkpoint.py) writes the asker's
        # QUESTION TEXT, verbatim and truncated to 2000 chars, under
        # `pk=REVIEW#<thread_id>`. That queue belongs to the SME seat
        # (docs/governance/ROLES.md). The query role is the one role in this
        # account driven by anonymous HTTP, so "it can read anything in the
        # table" means a bug in the query path can enumerate every question
        # anyone has ever escalated for human review.
        #
        # ONE READ STATEMENT AND ONE WRITE STATEMENT, not one pair per prefix,
        # and the shape is forced rather than chosen. `dynamodb:LeadingKeys`
        # under `ForAllValues:StringLike` requires EVERY key in the request to
        # match the statement's patterns, so a single `BatchWriteItem` carrying
        # both a `THREAD#` and a `REVIEW#` key satisfies neither of two
        # per-prefix statements and is denied. `delete_thread` issues exactly
        # that batch. Splitting by ACTION instead of by prefix is both the
        # literal spec sentence — "may read and write THREAD#*, and write
        # REVIEW#*, and may not read REVIEW#*" — and the only form that survives
        # a mixed batch.
        #
        # `Scan` is absent deliberately and is not an oversight: LeadingKeys
        # cannot constrain a Scan, so granting it would hand back everything
        # these two statements just took away. Nothing in `src/` scans.
        state_table_arn = self.state_table.table_arn
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:BatchGetItem",
                     "dynamodb:Query", "dynamodb:ConditionCheckItem"],
            resources=[state_table_arn],
            conditions={"ForAllValues:StringLike": {
                "dynamodb:LeadingKeys": ["THREAD#*"]}}))
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem",
                     "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"],
            resources=[state_table_arn],
            conditions={"ForAllValues:StringLike": {
                "dynamodb:LeadingKeys": ["THREAD#*", "REVIEW#*"]}}))
        # Metadata, not data. `DescribeTable` does not accept a LeadingKeys
        # condition — it has no keys — and it returns the schema and item COUNT,
        # never an item. Granted separately and named here so that its absence
        # from the two statements above reads as deliberate: `grant_read_write_data`
        # included it, and dropping it silently would be a latent boto3 failure
        # rather than a decision.
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:DescribeTable"], resources=[state_table_arn]))
        # ------------------------------------------------------------------
        # QUERY ROLE PERMISSIONS. This is the only role in the account driven by
        # ANONYMOUS requests — SPEC/04 declares /query unauthenticated and
        # CloudFront serves it to whoever asks — so its blast radius is the
        # blast radius of any bug in the query path.
        #
        # All three of these carried `Resource: "*"` and a `# TODO: scope` until
        # M04, deferred to SPEC/05. Security review pulled them forward on the
        # grounds that the risk changed character the day the role stopped being
        # reachable only by credential-holders.
        # ------------------------------------------------------------------
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=self._bedrock_model_arns()))
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["s3vectors:QueryVectors", "s3vectors:GetVectors"],
            # The bucket AND the index: QueryVectors names the index, and the
            # bucket ARN alone does not imply its children.
            resources=[
                self._vector_bucket_arn(),
                f"{self._vector_bucket_arn()}/index/{VECTOR_INDEX_NAME}",
            ]))
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter",
                                       resource_name="regdelta/search/*")]))
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"],
            # NOT pinned to a collection id, and that is a constraint rather
            # than an oversight: the collection is created by the EPHEMERAL
            # search stack, takes a fresh id on every `make up`, and this
            # persistent stack is deployed before it exists. Account-and-region
            # is the honest floor; `*` additionally reached every collection in
            # the account, and this account has others.
            #
            # The control that actually admits the request is AOSS's own data
            # access policy, which names this role explicitly — IAM here is
            # necessary and not sufficient, which is how AOSS is designed.
            resources=[self.format_arn(service="aoss", resource="collection",
                                       resource_name="*")]))
        self.query_lambda_role_arn = query_fn.role.role_arn

        # ------------------------------------------------------------------
        # SPEC/04's API surface and demo UI. ONE CloudFront distribution serves
        # both: static files from S3 at `/`, and the HTTP API at `/api/*`.
        #
        # THE SINGLE ORIGIN IS THE POINT, and it is a security decision rather
        # than a convenience. The alternative — UI on CloudFront calling the API
        # on its own execute-api domain — is cross-origin, so it needs CORS, and
        # the allowed origin is the CloudFront domain, which does not exist
        # until the distribution is created that depends on the API. The usual
        # escape is `allowOrigins: ["*"]` on an endpoint that spends Bedrock
        # tokens per request. Same-origin removes the question: the browser
        # never makes a cross-origin request, and no CORS policy exists to get
        # wrong. `/query` stays unauthenticated, which SPEC/04 declares out of
        # scope and which the throttle below bounds.
        # ------------------------------------------------------------------
        api = apigw.HttpApi(self, "Api", api_name="regdelta",
                            # No $default stage: the stage NAME becomes the
                            # first path segment, so a stage called `api` makes
                            # the API answer at /api/query — exactly what
                            # CloudFront forwards, with no path rewriting on
                            # either side. A default stage would need a
                            # CloudFront Function to strip `/api`, which is a
                            # second place for the path to be wrong.
                            create_default_stage=False)
        query_integration = apigw_int.HttpLambdaIntegration(
            "QueryIntegration", query_fn)
        for path, method in (("/query", apigw.HttpMethod.POST),
                             ("/resume/{thread_id}", apigw.HttpMethod.POST),
                             ("/health", apigw.HttpMethod.GET)):
            api.add_routes(path=path, methods=[method],
                           integration=query_integration)

        # Explicit routes, never a catch-all proxy. `ANY /{proxy+}` would hand
        # the Lambda every path an attacker cares to try and rely on FastAPI to
        # refuse them; three routes mean API Gateway refuses everything else
        # before a request reaches code that costs money.
        api_stage = apigw.HttpStage(
            self, "ApiStage", http_api=api, stage_name=API_STAGE_NAME, auto_deploy=True,
            # A BOUND ON AN UNAUTHENTICATED ENDPOINT THAT SPENDS MONEY. Each
            # /query is a Bedrock call; without a ceiling the only limit on a
            # stranger's bill is Lambda's account concurrency. These numbers are
            # a demo's shape — a handful of humans clicking — not a capacity
            # plan; M06 sets real ones against a load test.
            throttle=apigw.ThrottleSettings(rate_limit=20, burst_limit=40))

        # The UI's bucket is PRIVATE and reachable only through CloudFront's
        # origin access control. It holds derived files that are rebuilt from
        # git on every deploy, so DESTROY is right here where RETAIN is right
        # for the corpus.
        ui_bucket = s3.Bucket(
            self, "UiBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ------------------------------------------------------------------
        # A SECOND LAYER UNDER THE PAGE'S OWN DISCIPLINE.
        #
        # The demo page renders LLM output derived from untrusted Federal
        # Register and eCFR XML, to anonymous callers. Its XSS safety rests
        # entirely on every model-generated string going through `textContent`
        # and on `citationUrl` returning only literal federalregister.gov /
        # ecfr.gov prefixes concatenated with captured citation text. Two of its
        # three branches capture digits only; the CFR branch also captures a
        # paragraph designator, which is not — safe, because the scheme and host
        # are literal and the result is assigned to `a.href` as a property with
        # no attribute-quote context to escape, but the stronger wording was
        # this sentence's and it is the stated basis for "no sink found".
        # `security-reviewer`, M04.
        # `security-reviewer` found no sink and raised this as defence in
        # depth: discipline that is not enforced by anything is one careless
        # `innerHTML` away from being untrue, and nothing in this repo lints
        # JavaScript.
        #
        # It was declined at the time for a real reason — a meaningful CSP
        # needs the page's inline <script> in its own file, and `style-src`
        # needs the inline <style> and every literal `style=` attribute out
        # too, or the policy is written with 'unsafe-inline' and protects
        # nothing. That split is done (ui/app.js, ui/app.css), so the honest
        # policy is now available and this is it.
        #
        # `default-src 'none'` and then only what the page actually uses:
        # its own two scripts and one stylesheet, and `connect-src 'self'` for
        # the same-origin fetches to /api/*. The citation links are top-level
        # navigations to another origin, which no fetch directive governs.
        # `frame-ancestors` and `form-action` are 'none' because the page is
        # neither framed nor a form.
        # ------------------------------------------------------------------
        security_headers = cloudfront.ResponseHeadersPolicy(
            self, "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=CSP, override=True),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(
                    override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER,
                    override=True),
            ),
        )

        self.demo_distribution = cloudfront.Distribution(
            self, "Demo",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(ui_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=security_headers,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        f"{api.api_id}.execute-api.{self.region}.amazonaws.com"),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    # An answer is per-question and per-profile, and the
                    # response cache is DynamoDB's job with a stated TTL and a
                    # bypass a gate depends on (SPEC/04 control 1). A CloudFront
                    # cache in front of it would be a second, unstated cache
                    # with no bypass — and `make demo-parity`'s control would be
                    # measuring it.
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    # Everything except Host: the origin is API Gateway, which
                    # must see its own hostname to route. This is what carries
                    # `x-regdelta-no-cache` through to the Lambda.
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    # The same headers on the API responses. The CSP is inert
                    # over JSON; `nosniff` is not — it stops a browser deciding
                    # for itself that an API response is HTML, which is the one
                    # way a JSON endpoint becomes an XSS sink.
                    response_headers_policy=security_headers,
                ),
            },
        )

        # The UI ships with the stack, so a deploy cannot leave the bucket
        # holding a different commit's page than the API it talks to.
        s3deploy.BucketDeployment(
            self, "DemoUi",
            # ALLOWLISTED, with its mode, for the reason asset_policy states at
            # length: `exclude` without `ignore_mode` stages the opposite of
            # what it reads as, and this bucket is the one served to anonymous
            # callers with no IAM in the way.
            sources=[s3deploy.Source.asset(
                         UI_SRC,
                         exclude=asset_policy.UI_ASSET_EXCLUDE,
                         ignore_mode=asset_policy.ASSET_IGNORE_MODE),
                     s3deploy.Source.data("scenarios.json", _public_scenarios())],
            destination_bucket=ui_bucket,
            distribution=self.demo_distribution,
            distribution_paths=["/*"],
        )

        # Both consumed by tooling already in the repo: run_evals.resolve_api_url
        # reads ApiUrl, and the Makefile's `demo` target prints DemoUrl.
        cdk.CfnOutput(self, "ApiUrl", value=api_stage.url,
                      description="SPEC/04 API base; POST /query, POST "
                                  "/resume/{thread_id}, GET /health")
        cdk.CfnOutput(self, "DemoUrl",
                      value=f"https://{self.demo_distribution.distribution_domain_name}",
                      description="Demo UI; /api/* proxies to the same API")

        # TODO SPEC/04: SES identity for HITL notifications.
        # TODO SPEC/06: nightly eval Lambda + regression alarm + dashboard.

        # ------------------------------------------------------------------
        # Janitor: nightly, deletes regdelta-search if left up (forgotten
        # AOSS dev collection ≈ $175/month).
        # ------------------------------------------------------------------
        janitor = _lambda.Function(
            self, "JanitorFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="handler.handler",
            code=asset_policy.python_source(JANITOR_SRC),
            timeout=Duration.minutes(2),
            environment={"SEARCH_STACK_NAME": "regdelta-search"},
        )
        janitor.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudformation:DeleteStack", "cloudformation:DescribeStacks"],
            resources=[self.format_arn(service="cloudformation", resource="stack",
                                       resource_name="regdelta-search/*")]))
        # TODO SPEC/05: dedicated CFN execution role for regdelta-search +
        # iam:PassRole here, so deletion of the stack's resources succeeds.
        events.Rule(
            self, "NightlyJanitor",
            schedule=events.Schedule.cron(minute="0", hour="1"),
            targets=[targets.LambdaFunction(janitor)],
        )

        cdk.CfnOutput(self, "CorpusBucketName", value=self.corpus_bucket.bucket_name)
        cdk.CfnOutput(self, "PollerFnName", value=poller.function_name)
        cdk.CfnOutput(self, "VectorBucketName",
                      value=f"regdelta-vectors-{self.account}")

    # ---------------------------------------------------------------- ARNs
    def _vector_bucket_arn(self) -> str:
        """The S3 Vectors bucket, in the shape the service actually reports.

        Verified against the live bucket rather than inferred from the S3
        convention it does not follow:

            aws s3vectors get-vector-bucket --vector-bucket-name regdelta-...
            -> arn:aws:s3vectors:us-west-2:<acct>:bucket/regdelta-vectors-<acct>

        Note `bucket/NAME` — s3vectors ARNs carry region and account, unlike
        plain S3, so an ARN built by analogy with `arn:aws:s3:::name` would be
        wrong in a way that denies every request.
        """
        return self.format_arn(service="s3vectors", resource="bucket",
                               resource_name=f"regdelta-vectors-{self.account}")

    def _bedrock_model_arns(self) -> list[str]:
        """Exactly the models this system invokes — profiles AND their models.

        `config.MODEL_FAST` and `MODEL_VERDICT` are cross-region inference
        profiles (`us.anthropic...`). Two ARNs are needed per profile and the
        second is the one that is easy to miss: Bedrock authorises the call
        against the FOUNDATION MODEL in whichever region the profile routes to,
        so granting only the profile denies intermittently and by region.

        The embedding model is a plain foundation model — the query path embeds
        the question before it can search — and is regional to this stack.
        """
        arns: list[str] = []
        for model in (config.MODEL_FAST, config.MODEL_VERDICT):
            arns.append(self.format_arn(service="bedrock",
                                        resource="inference-profile",
                                        resource_name=model))
            base = model
            for prefix in _PROFILE_PREFIXES:
                if model.startswith(prefix):
                    if prefix != "us.":
                        # INFERENCE_PROFILE_REGIONS describes the `us.` profile
                        # only. A `global.` or `eu.` id would strip cleanly here
                        # and then be granted in the wrong regions — an
                        # intermittent, region-dependent AccessDenied, which is
                        # the exact failure this whole block exists to prevent.
                        # Refuse rather than guess.
                        raise ValueError(
                            f"{model!r} is a {prefix!r} inference profile, but "
                            "INFERENCE_PROFILE_REGIONS lists the regions for "
                            "`us.` profiles. Read the new profile's regions off "
                            "`aws bedrock get-inference-profile` and set them "
                            "here before deploying.")
                    base = model[len(prefix):]
                    break
            arns += [self.format_arn(service="bedrock", region=region,
                                     account="", resource="foundation-model",
                                     resource_name=base)
                     for region in INFERENCE_PROFILE_REGIONS]
        arns.append(self.format_arn(service="bedrock", account="",
                                    resource="foundation-model",
                                    resource_name=config.EMBED_MODEL))
        return arns
