#!/usr/bin/env python3
"""RegDelta CDK app — two stacks, two lifespans.

regdelta-core    persistent: corpus S3, S3 Vectors, DynamoDB, ingestion,
                 API, UI, evals, janitor
regdelta-search  ephemeral:  AOSS collection + policies + reindex trigger

search depends on core; core never references search, so
`cdk destroy regdelta-search` is always safe.
"""
import os

import aws_cdk as cdk
from core.core_stack import RegDeltaCoreStack
from search.search_stack import RegDeltaSearchStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

core = RegDeltaCoreStack(app, "regdelta-core", env=env)
search = RegDeltaSearchStack(
    app, "regdelta-search", env=env,
    corpus_bucket=core.corpus_bucket,
    query_lambda_role_arn=core.query_lambda_role_arn,
    # SPEC/06's disposition driver. Named here rather than defaulted in the
    # search stack: the grant it carries is what lets the Tier B half of the
    # measurement happen at all, and a silently-absent reader would record
    # 403s as Tier B's error rate.
    load_driver_role_arn=core.load_driver_role_arn,
)
search.add_dependency(core)
app.synth()
