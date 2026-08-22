"""The eval gate's OIDC role: what it may do, and who may become it.

SPEC/07 item 2, as amended by the PM seat on 2026-08-21
(`milestones/M07/spec07-oidc-amendment.md`): "permissions = read the registry
table for the corpus fingerprint, and nothing else". The original clause said
"invoke staging API only", which is not implementable — the HttpApi has no
authorizer and `run_evals.ask()` sends an unsigned POST, so there is nothing to
grant.

Two dangers, and one test each:

  the TRUST policy is who may assume it. An omitted `aud` condition lets any
  GitHub repository in the world assume the role; a `sub` of `repo:owner/name:*`
  lets any ref in this repo do it. Both are the common shape in published
  examples and neither fails visibly.

  the PERMISSION policy is what it may then do. `grant_read_data` would have
  been the one-liner and would have granted six actions across every index.

The permission is derived from the code that spends it, not asserted beside it
— see `test_the_grant_matches_what_the_fingerprint_actually_calls`. ADR-0013:
an instrument reads the field that describes its own claim.
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

import aws_cdk as cdk
from aws_cdk.assertions import Template

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))
sys.path.insert(0, str(ROOT / "src"))

ROLE_NAME = "regdelta-ci-eval"
OIDC_HOST = "token.actions.githubusercontent.com"


@pytest.fixture(scope="module")
def template():
    """The core stack's TEMPLATE, synthesised with the layer stubbed.

    The stub is not optional convenience. Without it these tests read
    build/lambda-layer, a `make layer` artifact that is not committed: they
    passed on the machine that wrote them and produced nine
    "build/lambda-layer does not exist" errors the first time CI ran them, on
    2026-08-22, after the milestone had been calling the suite green. Nothing
    here asserts anything about the layer's contents — only the shape of an IAM
    role — so the artifact must not be reachable at all. See tests/conftest.py.
    """
    from conftest import stub_layer
    from core.core_stack import RegDeltaCoreStack

    with stub_layer():
        app = cdk.App()
        stack = RegDeltaCoreStack(
            app, "regdelta-core",
            env=cdk.Environment(account="111111111111", region="us-west-2"))
        return Template.from_stack(stack)


@pytest.fixture(scope="module")
def role(template):
    roles = [r for r in template.find_resources("AWS::IAM::Role").values()
             if r["Properties"].get("RoleName") == ROLE_NAME]
    assert len(roles) == 1, f"expected exactly one {ROLE_NAME} role, got {len(roles)}"
    return roles[0]


# --------------------------------------------------------------------------
# Who may assume it
# --------------------------------------------------------------------------

def test_it_is_assumed_by_web_identity_and_never_by_a_user_or_key(role):
    """No long-lived credential exists to leak, which is the whole reason for
    OIDC. A role that can also be assumed by an IAM user reintroduces one."""
    statements = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert len(statements) == 1
    principal = statements[0]["Principal"]
    assert set(principal) == {"Federated"}, \
        f"trust policy admits a non-federated principal: {principal}"
    assert statements[0]["Action"] == "sts:AssumeRoleWithWebIdentity"


def test_the_audience_claim_is_pinned_to_sts(role):
    """WITHOUT THIS, ANY GITHUB REPOSITORY IN THE WORLD CAN ASSUME THE ROLE.
    The aud claim is what binds the token to STS rather than to some other
    consumer, and it is the most common omission in a hand-written GitHub OIDC
    trust policy — it fails open and it fails silently."""
    cond = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]
    assert cond["StringEquals"][f"{OIDC_HOST}:aud"] == "sts.amazonaws.com"


def test_the_subject_claim_is_scoped_to_the_event_not_just_the_repo(role):
    """`repo:andaro74/regdelta:*` — the shape most examples use — would let ANY
    ref in this repo assume the role, including a branch pushed by anyone who
    ever gets write access. evals.yml triggers on `pull_request` alone."""
    cond = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]
    sub = cond["StringEquals"][f"{OIDC_HOST}:sub"]
    assert sub == "repo:andaro74/regdelta:pull_request", sub
    assert "*" not in sub, "a wildcard subject admits every ref in the repo"
    # NARROWED to the sub key. It read `"StringLike" not in cond`, which would
    # have blocked adding a legitimate StringLike on `job_workflow_ref` — a
    # test forbidding a tightening. security-reviewer, M07 L1.
    assert f"{OIDC_HOST}:sub" not in cond.get("StringLike", {}), \
        "StringLike on the sub claim is how a wildcard gets in by the back door"


def test_the_repository_is_pinned_by_id_and_not_only_by_name(role):
    """`andaro74/regdelta` is a personal-account path. If the account is
    renamed or the repo deleted, whoever registers that owner/name mints a
    token with a byte-identical `sub` and `aud`. The numeric id cannot be
    re-registered. security-reviewer, M07 L1."""
    cond = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]
    repo_id = cond["StringEquals"].get(f"{OIDC_HOST}:repository_id")
    assert repo_id == "1322516232", (
        f"repository_id is {repo_id!r}; the sub claim alone is name-bound and "
        f"survives a rename by someone else")


def test_the_trust_names_this_accounts_provider(role):
    """Referenced, not created: one provider per URL already exists in the
    account, so creating a second fails the deploy with EntityAlreadyExists —
    on the stack that holds the corpus."""
    federated = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0][
        "Principal"]["Federated"]
    assert OIDC_HOST in json.dumps(federated)


def test_no_oidc_provider_resource_is_created(template):
    template.resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 0)
    template.resource_count_is("AWS::IAM::OIDCProvider", 0)


# --------------------------------------------------------------------------
# What it may do
# --------------------------------------------------------------------------

def _ci_eval_statements(template):
    out = []
    for policy in template.find_resources("AWS::IAM::Policy").values():
        roles = json.dumps(policy["Properties"].get("Roles", []))
        if "CiEvalRole" not in roles:
            continue
        out += policy["Properties"]["PolicyDocument"]["Statement"]
    return out


def test_it_holds_exactly_one_statement_granting_exactly_one_action(template):
    statements = _ci_eval_statements(template)
    assert len(statements) == 1, \
        f"the CI role has grown extra statements: {statements}"
    actions = statements[0]["Action"]
    actions = [actions] if isinstance(actions, str) else actions
    assert actions == ["dynamodb:Scan"], (
        f"granted {actions}. `grant_read_data` would add GetItem, BatchGetItem, "
        f"Query, ConditionCheckItem and DescribeTable across every index; the "
        f"fingerprint calls one of them.")


def test_the_grant_reaches_the_registry_table_and_no_index(template):
    resources = _ci_eval_statements(template)[0]["Resource"]
    resources = [resources] if isinstance(resources, dict | str) else resources
    assert len(resources) == 1
    rendered = json.dumps(resources[0])
    assert "RegistryTable" in rendered, rendered
    assert "index" not in rendered.lower(), \
        "the grant reaches an index; scan on the table is all that is needed"


def test_it_grants_nothing_for_the_api(template):
    """NOT AN OMISSION, and it is worth a test saying so. The HttpApi has no
    authorizer and run_evals.ask() sends an unsigned POST, so invoking the
    staging API needs no IAM identity. SPEC/07 item 2 states this after the
    PM-seat amendment; a future reader adding an execute-api grant to "fix" the
    role should land here first."""
    rendered = json.dumps(_ci_eval_statements(template))
    for service in ("execute-api", "apigateway", "lambda:", "s3:", "bedrock"):
        assert service not in rendered, f"unexpected {service} grant on the CI role"


def test_the_grant_matches_what_the_fingerprint_actually_calls():
    """THE ONE THAT IS NOT A RESTATEMENT. Drives the real code path with a fake
    table and records which DynamoDB operations it uses, so the grant above is
    derived from the caller rather than asserted next to it.

    Sufficiency against live IAM is NOT established here — that is settled the
    first time the gate runs on a PR, and until then this says only that the
    grant and the caller agree about which API is spent."""
    from shared import corpus

    calls = []

    class FakeTable:
        def scan(self, **kwargs):
            calls.append(("scan", tuple(sorted(kwargs))))
            return {"Items": [{"pk": "DOC#90 FR 4628", "pub_date": "2025-01-16"}]}

        def __getattr__(self, name):        # any other API is a failure
            calls.append((name, ()))
            raise AssertionError(
                f"fingerprint() called dynamodb:{name}, which the CI role does "
                f"not grant. Either narrow the caller or widen the grant "
                f"deliberately — do not discover this as an AccessDenied in CI.")

    result = corpus.fingerprint(table=FakeTable())
    assert result["available"] is True, result
    assert [c[0] for c in calls] == ["scan"], calls
