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
def test_no_inline_grant_on_the_internet_facing_role_uses_a_bare_wildcard(template):
    """THE FINDING, as one assertion. Anything reachable by a stranger's HTTP
    request should not be able to name every resource in the account.

    INLINE policies only, and the name says so. The role also carries managed
    policies, which this cannot see — covered by the test below instead of being
    quietly included in a claim about "the role".
    """
    offenders = [(_actions(s), _resources(s)) for s in query_statements(template)
                 if s.get("Effect") == "Allow" and "*" in _resources(s)]
    assert offenders == [], f"wildcard resources on QueryFn: {offenders}"


def test_the_role_attaches_only_the_managed_policies_we_expect(template):
    """Security review of this change, finding 4.

    The wildcard test above walks `AWS::IAM::Policy` resources and never looks
    at `ManagedPolicyArns` — so attaching a managed policy was the one way to
    widen this role without tripping any test in this file. The basic execution
    role does grant `logs:*` on `Resource: "*"`, which is the standard Lambda
    grant and is not what this is about; an allowlist is, because
    `AdministratorAccess` would have read exactly the same to every assertion
    here.
    """
    role = _query_role(template)
    managed = template["Resources"][role]["Properties"].get("ManagedPolicyArns", [])
    names = sorted(
        str(m["Fn::Join"][1][-1] if isinstance(m, dict) else m) for m in managed)
    assert names == [":iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"], \
        names


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


# ------------------------------------------- policy and runtime, same string
def test_the_models_granted_are_the_models_the_function_is_told_to_use(template):
    """Security review of this change, finding 2.

    The policy resolves `config.MODEL_*` in the SYNTH process — the operator's
    shell during `make core`. The function resolved them again at runtime from
    its own environment, which set none of them, so the two agreed only when the
    deployer had nothing exported. `config.py` invites exactly that divergence:
    "Raise MODEL_VERDICT to Opus 4.7 once account model access is granted."

    Export it, run `make core`, and you deploy a policy granting 4.7 to a
    function still invoking 4.6 — AccessDenied on the verdict node of every
    anonymous query. Under the old `Resource: "*"` this was impossible; the
    narrowing introduced it, and it presents as a Bedrock error in the demo
    rather than a failed build, which is the outcome the scoping was meant to
    prevent.

    Pinning the ids into the function's environment makes policy and runtime
    the same string by construction, and this asserts the correspondence rather
    than the values.
    """
    query = next(r["Properties"] for r in template["Resources"].values()
                 if r["Type"] == "AWS::Lambda::Function"
                 and r["Properties"].get("Handler") == "api.api.handler")
    env = query["Environment"]["Variables"]
    granted = " ".join(sorted(
        str(r) for s in _for_action(template, "bedrock:InvokeModel")
        for r in _resources(s)))

    for var in ("MODEL_FAST", "MODEL_VERDICT", "EMBED_MODEL"):
        assert var in env, f"{var} is not pinned into the function environment"
        assert env[var] in granted, \
            f"{var}={env[var]} is what the function will call, and it is not granted"
