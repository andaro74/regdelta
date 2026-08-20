"""The nightly OCU guard, and what it is allowed to claim.

The janitor is the only thing standing between a forgotten `make up` and
~$175/month. It runs unattended at 01:00 UTC, nobody reads its return value,
and its failure mode is silence — which is why every assertion here is about
what it SAYS as much as what it does.

ADR-0013 governs the statuses: an instrument reads the field that describes its
own claim. This function cannot watch an AOSS collection finish deleting inside
its two-minute timeout, so `delete-requested` is the strongest honest thing it
can say about a delete it just issued, and `billing_stopped` is true in exactly
one branch — the one that OBSERVED the stack was gone.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JANITOR = ROOT / "infra" / "lambdas" / "janitor"

ROLE = "arn:aws:iam::111122223333:role/regdelta-core-SearchStackDeletionRole-XYZ"


class _FakeClientError(Exception):
    pass


class _FakeCfn:
    """Only the two calls the handler makes, plus a record of how."""

    class exceptions:  # noqa: N801 - mirrors botocore's client.exceptions
        ClientError = _FakeClientError

    def __init__(self, state=None):
        self.state = state
        self.deletes: list[dict] = []

    def describe_stacks(self, StackName):
        if self.state is None:
            raise _FakeClientError("does not exist")
        return {"Stacks": [{"StackStatus": self.state}]}

    def delete_stack(self, **kwargs):
        self.deletes.append(kwargs)


@pytest.fixture
def load(monkeypatch):
    """Import the handler fresh with a stubbed boto3 client.

    Module-level: it reads both environment variables and builds the client at
    import, so each case needs its own import.
    """
    def _load(state):
        fake = _FakeCfn(state)
        monkeypatch.setenv("SEARCH_STACK_NAME", "regdelta-search")
        monkeypatch.setenv("SEARCH_CFN_ROLE_ARN", ROLE)
        sys.path.insert(0, str(JANITOR))
        try:
            import boto3
            monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
            sys.modules.pop("handler", None)
            mod = importlib.import_module("handler")
        finally:
            sys.path.remove(str(JANITOR))
        return mod, fake
    return _load


# --------------------------------------------------------------- the delete
def test_the_delete_passes_the_dedicated_role(load):
    """THE FIX. `delete_stack` with no RoleARN falls back to whatever role the
    stack was created with — the CDK bootstrap execution role, which carries
    AdministratorAccess. The nightly unattended path should not inherit it."""
    mod, fake = load("CREATE_COMPLETE")
    out = mod.handler({}, None)
    assert fake.deletes == [{"StackName": "regdelta-search", "RoleARN": ROLE}]
    assert out["status"] == "delete-requested"


def test_a_failed_delete_is_retried_rather_than_reported_as_no_action(load):
    """The defect that made the guard useless exactly when it was needed.

    The old test was `state.endswith("_COMPLETE") and not
    state.startswith("DELETE")`, so DELETE_FAILED — a stack whose collection is
    still there and still billing — returned `no-action`. Nightly. Forever.
    """
    mod, fake = load("DELETE_FAILED")
    out = mod.handler({}, None)
    assert len(fake.deletes) == 1, "a failed delete was not retried"
    assert out["status"] == "delete-requested"
    assert out["retry_of_failed"] is True, \
        "a retry must be distinguishable from a first attempt in the logs"


def test_a_delete_already_in_flight_is_left_alone(load):
    mod, fake = load("DELETE_IN_PROGRESS")
    out = mod.handler({}, None)
    assert fake.deletes == []
    assert out["status"] == "no-action"


def test_an_unrecognised_state_says_so_instead_of_no_action(load):
    """`no-action` on a stack that exists reads as "nothing to do". For a
    state this function does not know, the truth is "I do not know whether
    this is billing", and the status has to be able to say it."""
    mod, fake = load("REVIEW_IN_PROGRESS")
    out = mod.handler({}, None)
    assert fake.deletes == []
    assert out["status"] == "unhandled-state"
    assert out["billing_stopped"] is False


# ---------------------------------------------------------------- the claim
def test_only_an_observed_absence_claims_billing_has_stopped(load):
    """ADR-0013, as one assertion over every branch.

    `billing_stopped` is a claim about an AOSS collection. Only the branch that
    found no stack at all has evidence for it; a delete this run REQUESTED
    takes minutes to reach the collection and this function has two.
    """
    for state, expected in [(None, True),
                            ("CREATE_COMPLETE", False),
                            ("DELETE_FAILED", False),
                            ("DELETE_IN_PROGRESS", False),
                            ("REVIEW_IN_PROGRESS", False)]:
        mod, _ = load(state)
        out = mod.handler({}, None)
        assert out["billing_stopped"] is expected, f"{state} -> {out}"


def test_no_status_says_the_stack_was_deleted(load):
    """Wording is the interface here — a human reads these in CloudWatch.

    `delete-initiated` was the old wording and it reads as an accomplished
    fact. Nothing this function returns may claim the deletion happened,
    because nothing it does establishes that.
    """
    for state in (None, "CREATE_COMPLETE", "DELETE_FAILED", "DELETE_IN_PROGRESS"):
        mod, _ = load(state)
        status = mod.handler({}, None)["status"]
        assert "initiated" not in status and status != "deleted", status


def test_every_run_logs_one_structured_line(load, capsys):
    """EventBridge discards the return value, so until this printed, every
    status above was written for a reader who did not exist. SPEC/06's alarm
    matches on it."""
    mod, _ = load("CREATE_COMPLETE")
    mod.handler({}, None)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["stack"] == "regdelta-search"
    assert line["janitor"]["status"] == "delete-requested"


