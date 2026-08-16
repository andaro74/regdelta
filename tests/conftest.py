"""Tests import modules the way Lambda does (src/ is the package root)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURES = Path(__file__).parent / "fixtures"

# A UNIT TEST MUST NOT DEPEND ON THE DEVELOPER'S AWS PROFILE.
#
# src/graph/nodes.py states the rule this enforces: "unit tests must run without
# AWS". Three tests did not. They passed on a laptop with credentials and a
# region configured, and failed the first time CI ran them:
#
#   test_rerank.py x2                 botocore NoRegionError — boto3 cannot
#                                     build a client with no region anywhere
#   test_retrieval_router.py          aoss_client.request() checks credentials
#                                     BEFORE the urlopen the test mocks, so with
#                                     none present it raised "no AWS credentials
#                                     available for SigV4" instead of the
#                                     "unreachable" the test asserts
#
# Set rather than defaulted, deliberately. `setdefault` would leave the suite
# behaving one way for whoever has a profile exported and another way in CI,
# which is the defect itself rather than a fix for it. These values are
# syntactically valid and functionally useless: every AWS call in this suite is
# mocked, and anything that genuinely reached AWS with them would fail loudly
# rather than quietly touch a real account. Integration lives in the make
# targets, not in pytest.
os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
    # Kills the ~/.aws/config lookup as well, so a profile with a different
    # region cannot reach in either.
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
})
