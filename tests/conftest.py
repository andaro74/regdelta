"""Tests import modules the way Lambda does (src/ is the package root)."""
import contextlib
import os
import sys
import tempfile
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


# THE DEPENDENCY LAYER IS A BUILD ARTIFACT AND CI DOES NOT HAVE ONE.
#
# `make layer` writes build/lambda-layer (~101MB), which is not committed, and
# RegDeltaCoreStack refuses to synth without it — deliberately, because an
# empty layer deploys a function whose imports fail in the region.
#
# Same class of defect as the AWS-profile block above, found the same way. On
# 2026-08-22 tests/test_ci_eval_role.py synthesised the core stack directly and
# passed on a laptop that had run `make layer` months earlier; its first CI run
# produced nine errors reading "build/lambda-layer does not exist". The local
# suite had been called green for the whole milestone.
#
# So the stub lives here rather than in one test module: any test asserting
# stack SHAPE must be unable to see the developer's artifact at all, whether or
# not it happens to exist. tests/test_core_stack_assets.py owns the test that
# asserts the refusal itself, which is the guard that makes stubbing safe.
#
# ROOT CAUSE, and it is still open. This was already copy-pasted into FOUR
# modules — test_core_stack_assets.py, test_query_fn_iam.py, test_janitor.py,
# test_observability_stack.py — with no shared home, so a fifth module that
# synthesises the core stack skips it by simply not knowing. That is what
# happened. This definition is the home; the four copies predate M07 and are
# NOT collapsed into it here, because they pass and a five-module refactor does
# not belong in the branch that found the bug. Carried in
# milestones/M07/README.md as open.
@contextlib.contextmanager
def stub_layer():
    """Point core_stack.LAYER_SRC at an empty but well-formed layer directory."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "infra"))
    from core import core_stack

    original = core_stack.LAYER_SRC
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "python").mkdir()
        core_stack.LAYER_SRC = Path(tmp)
        try:
            yield
        finally:
            core_stack.LAYER_SRC = original
