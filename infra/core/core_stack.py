"""regdelta-core — the persistent stack. Idle target: < $2/month.

Everything bills per-request: S3 (+S3 Vectors), DynamoDB on-demand, Lambda.
Nothing here may reference regdelta-search.
"""
from pathlib import Path

import asset_policy
import aws_cdk as cdk
from aws_cdk import (
    CfnResource,
    Duration,
    RemovalPolicy,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sqs as sqs,
)
from constructs import Construct

# Resolved from this file, not the process CWD — same reason as
# asset_policy.SRC, and the reason `../src` was wrong here.
JANITOR_SRC = str(Path(__file__).resolve().parent.parent / "lambdas" / "janitor")

SSM_ENDPOINT_PARAM = "/regdelta/search/endpoint"
VECTOR_INDEX_NAME = "chunks"
EMBED_DIM = 1024


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
            resources=["*"]))  # TODO SPEC/05: scope to bucket/index ARNs

        # ------------------------------------------------------------------
        # Query plane: LangGraph Lambda. Routes AOSS/S3Vectors via SSM param;
        # absent param => S3 Vectors tier (never a 5xx). SPEC/03-04.
        # ------------------------------------------------------------------
        query_fn = _lambda.Function(
            self, "QueryFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="api.api.handler",
            code=asset_policy.python_source(),
            timeout=Duration.minutes(2),
            memory_size=2048,
            environment={
                **common_env,
                "STATE_TABLE": self.state_table.table_name,
                "SEARCH_ENDPOINT_PARAM": SSM_ENDPOINT_PARAM,
            },
        )
        self.corpus_bucket.grant_read(query_fn)
        self.registry_table.grant_read_data(query_fn)
        self.state_table.grant_read_write_data(query_fn)
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=["*"]))  # TODO: scope
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["s3vectors:QueryVectors", "s3vectors:GetVectors"],
            resources=["*"]))  # TODO: scope
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter",
                                       resource_name="regdelta/search/*")]))
        query_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=["*"]))  # TODO: scope to collection
        self.query_lambda_role_arn = query_fn.role.role_arn

        # TODO SPEC/04: HTTP API Gateway (ApiUrl output), UI bucket +
        #   CloudFront (DemoUrl output), SES identity for HITL notifications.
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
