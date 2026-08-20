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
    """botocore's shape, minimally: the handler reads `.response` for the code.

    `Error.Code` defaults to ValidationError because that is what
    CloudFormation actually returns for a missing stack; cases that need a
    different code pass one.
    """

    def __init__(self, message, code="ValidationError"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": str(message)}}


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


# --------------------------------------------------------------------------
# THE DELETION ROLE MUST REACH EVERY ROLE regdelta-search WRITES A POLICY ONTO
#
# Not every role NAMED regdelta-search-*. Those are different sets, and M05
# made them different: search_stack attaches the AOSS grant to the CORE
# stack's query role via `from_role_arn(..., mutable=True)`, which puts an
# `AWS::IAM::Policy` in the EPHEMERAL stack whose `Roles:` list resolves to
# `regdelta-core-QueryFnServiceRole…`. Deleting it calls `iam:DeleteRolePolicy`
# against that role, and the prefix grant does not match — so
# `DeleteStack(RoleARN=deletion_role)` takes AccessDenied and the stack sticks
# in DELETE_FAILED with the collection billing.
#
# Invisible to the SPEC/05 Done-when: `make down` is `cdk destroy` under the
# bootstrap AdministratorAccess role and always succeeds. Only the 01:00 UTC
# janitor uses the deletion role.
#
# So the assertion is the PROPERTY — every foreign role the search stack
# attaches to is covered — rather than a second copy of the prefix. Adding
# another cross-stack attachment later fails this test instead of failing at
# 01:00 UTC.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def both_templates():
    """Core and search synthesized in ONE app, as infra/app.py builds them.

    Synthesizing search alone with a literal role ARN renders the attachment as
    a plain role NAME and hides the cross-stack shape entirely; it is the
    `Fn::ImportValue` form that this test is about.
    """
    import contextlib
    import tempfile

    import aws_cdk as cdk

    sys.path.insert(0, str(ROOT / "infra"))
    sys.path.insert(0, str(ROOT / "src"))
    from core import core_stack
    from core.core_stack import RegDeltaCoreStack
    from search.search_stack import RegDeltaSearchStack

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
    env = cdk.Environment(account=ACCOUNT, region=REGION)
    with stub_layer():
        core = RegDeltaCoreStack(app, "regdelta-core", env=env)
    search = RegDeltaSearchStack(
        app, "regdelta-search", env=env, corpus_bucket=core.corpus_bucket,
        query_lambda_role_arn=core.query_lambda_role_arn)
    search.add_dependency(core)
    asm = app.synth()
    return (asm.get_stack_by_name("regdelta-core").template,
            asm.get_stack_by_name("regdelta-search").template)


def _import_names(node) -> list[str]:
    """Every Fn::ImportValue export name anywhere inside a template fragment."""
    if isinstance(node, dict):
        if "Fn::ImportValue" in node and isinstance(node["Fn::ImportValue"], str):
            return [node["Fn::ImportValue"]]
        return [n for v in node.values() for n in _import_names(v)]
    if isinstance(node, list):
        return [n for v in node for n in _import_names(v)]
    return []


def _foreign_role_imports(search_template) -> list[str]:
    """Export names of roles the search stack attaches a policy to but does not own."""
    owned = {k for k, v in search_template["Resources"].items()
             if v["Type"] == "AWS::IAM::Role"}
    # EVERY resource type that carries a `Roles:` list, not just the one the
    # stack happens to use today. A future ManagedPolicy or L1 RolePolicy
    # attached to a foreign role would otherwise pass this test vacuously and
    # produce the same 01:00-UTC DELETE_FAILED it exists to prevent.
    # eng-code-reviewer, M05.
    # TWO PROPERTY SHAPES, not one. `Policy`/`ManagedPolicy` carry a `Roles:`
    # LIST; the L1 `AWS::IAM::RolePolicy` carries a scalar `RoleName:`. Adding
    # the type to this tuple without reading its property did nothing, and the
    # test below caught exactly that.
    attaches_to_roles = ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",
                         "AWS::IAM::RolePolicy")
    out = []
    for res in search_template["Resources"].values():
        if res["Type"] not in attaches_to_roles:
            continue
        props = res["Properties"]
        entries = list(props.get("Roles") or [])
        if "RoleName" in props:
            entries.append(props["RoleName"])
        for entry in entries:
            if isinstance(entry, dict) and entry.get("Ref") in owned:
                continue  # a role this stack creates; the name prefix covers it
            out.extend(_import_names(entry))
    return out


def _exported_logical_id(core_template, export_name: str) -> str:
    """Which core resource an export names — read off core's own Outputs."""
    for out in core_template.get("Outputs", {}).values():
        if out.get("Export", {}).get("Name") == export_name:
            return out["Value"]["Fn::GetAtt"][0]
    raise AssertionError(f"{export_name} is not exported by regdelta-core")


def test_the_deletion_role_reaches_every_foreign_role_search_writes_to(both_templates):
    core_template, search_template = both_templates

    foreign = _foreign_role_imports(search_template)
    assert foreign, (
        "no cross-stack role attachment found in regdelta-search. If the AOSS "
        "grant moved back into core this test is vacuous and should go with "
        "it — a passing test over an empty set is the failure mode here.")

    deletable = set()
    for stmt in _statements_for_role(core_template,
                                     _deletion_role_id(core_template)):
        actions = (stmt["Action"] if isinstance(stmt["Action"], list)
                   else [stmt["Action"]])
        if "iam:DeleteRolePolicy" not in actions:
            continue
        resources = (stmt["Resource"] if isinstance(stmt["Resource"], list)
                     else [stmt["Resource"]])
        for r in resources:
            if isinstance(r, dict) and "Fn::GetAtt" in r:
                deletable.add(r["Fn::GetAtt"][0])

    for export_name in foreign:
        logical = _exported_logical_id(core_template, export_name)
        assert logical in deletable, (
            f"regdelta-search attaches an IAM policy to core's {logical}, but "
            f"the deletion role can only iam:DeleteRolePolicy on "
            f"{sorted(deletable)} plus the regdelta-search-* name prefix. "
            "DeleteStack under this role would land in DELETE_FAILED with the "
            "AOSS collection still billing — nightly, unattended.")


