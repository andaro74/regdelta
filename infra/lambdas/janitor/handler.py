"""Nightly janitor: delete regdelta-search if still up. Prevents the
forgotten-collection failure mode (~$175/month at the dev OCU floor).

WHAT THIS RETURNS IS A CLAIM ABOUT THE REQUEST, NOT ABOUT THE BILLING.
ADR-0013. Deleting an AOSS collection takes minutes and this function has a
two-minute timeout, so it cannot watch the deletion finish and must not imply
that it did. `delete-requested` is therefore the strongest honest status for a
delete this invocation started; `already-down` is the only status here that
means OCU billing has actually stopped, and it is the only one reached by
OBSERVING the stack rather than by acting on it.

Until M05 this returned `delete-initiated` for the acting case, which read as
the stronger claim, and it treated `DELETE_FAILED` as `no-action` — so a stack
that had failed to delete was reported as needing nothing, nightly, forever,
while the collection billed. That is the exact failure mode the janitor exists
to prevent, wearing the janitor's own success message.

## What was NOT wrong with it, measured 2026-08-19

The M04 pack records (README:860) that this function "does not work at all —
it calls `delete_stack` with no `RoleARN` while holding only `DeleteStack` and
`DescribeStacks`, so it reports `delete-initiated` and lands in
`DELETE_FAILED`". **That is false, and it was reasoned rather than run.**

Probed against the live account: an inert CloudFormation stack named
`regdelta-search` holding one SSM parameter, created with the same
`cdk-hnb659fds-cfn-exec-role` every `cdk deploy` in this account associates,
then this function invoked against it unchanged. The stack was **deleted**, and
so was the parameter — `ParameterNotFound` afterwards, so the resource went and
not merely the stack record. CloudFormation reuses a stack's associated role
for later operations and does not re-check `iam:PassRole`, exactly as its docs
say.

So the RoleARN change below is a NARROWING, not a repair: it swaps an
`AdministratorAccess` bootstrap role for a delete-only one on the unattended
nightly path. The two defects above are the real breakage, and they are
unaffected by this correction.

What the probe does not establish is that deleting the REAL search stack
succeeds — an AOSS collection, two Lambdas, two roles and a custom resource are
not one SSM parameter. That is settled by the live teardown, not here.
"""
import json
import os

import boto3

STACK = os.environ["SEARCH_STACK_NAME"]
# The dedicated deletion role (SPEC/05). Passing it EXPLICITLY rather than
# letting CloudFormation reuse whatever role the stack was created with is the
# point of the change: `make up` runs under the CDK bootstrap execution role,
# which carries AdministratorAccess, and the unattended nightly path should not
# inherit it. `core_stack.py` grants this function `iam:PassRole` on exactly
# this ARN and pins the same string into this variable.
ROLE_ARN = os.environ["SEARCH_CFN_ROLE_ARN"]

cfn = boto3.client("cloudformation")

#: Stack states in which a delete is worth issuing.
#:
#: DELETE_FAILED IS IN THIS LIST DELIBERATELY. A stack that failed to delete
#: still has its collection, and therefore still bills; the previous code's
#: `_COMPLETE`-suffix test excluded it, which turned the one state that most
#: needs a retry into a silent no-action. Re-issuing DeleteStack on a
#: DELETE_FAILED stack is the documented recovery, and with a role that can
#: actually delete the resources it is now likely to succeed.
_DELETABLE = (
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
    "ROLLBACK_COMPLETE",
    "IMPORT_COMPLETE",
    "IMPORT_ROLLBACK_COMPLETE",
    "DELETE_FAILED",
)
#: Already on its way down. Issuing a second delete would not be harmful, but
#: reporting "requested" for a delete this run did not start would be.
_IN_FLIGHT = ("DELETE_IN_PROGRESS", "CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS",
              "UPDATE_ROLLBACK_IN_PROGRESS", "ROLLBACK_IN_PROGRESS")


def handler(event, context):
    try:
        stacks = cfn.describe_stacks(StackName=STACK)["Stacks"]
    except cfn.exceptions.ClientError:
        # The only branch that may claim billing has stopped, because it is the
        # only one that observed the absence rather than requesting it.
        return _log({"status": "already-down", "billing_stopped": True})

    state = stacks[0]["StackStatus"]

    if state in _IN_FLIGHT:
        return _log({"status": "no-action", "state": state,
                     "billing_stopped": False,
                     "detail": "a stack operation is already in flight"})

    if state not in _DELETABLE:
        # Unknown state: say so and say it is unhandled, rather than returning
        # a no-action that reads as "nothing to do here". A state this function
        # does not recognise on a stack that exists is a collection that may
        # still be billing.
        return _log({"status": "unhandled-state", "state": state,
                     "billing_stopped": False,
                     "detail": "not in the deletable or in-flight sets; the "
                               "collection may still be billing"})

    cfn.delete_stack(StackName=STACK, RoleARN=ROLE_ARN)
    return _log({
        "status": "delete-requested",
        "was": state,
        # NOT a claim that the stack is gone. Deleting the collection takes
        # minutes; this function has two. The next nightly run observes the
        # outcome, and a retry_of_failed run says the previous one did not work.
        "billing_stopped": False,
        "retry_of_failed": state == "DELETE_FAILED",
        "role_arn": ROLE_ARN,
    })


def _log(result: dict) -> dict:
    """One structured line per run, so the outcome is greppable in CloudWatch.

    The return value of a scheduled invocation goes nowhere — EventBridge
    discards it — so until this printed, every status above was written for a
    reader who did not exist. SPEC/06 owns the alarm; this is what it will have
    to match on.
    """
    print(json.dumps({"janitor": result, "stack": STACK}, sort_keys=True))
    return result
