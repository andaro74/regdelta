"""Nightly janitor: delete regdelta-search if still up. Prevents the
forgotten-collection failure mode (~$175/month at the dev OCU floor)."""
import os

import boto3

STACK = os.environ["SEARCH_STACK_NAME"]
cfn = boto3.client("cloudformation")


def handler(event, context):
    try:
        stacks = cfn.describe_stacks(StackName=STACK)["Stacks"]
    except cfn.exceptions.ClientError:
        return {"status": "already-down"}
    state = stacks[0]["StackStatus"]
    if state.endswith("_COMPLETE") and not state.startswith("DELETE"):
        # TODO SPEC/05: deploy regdelta-search with a dedicated CFN
        # execution role; grant iam:PassRole here so resource deletion works.
        cfn.delete_stack(StackName=STACK)
        return {"status": "delete-initiated", "was": state}
    return {"status": "no-action", "state": state}