# ------------------------------------------- what security-reviewer added


def test_a_failure_to_look_is_not_a_claim_that_billing_stopped(load):
    """`billing_stopped: True` is the strongest claim this function makes.

    It used to be returned for ANY `ClientError`, which is botocore's base
    class — AccessDenied, throttling, expired credentials. Under an IAM
    regression the janitor would report the meter stopped while the collection
    billed, and SPEC/06's alarm is going to be told to trust this line.
    Only "the stack is not there" is an observation of absence.
    """
    mod, fake = load("CREATE_COMPLETE")

    def denied(StackName):
        raise _FakeClientError(
            "An error occurred (AccessDenied) when calling DescribeStacks",
            code="AccessDeniedException")

    fake.describe_stacks = denied
    out = mod.handler({}, None)

    assert out["status"] == "unhandled-error"
    assert out["billing_stopped"] is False
    assert "AccessDenied" in out["error"]
    assert fake.deletes == [], "issued a delete on a stack it could not read"


def test_an_absent_stack_still_reports_billing_stopped(load):
    """The narrowing must not break the one branch that may claim it."""
    mod, _fake = load(None)
    out = mod.handler({}, None)
    assert out["status"] == "already-down"
    assert out["billing_stopped"] is True


@pytest.mark.parametrize("state", ["CREATE_FAILED", "ROLLBACK_FAILED",
                                   "UPDATE_ROLLBACK_FAILED"])
def test_terminal_failed_states_are_deleted_rather_than_shrugged_at(load, state):
    """All three are terminal, leave live resources, and accept DeleteStack.

    Leaving them out sends a billing collection down the `unhandled-state`
    path every night forever — the DELETE_FAILED bug in a different status
    string. `UPDATE_ROLLBACK_FAILED` is reachable from this milestone's own
    `make fault-drop`.
    """
    mod, fake = load(state)
    out = mod.handler({}, None)
    assert out["status"] == "delete-requested", out
    assert fake.deletes == [{"StackName": "regdelta-search", "RoleARN": ROLE}]


@pytest.mark.parametrize("state", ["UPDATE_FAILED", "IMPORT_ROLLBACK_FAILED"])
def test_the_remaining_terminal_failed_states_are_deleted(load, state):
    """`UPDATE_FAILED` is reachable with `--no-rollback`. Same argument as the
    other *_FAILED states: terminal, live resources, DeleteStack is valid."""
    mod, fake = load(state)
    assert mod.handler({}, None)["status"] == "delete-requested"
    assert fake.deletes == [{"StackName": "regdelta-search", "RoleARN": ROLE}]


@pytest.mark.parametrize("state", ["UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                                   "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS"])
def test_ordinary_update_transients_are_not_unhandled(load, state):
    """Both are routine after any update. Left out of `_IN_FLIGHT` they sent a
    perfectly healthy stack down the `unhandled-state` path for a night — a
    shrug rather than a false claim, but the same family as the DELETE_FAILED
    defect."""
    mod, fake = load(state)
    out = mod.handler({}, None)
    assert out["status"] == "no-action", out
    assert fake.deletes == []


def test_a_validationerror_is_required_not_just_the_phrase(load):
    """`billing_stopped: True` is the one claim SPEC/06's alarm will trust.

    Message matching alone would let any future error whose prose happens to
    contain "does not exist" reach the fail-open branch. The structured error
    code is AND-ed with it.
    """
    mod, fake = load("CREATE_COMPLETE")

    def throttled(StackName):
        raise _FakeClientError(
            "Rate exceeded; the requested throughput does not exist yet",
            code="Throttling")

    fake.describe_stacks = throttled
    out = mod.handler({}, None)
    assert out["status"] == "unhandled-error", out
    assert out["billing_stopped"] is False


def test_the_foreign_role_walk_sees_every_type_that_attaches_to_a_role():
    """Directly, against a hand-built template.

    `test_the_deletion_role_reaches_every_foreign_role_search_writes_to` runs
    against the REAL search stack, which today creates only `AWS::IAM::Policy`
    — so narrowing this walk back to that one type changes nothing there and
    the mutation survives. It would stop being vacuous the day someone adds a
    ManagedPolicy, which is exactly when a missed foreign role becomes a
    01:00-UTC DELETE_FAILED. Pinned here instead.
    """
    template = {"Resources": {
        "OwnRole": {"Type": "AWS::IAM::Role", "Properties": {}},
        "OwnPolicy": {"Type": "AWS::IAM::Policy",
                      "Properties": {"Roles": [{"Ref": "OwnRole"}]}},
        "ForeignInline": {
            "Type": "AWS::IAM::Policy",
            "Properties": {"Roles": [{"Fn::ImportValue": "other:InlineRole"}]}},
        "ForeignManaged": {
            "Type": "AWS::IAM::ManagedPolicy",
            "Properties": {"Roles": [{"Fn::ImportValue": "other:ManagedRole"}]}},
        "ForeignL1": {
            "Type": "AWS::IAM::RolePolicy",
            "Properties": {"RoleName": {"Fn::ImportValue": "other:L1Role"}}},
    }}
    found = set(_foreign_role_imports(template))
    assert found == {"other:InlineRole", "other:ManagedRole", "other:L1Role"}, (
        f"the walk missed a role-attaching resource type: {found}")
