"""Can CloudFormation still delete a stack whose SSM parameter is already gone?

THE HYDRATION GATE DEPENDS ON THIS. The gate makes `reindex` delete
`/regdelta/search/endpoint` as hydration's first act and write it back only
after count-parity and the kNN mapping assert both pass. That leaves the
parameter absent whenever hydration failed -- while `regdelta-search` still
declares it as an `AWS::SSM::Parameter` it owns.

Two ways that could go wrong, and both are worse than the bug being fixed:

  1. If `DeleteStack` fails on the missing parameter, the stack lands in
     DELETE_FAILED. `make down` stops working, the janitor stops working, and
     a collection bills at ~$0.24/hr until someone notices by hand. Trading a
     silent wrong answer for an unbounded bill is not a fix.
  2. If a later stack UPDATE re-creates the parameter, the gate leaks: a
     redeploy that never re-ran hydration would republish the endpoint and
     point retrieval back at an index nobody verified.

Neither is reasoned about here. Both are run.

Free: SSM standard parameters and CloudFormation cost nothing, and no AOSS
collection is involved. Tears down at the end, including on failure.

Result, 2026-08-20 (us-west-2, account 581208540944):

    unchanged UPDATE   EndpointParam stayed DELETED, and UnrelatedChange was
                       CREATE_COMPLETE in the same update -- so the update
                       really ran and simply did not touch the parameter.
    DELETE stack       EndpointParam DELETE_COMPLETE, stack DELETE_COMPLETE.
                       CloudFormation's SSM::Parameter delete is idempotent.

Both premises hold, so the gate is safe in both directions.
"""
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-2"
STACK = "regdelta-probe-orphan-param"
# NOT /regdelta/search/endpoint. This probe deletes what it points at, and the
# real parameter is the one thing in the account that flips the retrieval tier.
PARAM = "/regdelta/probe/orphan-endpoint"
UNRELATED = "/regdelta/probe/orphan-unrelated"

cfn = boto3.client("cloudformation", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)


def template(with_unrelated: bool) -> str:
    """v1 = the parameter alone. v2 adds a second, unrelated resource.

    v2 exists because CloudFormation rejects an update with no changes
    ("No updates are to be performed"), so proving "the update left
    EndpointParam alone" needs some OTHER resource to be the change. If
    UnrelatedChange comes back CREATE_COMPLETE, the update ran.
    """
    resources = {
        "EndpointParam": {
            "Type": "AWS::SSM::Parameter",
            "Properties": {"Name": PARAM, "Type": "String",
                           "Value": "https://probe.example.invalid"},
        },
    }
    if with_unrelated:
        resources["UnrelatedChange"] = {
            "Type": "AWS::SSM::Parameter",
            "Properties": {
                "Name": UNRELATED, "Type": "String",
                "Value": "forces-an-update-that-leaves-EndpointParam-untouched"},
        }
    return json.dumps({"AWSTemplateFormatVersion": "2010-09-09",
                       "Description": "M05 hydration-gate probe. Inert. "
                                      "Safe to delete.",
                       "Resources": resources})


def wait(stack_ref: str, terminal: tuple[str, ...]) -> str:
    """Poll describe-stacks. Deliberately not `cfn.get_waiter`.

    A waiter raises on the failure states this probe is trying to OBSERVE --
    DELETE_FAILED is the interesting answer here, not an exception.
    """
    while True:
        try:
            status = cfn.describe_stacks(
                StackName=stack_ref)["Stacks"][0]["StackStatus"]
        except ClientError as e:
            if "does not exist" in str(e):
                return "GONE"
            raise
        if status.endswith(terminal):
            return status
        time.sleep(3)


def exists(name: str) -> bool:
    try:
        ssm.get_parameter(Name=name)
        return True
    except ssm.exceptions.ParameterNotFound:
        return False


def main() -> int:
    ok = True
    stack_id = None
    try:
        print(f"-> create {STACK}")
        stack_id = cfn.create_stack(
            StackName=STACK, TemplateBody=template(False))["StackId"]
        assert wait(stack_id, ("_COMPLETE", "_FAILED")) == "CREATE_COMPLETE"
        assert exists(PARAM), "the stack did not create the parameter"

        # What a failed hydration does: the reindex Lambda retires the
        # parameter, then raises before it can write it back.
        print("-> delete the parameter out of band (simulating failed hydration)")
        ssm.delete_parameter(Name=PARAM)
        assert not exists(PARAM)

        print("-> UPDATE the stack, leaving EndpointParam untouched")
        cfn.update_stack(StackName=STACK, TemplateBody=template(True))
        status = wait(stack_id, ("_COMPLETE", "_FAILED"))
        resurrected = exists(PARAM)
        update_ran = exists(UNRELATED)
        print(json.dumps({"update_status": status,
                          "unrelated_resource_created": update_ran,
                          "endpoint_param_resurrected": resurrected}))
        if not update_ran:
            print("INCONCLUSIVE: the update did not create UnrelatedChange, so "
                  "'it left EndpointParam alone' is not established", file=sys.stderr)
            ok = False
        if resurrected:
            print("FAIL: an unchanged update RE-CREATED the endpoint parameter "
                  "-- the hydration gate would leak on every redeploy",
                  file=sys.stderr)
            ok = False

        print("-> DELETE the stack with the parameter still missing")
        cfn.delete_stack(StackName=STACK)
        status = wait(stack_id, ("_COMPLETE", "_FAILED"))
        events = [
            {"id": e["LogicalResourceId"], "status": e["ResourceStatus"],
             "reason": e.get("ResourceStatusReason")}
            for e in cfn.describe_stack_events(StackName=stack_id)["StackEvents"]
            if e["LogicalResourceId"] == "EndpointParam"
            and e["ResourceStatus"].startswith("DELETE")
        ]
        print(json.dumps({"delete_status": status,
                          "endpoint_param_delete_events": events}))
        if status != "DELETE_COMPLETE":
            print(f"FAIL: DeleteStack ended {status} with the parameter already "
                  "gone -- `make down` and the janitor would both be blocked and "
                  "an AOSS collection would keep billing", file=sys.stderr)
            ok = False
        stack_id = None
    finally:
        if stack_id is not None:
            print("-> teardown", file=sys.stderr)
            try:
                cfn.delete_stack(StackName=STACK)
                wait(stack_id, ("_COMPLETE", "_FAILED"))
            except ClientError as e:
                print(f"teardown failed: {e}", file=sys.stderr)
        for name in (PARAM, UNRELATED):
            try:
                ssm.delete_parameter(Name=name)
                print(f"-> swept leftover {name}", file=sys.stderr)
            except ssm.exceptions.ParameterNotFound:
                pass

    print("PASS -- the gate is safe in both directions" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
