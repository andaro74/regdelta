"""Does the SPEC/05 state-table policy actually behave as core_stack.py claims?

Six claims, each run as the restricted role against a throwaway table with the
real key schema. A throwaway rather than the live STATE_TABLE so nothing here
can write a row into production.

The claim that matters most is MIXED_BATCH. core_stack.py splits the policy by
ACTION rather than by PREFIX on the argument that `ForAllValues:` requires
every key in a request to match the statement's own patterns, so two per-prefix
statements would deny the one BatchWriteItem `delete_thread` issues. If that
reasoning is wrong, the split could have been written the other way and the
comment in core_stack.py is a story rather than a reason.

Everything is torn down at the end, including on failure.
"""
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-2"
TABLE = "regdelta-m05-leadingkeys-probe"
ROLE = "regdelta-m05-leadingkeys-probe"
POLICY = "probe"

iam = boto3.client("iam")
ddb = boto3.client("dynamodb", region_name=REGION)
sts = boto3.client("sts")
ACCOUNT = sts.get_caller_identity()["Account"]
CALLER = sts.get_caller_identity()["Arn"]
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}"


def policy_document():
    """The statements core_stack.py synthesizes, verbatim in shape."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Action": ["dynamodb:GetItem", "dynamodb:BatchGetItem",
                        "dynamodb:Query", "dynamodb:ConditionCheckItem"],
             "Resource": TABLE_ARN,
             "Condition": {"ForAllValues:StringLike": {
                 "dynamodb:LeadingKeys": ["THREAD#*"]}}},
            {"Effect": "Allow",
             "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem",
                        "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"],
             "Resource": TABLE_ARN,
             "Condition": {"ForAllValues:StringLike": {
                 "dynamodb:LeadingKeys": ["THREAD#*", "REVIEW#*"]}}},
            {"Effect": "Allow", "Action": ["dynamodb:DescribeTable"],
             "Resource": TABLE_ARN},
        ],
    }


def setup():
    print("creating table", TABLE)
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        BillingMode="PAY_PER_REQUEST")
    ddb.get_waiter("table_exists").wait(TableName=TABLE)

    print("creating role", ROLE)
    trust = {"Version": "2012-10-17",
             "Statement": [{"Effect": "Allow",
                            "Principal": {"AWS": CALLER},
                            "Action": "sts:AssumeRole"}]}
    iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                    Description="M05 LeadingKeys probe. Safe to delete.")
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                        PolicyDocument=json.dumps(policy_document()))


def restricted_client():
    """Assume the probe role, retrying while IAM converges."""
    arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    for attempt in range(30):
        try:
            creds = sts.assume_role(RoleArn=arn,
                                    RoleSessionName="m05probe")["Credentials"]
            return boto3.client(
                "dynamodb", region_name=REGION,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"])
        except ClientError as exc:
            if attempt == 29:
                raise
            print(f"  assume_role not ready ({exc.response['Error']['Code']}), "
                  f"retry {attempt + 1}")
            time.sleep(2)
    raise AssertionError("unreachable")


def run(label, fn, expect):
    """Run one call and report ALLOW/DENY against what the policy claims.

    Retries an unexpected DENY: a freshly attached inline policy is eventually
    consistent, and a propagation delay reads exactly like a correct denial.
    Never retries an unexpected ALLOW — that direction cannot be a delay.
    """
    for attempt in range(15):
        try:
            fn()
            got = "ALLOW"
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            got = "DENY" if code == "AccessDeniedException" else f"ERROR:{code}"
        if got == expect or got.startswith("ERROR") or expect == "ALLOW":
            break
        if got == "DENY" and expect == "DENY":
            break
        time.sleep(2)
    if got != expect and got == "DENY" and expect == "ALLOW":
        pass
    ok = "ok " if got == expect else "FAIL"
    print(f"  [{ok}] {label:<44} expected {expect:<5} got {got}")
    return got == expect


def probe(c):
    results = []
    results.append(run(
        "Query THREAD# partition", lambda: c.query(
            TableName=TABLE, KeyConditionExpression="pk = :p",
            ExpressionAttributeValues={":p": {"S": "THREAD#t1"}}), "ALLOW"))
    results.append(run(
        "Query REVIEW# partition (the forbidden read)", lambda: c.query(
            TableName=TABLE, KeyConditionExpression="pk = :p",
            ExpressionAttributeValues={":p": {"S": "REVIEW#t1"}}), "DENY"))
    results.append(run(
        "GetItem REVIEW# (the other read path)", lambda: c.get_item(
            TableName=TABLE,
            Key={"pk": {"S": "REVIEW#t1"}, "sk": {"S": "ITEM"}}), "DENY"))
    results.append(run(
        "PutItem REVIEW# (write_review_item)", lambda: c.put_item(
            TableName=TABLE,
            Item={"pk": {"S": "REVIEW#t1"}, "sk": {"S": "ITEM"},
                  "question": {"S": "probe"}}), "ALLOW"))
    results.append(run(
        "MIXED BatchWriteItem THREAD#+REVIEW#", lambda: c.batch_write_item(
            RequestItems={TABLE: [
                {"DeleteRequest": {"Key": {"pk": {"S": "THREAD#t1"},
                                           "sk": {"S": "CKPT#1"}}}},
                {"DeleteRequest": {"Key": {"pk": {"S": "REVIEW#t1"},
                                           "sk": {"S": "ITEM"}}}},
            ]}), "ALLOW"))
    results.append(run(
        "Scan (never granted)", lambda: c.scan(TableName=TABLE), "DENY"))
    return results


def teardown():
    for label, fn in [
        ("role policy", lambda: iam.delete_role_policy(RoleName=ROLE,
                                                       PolicyName=POLICY)),
        ("role", lambda: iam.delete_role(RoleName=ROLE)),
        ("table", lambda: ddb.delete_table(TableName=TABLE)),
    ]:
        try:
            fn()
            print("  deleted", label)
        except ClientError as exc:
            print("  could not delete", label, exc.response["Error"]["Code"])


if __name__ == "__main__":
    setup()
    try:
        results = probe(restricted_client())
    finally:
        print("teardown")
        teardown()
    print(f"\n{sum(results)}/{len(results)} claims held")
    sys.exit(0 if all(results) else 1)
