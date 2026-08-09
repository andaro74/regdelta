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
import os
from pathlib import Path

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

# Resolved from this file, not from the process CWD. `Code.from_asset("../src")`
# only works when cdk is invoked from infra/, which is what the Makefile does
# and what nothing else does — `cdk synth` from the repo root, and any test
# that synthesises this stack, both look for ../src one level too high. jsii
# runs Node in its own process, so a chdir on the Python side does not move it.
SRC = str(Path(__file__).resolve().parents[2] / "src")


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

        # Ships ../src, like every core Lambda. It used to ship its own
        # lambdas/reindex/ directory holding a second copy of the index
        # mapping — the same shape as the _EDGE_PREDICATE duplication that
        # drifted in M01c. The mapping and the query tier must agree on field
        # names or cross-tier Jaccard measures the disagreement instead of the
        # retrieval; one importable module makes that unrepresentable.
        # SPEC/02's Files list is amended in the same PR.
        reindex = _lambda.Function(
            self, "ReindexFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="retrieval.reindex.handler",
            code=_lambda.Code.from_asset(SRC),
            timeout=Duration.minutes(15), memory_size=1024,
            environment={
                "CORPUS_BUCKET": corpus_bucket.bucket_name,
                "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
            })
        corpus_bucket.grant_read(reindex)
        reindex.add_to_role_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))

        # AOSS data access is governed ONLY by this policy — an IAM principal
        # with aoss:APIAccessAll still gets 403 unless it is named here.
        #
        # The two Lambda roles are not sufficient, and this is a gap in
        # SPEC/02's Done-when rather than a convenience: `run_retrieval.py`
        # calls router.retrieve() IN-PROCESS, deliberately, so that a failure
        # means "the chunk never came back" and not "the model fumbled it".
        # In-process means it runs as the operator's own principal. Without an
        # opt-in for that principal, the AOSS half of criterion 1 cannot be
        # executed by the person the spec asks to execute it.
        #
        # Opt-in and empty by default, so a deploy that does not ask for it
        # grants nothing: `cdk deploy -c devPrincipalArn=arn:...:user/you`, or
        # REGDELTA_DEV_PRINCIPAL_ARN in the environment. `make up` passes the
        # caller's own STS identity. Read/write is still aoss:* pending the
        # SPEC/05 split below; narrow this to read-only when that happens,
        # since the eval harness only ever queries.
        principals = [reindex.role.role_arn, query_lambda_role_arn]
        dev_principal = (self.node.try_get_context("devPrincipalArn")
                         or os.environ.get("REGDELTA_DEV_PRINCIPAL_ARN"))
        if dev_principal:
            principals.append(dev_principal)

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
                "Principal": principals,
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
