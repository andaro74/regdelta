"""regdelta-search — the EPHEMERAL stack. Everything here is cattle.

AOSS VECTORSEARCH collection in dev mode (standby_replicas=DISABLED →
0.5 + 0.5 OCU ≈ $0.24/hr), three mandatory policies, a reindex Lambda that
hydrates from the corpus bucket on every deploy, and the SSM endpoint param
that flips the retrieval router to the hot tier.

`cdk destroy regdelta-search` must always succeed and loses nothing: the
index is a pure function of the corpus bucket. StandbyReplicas cannot be
changed after index creation — fine, the stack is disposable. Production =
ENABLED + VPC network policy + never destroyed.
"""
import json

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_opensearchserverless as aoss,
    aws_s3 as s3,
    aws_ssm as ssm,
    triggers,
)
from constructs import Construct

COLLECTION_NAME = "regdelta"
SSM_ENDPOINT_PARAM = "/regdelta/search/endpoint"


class RegDeltaSearchStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 corpus_bucket: s3.IBucket, query_lambda_role_arn: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        enc = aoss.CfnSecurityPolicy(
            self, "EncryptionPolicy",
            name=f"{COLLECTION_NAME}-enc", type="encryption",
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection",
                           "Resource": [f"collection/{COLLECTION_NAME}"]}],
                "AWSOwnedKey": True,  # enterprise swap: customer-managed KMS
            }))

        net = aoss.CfnSecurityPolicy(
            self, "NetworkPolicy",
            name=f"{COLLECTION_NAME}-net", type="network",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection",
                     "Resource": [f"collection/{COLLECTION_NAME}"]},
                    {"ResourceType": "dashboard",
                     "Resource": [f"collection/{COLLECTION_NAME}"]},
                ],
                "AllowFromPublic": True,  # enterprise swap: VPC endpoint
            }]))

        collection = aoss.CfnCollection(
            self, "Collection",
            name=COLLECTION_NAME, type="VECTORSEARCH",
            standby_replicas="DISABLED",
            description="RegDelta hot tier (BM25+kNN). Ephemeral; rebuilt "
                        "from the corpus bucket on every deploy.")
        collection.add_dependency(enc)
        collection.add_dependency(net)

        reindex = _lambda.Function(
            self, "ReindexFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambdas/reindex"),
            timeout=Duration.minutes(15), memory_size=1024,
            environment={
                "CORPUS_BUCKET": corpus_bucket.bucket_name,
                "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
                "INDEX_NAME": "chunks",
            })
        corpus_bucket.grant_read(reindex)
        reindex.add_to_role_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))

        access = aoss.CfnAccessPolicy(
            self, "DataAccessPolicy",
            name=f"{COLLECTION_NAME}-access", type="data",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection",
                     "Resource": [f"collection/{COLLECTION_NAME}"],
                     "Permission": ["aoss:*"]},
                    {"ResourceType": "index",
                     "Resource": [f"index/{COLLECTION_NAME}/*"],
                     "Permission": ["aoss:*"]},  # TODO SPEC/05: split write/read
                ],
                "Principal": [reindex.role.role_arn, query_lambda_role_arn],
            }]))
        access.add_dependency(collection)

        triggers.Trigger(
            self, "HydrateOnDeploy",
            handler=reindex,
            execute_after=[access],
            execute_on_handler_change=True)

        ssm.StringParameter(
            self, "EndpointParam",
            parameter_name=SSM_ENDPOINT_PARAM,
            string_value=collection.attr_collection_endpoint)

        cdk.CfnOutput(self, "CollectionEndpoint",
                      value=collection.attr_collection_endpoint)
        cdk.CfnOutput(self, "SessionCostNote",
                      value="Dev mode ≈ $0.24/hr while this stack exists; "
                            "`make down` stops billing.")
