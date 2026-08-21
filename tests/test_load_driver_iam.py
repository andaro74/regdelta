"""What SPEC/06's load driver is allowed to do.

`LoadDriverFn` dispatches up to 90 retrievals a second and every retrieval
embeds. It is the only thing in this account that could reach a Bedrock
per-minute quota by accident, and the seat's ceiling for M06 is $20 — so the
question this file answers is not "is the policy tidy" but "what is the worst
this function can spend and reach".

THE ANSWER HAS TO BE A GRANT, NOT A CODE PATH. `loadtest/budget.py` refuses on
dollars and on non-adjustable daily caps, and it is a Python object inside the
orchestrator; it cannot constrain a function someone invokes by hand with the
console's Test button. IAM can. So the driver holds `bedrock:InvokeModel` on
Titan Text Embeddings V2 and on nothing else: one minute of Opus 4.6 at this
account's non-adjustable per-minute quota is $23.63 and 115.7% of a
non-adjustable DAILY cap (milestones/M06/spec06-disposition-amendment.md), and
the driver cannot buy a token of it.

`tests/test_search_stack_access.py` covers the other half — the driver is an
AOSS index READER and never a writer — because that grant lives in the
ephemeral stack, with the collection it is about.
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

#: THE SAME ALLOWLIST, IMPORTED RATHER THAN COPIED. A second literal here would
#: be a second place to widen the X-Ray exemption, and the pinning test in that
#: module would keep passing while this role grew a third wildcard action.
from test_query_fn_iam import WILDCARD_EXEMPT  # noqa: E402

ACCOUNT, REGION = "111122223333", "us-west-2"

HANDLER = "ops.retrieval_load.handler"


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


def _function(template):
    return next(r for r in template["Resources"].values()
                if r["Type"] == "AWS::Lambda::Function"
                and r["Properties"].get("Handler") == HANDLER)


def driver_statements(template):
    role = _function(template)["Properties"]["Role"]["Fn::GetAtt"][0]
    out = []
    for res in template["Resources"].values():
        if res["Type"] != "AWS::IAM::Policy":
            continue
        if role in [r.get("Ref") for r in res["Properties"].get("Roles", [])]:
            out.extend(res["Properties"]["PolicyDocument"]["Statement"])
    return out


def _listed(value):
    return value if isinstance(value, list) else [value]


def _actions(stmt):
    return _listed(stmt.get("Action"))


def _resources(stmt):
    return _listed(stmt.get("Resource"))


def _flat(resource):
    """A resource entry as comparable text, tokens and all.

    Model ARNs synthesise as `Fn::Join` fragments because the partition and
    region are tokens. Flattening to a string lets an assertion say "the model
    id does not appear anywhere in what this role can invoke", which is the
    claim that matters and which a structural comparison would miss.
    """
    if isinstance(resource, str):
        return resource
    if isinstance(resource, dict):
        return " ".join(_flat(v) for v in resource.values())
    if isinstance(resource, list):
        return " ".join(_flat(v) for v in resource)
    return str(resource)


# ------------------------------------------------------------------ the money
def test_the_driver_can_invoke_the_embedding_model(template):
    """The positive half. A guard that can only refuse is indistinguishable
    from one that is broken, and without this grant every call in the
    disposition run fails identically on both tiers."""
    from shared import config

    invoke = [s for s in driver_statements(template)
              if "bedrock:InvokeModel" in _actions(s)]
    assert len(invoke) == 1, f"expected one bedrock statement, got {invoke}"
    # The whole statement, both halves: exactly one action, and exactly one
    # resource that names the embedder. A membership check on the resource
    # would pass a statement that also carried `bedrock:Converse`, and a
    # membership check on the action would pass a five-ARN resource list.
    assert set(_actions(invoke[0])) == {"bedrock:InvokeModel"}
    resources = _resources(invoke[0])
    assert len(resources) == 1, f"expected one model ARN, got {resources}"
    assert config.EMBED_MODEL in _flat(resources[0])


def test_the_driver_cannot_invoke_any_model_but_the_embedder(template):
    """THE FINDING THIS FILE EXISTS FOR.

    `_bedrock_model_arns()` returns five ARNs — two inference profiles, their
    foundation models across the profile's regions, and the embedder. Reusing
    it here (the obvious edit, and the one this test is written to fail) would
    hand a 90-call-per-second driver a grant on Opus 4.6.
    """
    from shared import config

    invoke = [s for s in driver_statements(template)
              if "bedrock:InvokeModel" in _actions(s)]
    granted = " ".join(_flat(r) for r in _resources(invoke[0]))
    for model in (config.MODEL_FAST, config.MODEL_VERDICT):
        assert model not in granted, (
            f"the load driver can invoke {model}; one minute of Opus at this "
            "account's per-minute quota is $23.63 and exceeds a NON-ADJUSTABLE "
            "daily cap")
        # The bare foundation-model id too: an inference profile is granted as
        # `inference-profile/us.anthropic...` AND as
        # `foundation-model/anthropic...`, and checking only the profile string
        # would miss the half that actually authorises the call.
        assert model.removeprefix("us.") not in granted
    assert "inference-profile" not in granted


def test_the_drivers_grants_are_exactly_these(template):
    """It reads a parameter, reads a table, queries a vector index, embeds and
    writes a trace. Everything else is a mistake, and the list is short enough
    to pin whole.

    AN EQUALITY, NOT A SUBSET BOUND, and the change is a finding rather than a
    preference. `granted <= allowed` detects widening and is blind to a grant
    going MISSING — the same asymmetry that let the driver's `aoss:APIAccessAll`
    ship with nothing pinning it, which security-reviewer found by deleting it
    and watching the whole suite stay green.
    """
    expected = {
        "ssm:GetParameter",
        "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query",
        "dynamodb:Scan", "dynamodb:ConditionCheckItem", "dynamodb:DescribeTable",
        # The registry table has a stream, so `grant_read_data` adds its two
        # stream READ actions. Listed rather than filtered out: they are reads,
        # they arrive with the same grant the query role already holds on this
        # table, and naming them is how a later `grant_read_write_data` — which
        # would add PutItem here and pass a laxer check — gets caught.
        "dynamodb:GetRecords", "dynamodb:GetShardIterator",
        "s3vectors:QueryVectors", "s3vectors:GetVectors",
        "bedrock:InvokeModel",
        *WILDCARD_EXEMPT,
    }
    granted = {a for s in driver_statements(template)
               if s.get("Effect") == "Allow" for a in _actions(s)}
    assert granted == expected, (
        f"gained: {sorted(granted - expected)}  "
        f"lost: {sorted(expected - granted)}")


def test_the_only_wildcard_resource_is_the_pinned_xray_exemption(template):
    """Same rule as the internet-facing role, same allowlist object.

    Imported rather than restated: two copies of an exemption are two places to
    widen it, and `test_query_fn_iam.py` pins the copy.
    """
    offenders = [(_actions(s), _resources(s)) for s in driver_statements(template)
                 if s.get("Effect") == "Allow" and "*" in _resources(s)
                 and not set(_actions(s)) <= WILDCARD_EXEMPT]
    assert offenders == [], f"wildcard resources on LoadDriverFn: {offenders}"


def test_the_role_attaches_only_the_managed_policies_we_expect(template):
    """The M04 finding on QueryFn, which this role did not inherit.

    Every other assertion in this file walks `AWS::IAM::Policy` resources and
    never looks at `ManagedPolicyArns`, so attaching a managed policy was the
    one way to widen this role without tripping any of them —
    `AdministratorAccess` would have read identically to all of it, on the role
    whose whole job is to dispatch ninety Bedrock-touching calls a second.

    MEASURED AS A GUARD GAP, NOT A MISCONFIGURATION: the synthesised role today
    carries only the basic execution role. security-reviewer, M06.
    """
    role_id = _function(template)["Properties"]["Role"]["Fn::GetAtt"][0]
    managed = template["Resources"][role_id]["Properties"].get(
        "ManagedPolicyArns", [])
    names = sorted(
        str(m["Fn::Join"][1][-1] if isinstance(m, dict) else m) for m in managed)
    assert names == [":iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"], \
        names


# ------------------------------------------------------------- the instrument
def test_tracing_is_active(template):
    """SPEC/06 defines the measured interval as the one carried on the per-node
    retrieval span. Without ACTIVE tracing there is no daemon, every subsegment
    goes nowhere, and the report's span status reads `off` for every call —
    honest, and not a measurement of anything."""
    assert _function(template)["Properties"]["TracingConfig"]["Mode"] == "Active"


def test_the_driver_is_not_reachable_by_an_event(template):
    """No trigger, no function URL, no API route, no permission for a service
    to invoke it. `make tier-disposition` calls it and nothing else does — a
    load generator with an event source is an outage waiting for a bad rule."""
    fn_id = next(k for k, r in template["Resources"].items()
                 if r["Type"] == "AWS::Lambda::Function"
                 and r["Properties"].get("Handler") == HANDLER)
    for res in template["Resources"].values():
        if res["Type"] in ("AWS::Lambda::Permission",
                           "AWS::Lambda::EventSourceMapping",
                           "AWS::Lambda::Url"):
            target = _flat(res["Properties"].get("FunctionName"))
            assert fn_id not in target, f"{res['Type']} targets the load driver"
        if res["Type"] == "AWS::Events::Rule":
            assert fn_id not in _flat(res["Properties"].get("Targets", [])), \
                "an EventBridge rule invokes the load driver"
