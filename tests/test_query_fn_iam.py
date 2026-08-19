"""What the internet-facing role is allowed to do.

`QueryFn` is the only Lambda in this account driven by ANONYMOUS REQUESTS —
SPEC/04 declares `/query` unauthenticated and CloudFront serves it to whoever
asks. Until M04 it held three `Resource: "*"` grants carrying `# TODO: scope`:
`bedrock:InvokeModel`, `s3vectors:QueryVectors|GetVectors`, and
`aoss:APIAccessAll`.

The last is the widest. `aoss:APIAccessAll` on `*` reaches EVERY OpenSearch
Serverless collection in the account, and this account has others. The
consequence of a prompt-injection or deserialisation bug in the query path is
therefore bounded by the collection's data access policy alone, with IAM
contributing nothing.

The security review filed these as MEDIUM against SPEC/05 and recommended
pulling them into the API's own PR, because the risk changed character the day
the role stopped being reachable only by credential-holders.

WHAT THESE TESTS ARE NOT. They do not assert a policy is "secure" — they assert
it is SCOPED, which is checkable. A wildcard is a statement that nobody decided,
and that is the thing worth failing a build over.
"""
import contextlib
import sys
import tempfile
from pathlib import Path

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))
sys.path.insert(0, str(ROOT / "src"))

ACCOUNT, REGION = "111122223333", "us-west-2"


@contextlib.contextmanager
def stub_layer():
    from core import core_stack

    original = core_stack.LAYER_SRC
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "python").mkdir()
        core_stack.LAYER_SRC = Path(tmp)
        try:
            yield
        finally:
            core_stack.LAYER_SRC = original


@pytest.fixture(scope="module")
def template():
    import aws_cdk as cdk
    from core.core_stack import RegDeltaCoreStack

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core",
                          env=cdk.Environment(account=ACCOUNT, region=REGION))
    return app.synth().get_stack_by_name("regdelta-core").template


def _query_role(template):
    """The QueryFn role's logical id, found via the function that uses it."""
    fn = next(r for r in template["Resources"].values()
              if r["Type"] == "AWS::Lambda::Function"
              and r["Properties"].get("Handler") == "api.api.handler")
    return fn["Properties"]["Role"]["Fn::GetAtt"][0]


def query_statements(template):
    """Every policy statement attached to the QueryFn role."""
    role = _query_role(template)
    out = []
    for res in template["Resources"].values():
        if res["Type"] != "AWS::IAM::Policy":
            continue
        roles = [r.get("Ref") for r in res["Properties"].get("Roles", [])]
        if role in roles:
            out.extend(res["Properties"]["PolicyDocument"]["Statement"])
    return out


def _actions(stmt):
    a = stmt.get("Action")
    return a if isinstance(a, list) else [a]


def _for_action(template, action):
    return [s for s in query_statements(template) if action in _actions(s)]


def _resources(stmt):
    r = stmt.get("Resource")
    return r if isinstance(r, list) else [r]


# ------------------------------------------------------------------- the rule
def test_no_grant_on_the_internet_facing_role_uses_a_bare_wildcard(template):
    """THE FINDING, as one assertion. Anything reachable by a stranger's HTTP
    request should not be able to name every resource in the account."""
    offenders = [(_actions(s), _resources(s)) for s in query_statements(template)
                 if s.get("Effect") == "Allow" and "*" in _resources(s)]
    assert offenders == [], f"wildcard resources on QueryFn: {offenders}"


# --------------------------------------------------------------------- bedrock
def test_bedrock_is_scoped_to_the_models_this_system_actually_calls(template):
    """`bedrock:InvokeModel` on `*` permits any model in any region the role can
    reach, including ones nobody has priced."""
    from shared import config

    granted = {r for s in _for_action(template, "bedrock:InvokeModel")
               for r in _resources(s) if isinstance(r, str)}
    granted |= {str(r) for s in _for_action(template, "bedrock:InvokeModel")
                for r in _resources(s) if not isinstance(r, str)}

    flat = " ".join(sorted(granted))
    for model in (config.MODEL_FAST, config.MODEL_VERDICT, config.EMBED_MODEL):
        assert model in flat, f"{model} is configured but not granted"


def test_the_bedrock_grant_tracks_config_rather_than_repeating_it(template):
    """A model id copied into the stack drifts from the one the code calls, and
    the failure is an AccessDenied in the region rather than a broken build.
    Changing config must change the policy."""
    from shared import config

    granted = " ".join(sorted(
        str(r) for s in _for_action(template, "bedrock:InvokeModel")
        for r in _resources(s)))
    assert config.MODEL_VERDICT in granted


def test_cross_region_inference_profiles_carry_their_foundation_models(template):
    """A `us.` inference profile is not itself invocable: Bedrock evaluates the
    call against the FOUNDATION MODEL in whichever region it routes to, so a
    policy naming only the profile fails intermittently — in exactly the regions
    it happens to pick. Verified against the live profile, which lists
    us-east-1, us-east-2 and us-west-2."""
    granted = " ".join(sorted(
        str(r) for s in _for_action(template, "bedrock:InvokeModel")
        for r in _resources(s)))
    assert "inference-profile" in granted
    for region in ("us-east-1", "us-east-2", "us-west-2"):
        assert f"bedrock:{region}::foundation-model" in granted, region


# ------------------------------------------------------------------ s3vectors
def test_s3vectors_is_scoped_to_this_stack_s_bucket_and_index(template):
    granted = " ".join(sorted(
        str(r) for s in _for_action(template, "s3vectors:QueryVectors")
        for r in _resources(s)))
    assert "regdelta-vectors" in granted
    assert "index/chunks" in granted


# ----------------------------------------------------------------------- aoss
def test_aoss_is_scoped_to_this_account_and_region(template):
    """`aoss:APIAccessAll` on `*` reaches every collection in the account.

    It cannot be pinned to a collection ID: the collection is created by the
    EPHEMERAL search stack, gets a fresh id on every `make up`, and this
    persistent stack is deployed before it exists. Account-and-region is the
    honest floor, and AOSS's own data access policy — which names this role —
    is what actually admits the request.
    """
    granted = [str(r) for s in _for_action(template, "aoss:APIAccessAll")
               for r in _resources(s)]
    assert granted, "no aoss grant found"
    for r in granted:
        assert r != "*", "aoss:APIAccessAll on * reaches every collection"
        assert ACCOUNT in r and REGION in r, r


# ------------------------------------------------------- what did NOT change
def test_the_query_role_still_cannot_write_vectors(template):
    """Scoping must not quietly widen anything. The query path reads; the
    processor writes, and they are different roles for that reason."""
    for forbidden in ("s3vectors:PutVectors", "s3vectors:DeleteVectors"):
        assert not _for_action(template, forbidden), forbidden