def test_the_role_arn_is_required_rather_than_defaulted(monkeypatch):
    """A missing SEARCH_CFN_ROLE_ARN must fail at import, loudly.

    Defaulting to None would make `delete_stack` fall back to the stack's
    creation role and silently restore the admin path this change removed —
    with every test above still passing.
    """
    monkeypatch.setenv("SEARCH_STACK_NAME", "regdelta-search")
    monkeypatch.delenv("SEARCH_CFN_ROLE_ARN", raising=False)
    sys.path.insert(0, str(JANITOR))
    try:
        import boto3
        monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeCfn(None))
        sys.modules.pop("handler", None)
        with pytest.raises(KeyError):
            importlib.import_module("handler")
    finally:
        sys.path.remove(str(JANITOR))
        sys.modules.pop("handler", None)


# ---------------------------------------------------------------- the policy
# The handler above can only pass a role the stack actually granted it. These
# read the synthesized template, because that pairing is the half of the fix
# that lives in CDK and a handler test cannot see it.
aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ACCOUNT, REGION = "111122223333", "us-west-2"


@pytest.fixture(scope="module")
def template():
    import contextlib
    import tempfile

    import aws_cdk as cdk

    sys.path.insert(0, str(ROOT / "infra"))
    sys.path.insert(0, str(ROOT / "src"))
    from core import core_stack
    from core.core_stack import RegDeltaCoreStack

    @contextlib.contextmanager
    def stub_layer():
        original = core_stack.LAYER_SRC
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "python").mkdir()
            core_stack.LAYER_SRC = Path(tmp)
            try:
                yield
            finally:
                core_stack.LAYER_SRC = original

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core",
                          env=cdk.Environment(account=ACCOUNT, region=REGION))
    return app.synth().get_stack_by_name("regdelta-core").template


def _janitor_fn(template):
    return next(r for r in template["Resources"].values()
                if r["Type"] == "AWS::Lambda::Function"
                and r["Properties"].get("Handler") == "handler.handler")


def _deletion_role_id(template):
    """The deletion role, found by its trust policy rather than by its name.

    It is the only role in this stack CloudFormation itself may assume; every
    other one is a Lambda execution role. Matching on the logical id would pin
    a CDK construct id instead of the property that makes this role what it is.
    """
    ids = []
    for name, res in template["Resources"].items():
        if res["Type"] != "AWS::IAM::Role":
            continue
        for stmt in res["Properties"]["AssumeRolePolicyDocument"]["Statement"]:
            if stmt.get("Principal", {}).get("Service") == "cloudformation.amazonaws.com":
                ids.append(name)
    assert len(ids) == 1, f"expected one CloudFormation-assumable role, got {ids}"
    return ids[0]


def _statements_for_role(template, role_id):
    out = []
    res = template["Resources"][role_id]
    for policy in res["Properties"].get("Policies", []):
        out.extend(policy["PolicyDocument"]["Statement"])
    for other in template["Resources"].values():
        if other["Type"] != "AWS::IAM::Policy":
            continue
        if role_id in [r.get("Ref") for r in other["Properties"].get("Roles", [])]:
            out.extend(other["Properties"]["PolicyDocument"]["Statement"])
    return out


def test_the_janitor_passes_the_role_the_stack_granted_it(template):
    """One ARN, referenced twice — not two strings kept in step by hand.

    The handler reads `SEARCH_CFN_ROLE_ARN` and calls `delete_stack(RoleARN=...)`
    with it; this stack grants `iam:PassRole` on a role ARN. If those can drift,
    the failure is an AccessDenied at 01:00 UTC on a stack nobody is watching.
    """
    fn = _janitor_fn(template)
    env_arn = fn["Properties"]["Environment"]["Variables"]["SEARCH_CFN_ROLE_ARN"]

    role_id = _janitor_fn(template)["Properties"]["Role"]["Fn::GetAtt"][0]
    passroles = [s for s in _statements_for_role(template, role_id)
                 if "iam:PassRole" in (s["Action"] if isinstance(s["Action"], list)
                                       else [s["Action"]])]
    assert len(passroles) == 1, f"expected exactly one PassRole grant: {passroles}"
    assert passroles[0]["Resource"] == env_arn, \
        f"PassRole grants {passroles[0]['Resource']}, handler passes {env_arn}"


def test_the_deletion_role_cannot_create_anything(template):
    """It is a DELETION role and the action list is the whole guarantee.

    A Create* here would make it a general-purpose provisioning role that
    happens to be named for deletion, and it is reachable by an unattended
    nightly Lambda.
    """
    actions = [a for s in _statements_for_role(template, _deletion_role_id(template))
               for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
    creates = [a for a in actions if ":Create" in a or ":Put" in a or ":Update" in a]
    assert creates == [], f"deletion role can create or mutate: {creates}"


def test_the_deletion_role_cannot_read_documents(template):
    """`aoss:APIAccessAll` is the data-plane grant. Deleting a collection never
    needs it, and this role runs unattended against the index built from the
    corpus."""
    actions = [a for s in _statements_for_role(template, _deletion_role_id(template))
               for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
    assert "aoss:APIAccessAll" not in actions


def test_the_deletion_role_can_invoke_the_custom_resource_provider(template):
    """The Custom::Trigger's DeletionPolicy is Delete, so CloudFormation
    invokes the provider function with RequestType=Delete using this role.
    Without `lambda:InvokeFunction` the stack sticks in DELETE_FAILED on the
    custom resource — which is the shape the whole role exists to prevent, and
    the one a test of the action list would otherwise never notice."""
    actions = [a for s in _statements_for_role(template, _deletion_role_id(template))
               for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
    assert "lambda:InvokeFunction" in actions
