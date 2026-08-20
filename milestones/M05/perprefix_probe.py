"""The counter-claim: would a per-PREFIX split really deny the mixed batch?

core_stack.py justifies splitting the state-table policy by ACTION with this
argument:

    `dynamodb:LeadingKeys` under `ForAllValues:StringLike` requires EVERY key
    in the request to match the statement's patterns, so a single
    `BatchWriteItem` carrying both a `THREAD#` and a `REVIEW#` key satisfies
    neither of two per-prefix statements and is denied.

That is a claim about IAM, written as the reason for a design. If it is false,
the comment is a story. This builds the REJECTED policy — read+write on
THREAD#* in one statement, write-only on REVIEW#* in another — and issues the
exact batch `delete_thread` issues.

Expected: DENY. An ALLOW here means the reasoning in core_stack.py is wrong and
the comment has to change even though the code would not.
"""
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-2"
TABLE = "regdelta-m05-perprefix-probe"
ROLE = "regdelta-m05-perprefix-probe"
POLICY = "probe"

iam = boto3.client("iam")
ddb = boto3.client("dynamodb", region_name=REGION)
sts = boto3.client("sts")
ident = sts.get_caller_identity()
ACCOUNT, CALLER = ident["Account"], ident["Arn"]
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}"

REJECTED_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        # Per-prefix statement 1: everything THREAD#.
        {"Effect": "Allow",
         "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem",
                    "dynamodb:UpdateItem", "dynamodb:DeleteItem",
                    "dynamodb:BatchWriteItem"],
         "Resource": TABLE_ARN,
         "Condition": {"ForAllValues:StringLike": {
             "dynamodb:LeadingKeys": ["THREAD#*"]}}},
        # Per-prefix statement 2: writes only, REVIEW#.
        {"Effect": "Allow",
         "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"],
         "Resource": TABLE_ARN,
         "Condition": {"ForAllValues:StringLike": {
             "dynamodb:LeadingKeys": ["REVIEW#*"]}}},
        {"Effect": "Allow", "Action": ["dynamodb:DescribeTable"],
         "Resource": TABLE_ARN},
    ],
}


def setup():
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        BillingMode="PAY_PER_REQUEST")
    ddb.get_waiter("table_exists").wait(TableName=TABLE)
    trust = {"Version": "2012-10-17",
             "Statement": [{"Effect": "Allow", "Principal": {"AWS": CALLER},
                            "Action": "sts:AssumeRole"}]}
    iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                    Description="M05 per-prefix counter-probe. Safe to delete.")
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                        PolicyDocument=json.dumps(REJECTED_POLICY))


def restricted():
    arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    for attempt in range(30):
        try:
            c = sts.assume_role(RoleArn=arn, RoleSessionName="m05pp")["Credentials"]
            return boto3.client("dynamodb", region_name=REGION,
                                aws_access_key_id=c["AccessKeyId"],
                                aws_secret_access_key=c["SecretAccessKey"],
                                aws_session_token=c["SessionToken"])
        except ClientError:
            if attempt == 29:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def call(c, label, fn, expect):
    """Retry an unexpected result while IAM converges, then report.

    Both directions are retried here, unlike the main probe: a fresh policy can
    read as DENY before it propagates, and this test EXPECTS a deny — so
    stopping at the first deny would let propagation masquerade as the finding.
    """
    got = None
    for _ in range(12):
        try:
            fn()
            got = "ALLOW"
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            got = "DENY" if code == "AccessDeniedException" else f"ERROR:{code}"
        if got == expect:
            break
        time.sleep(3)
    ok = "ok " if got == expect else "FAIL"
    print(f"  [{ok}] {label:<44} expected {expect:<5} got {got}")
    return got == expect


def teardown():
    for fn in (lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName=POLICY),
               lambda: iam.delete_role(RoleName=ROLE),
               lambda: ddb.delete_table(TableName=TABLE)):
        try:
            fn()
        except ClientError as exc:
            print("  teardown:", exc.response["Error"]["Code"])


if __name__ == "__main__":
    setup()
    try:
        c = restricted()
        results = [
            # The control: a single-prefix batch is fine under this policy, so
            # a DENY below cannot be blamed on BatchWriteItem being ungranted.
            call(c, "single-prefix BatchWriteItem (control)",
                 lambda: c.batch_write_item(RequestItems={TABLE: [
                     {"DeleteRequest": {"Key": {"pk": {"S": "THREAD#t1"},
                                                "sk": {"S": "CKPT#1"}}}}]}),
                 "ALLOW"),
            call(c, "MIXED BatchWriteItem under per-prefix split",
                 lambda: c.batch_write_item(RequestItems={TABLE: [
                     {"DeleteRequest": {"Key": {"pk": {"S": "THREAD#t1"},
                                                "sk": {"S": "CKPT#1"}}}},
                     {"DeleteRequest": {"Key": {"pk": {"S": "REVIEW#t1"},
                                                "sk": {"S": "ITEM"}}}}]}),
                 "DENY"),
        ]
    finally:
        teardown()
    print(f"\n{sum(results)}/{len(results)} — the rejected design fails as claimed"
          if all(results) else
          f"\n{sum(results)}/{len(results)} — core_stack.py's reasoning needs revising")
    sys.exit(0 if all(results) else 1)
