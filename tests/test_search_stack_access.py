"""The AOSS data-access policy is the whole of AOSS authorization.

An IAM principal holding `aoss:APIAccessAll` still gets 403 unless it is named
in the collection's data access policy — so this policy is not defence in
depth, it is the door. The dev-principal opt-in added for M02 widens it, and a
widening that defaults to on, or that quietly grants more than asked, is worth
a test rather than a comment.
"""
import json

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

DEV_ARN = "arn:aws:iam::111122223333:user/someone"
QUERY_ROLE = "arn:aws:iam::111122223333:role/QueryFn"


def synth(context: dict | None = None) -> dict:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent / "infra"))
    import aws_cdk as cdk
    from aws_cdk import aws_s3 as s3
    from search.search_stack import RegDeltaSearchStack

    app = cdk.App(context=context or {})
    host = cdk.Stack(app, "host", env=cdk.Environment(
        account="111122223333", region="us-west-2"))
    bucket = s3.Bucket(host, "Corpus")
    RegDeltaSearchStack(
        app, "regdelta-search", corpus_bucket=bucket,
        query_lambda_role_arn=QUERY_ROLE,
        env=cdk.Environment(account="111122223333", region="us-west-2"))
    return app.synth().get_stack_by_name("regdelta-search").template


def access_statements(template: dict) -> list[dict]:
    """Every statement in the data-access policy.

    The reindex role's ARN is a CFN token, so the policy synthesises as an
    Fn::Join of literals and Fn::GetAtt fragments rather than a plain string.
    Tokens are rendered as a placeholder — what matters here is the LITERAL
    principals, since those are the ones a reader of the template can widen
    without noticing.
    """
    for res in template["Resources"].values():
        if res["Type"] != "AWS::OpenSearchServerless::AccessPolicy":
            continue
        policy = res["Properties"]["Policy"]
        if not isinstance(policy, str):
            policy = "".join(p if isinstance(p, str) else "<cfn-token>"
                             for p in policy["Fn::Join"][1])
        return json.loads(policy)
    raise AssertionError("no data access policy in the template")


def access_principals(template: dict) -> list[str]:
    """Every principal named anywhere in the policy, across all statements.

    Was `statements[0]["Principal"]` until the dev principal moved to its own
    read-only statement (security review M1). Reading only the first statement
    would now report the operator as ungranted — a test that passes because it
    stopped looking.
    """
    return [p for s in access_statements(template) for p in s["Principal"]]


def permissions_for(template: dict, principal: str) -> set[str]:
    """The union of permissions any statement grants to `principal`."""
    return {perm
            for s in access_statements(template) if principal in s["Principal"]
            for rule in s["Rules"] for perm in rule["Permission"]}


def test_the_dev_principal_is_opt_in(monkeypatch):
    """Default deploy grants the two Lambda roles and nothing else.

    If this ever defaults to on, every deploy of the hot tier hands query and
    WRITE access to whoever last ran `aws configure` — including in CI.
    """
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    principals = access_principals(synth())
    assert QUERY_ROLE in principals
    assert not any("user/" in p for p in principals)


def test_the_dev_principal_is_granted_when_asked_for(monkeypatch):
    """Without this, SPEC/02's AOSS run cannot be executed at all: the harness
    calls router.retrieve() in-process by design, so it runs as the operator's
    own principal, which no Lambda role covers."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    principals = access_principals(synth({"devPrincipalArn": DEV_ARN}))
    assert DEV_ARN in principals
    assert QUERY_ROLE in principals


def test_it_grants_exactly_the_one_principal_asked_for(monkeypatch):
    """No account root, no wildcard. The Lambda statement still grants aoss:*
    (the read/write split is SPEC/05), so an over-broad principal list there is
    write access to the index."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    principals = access_principals(synth({"devPrincipalArn": DEV_ARN}))
    assert len(principals) == 3
    assert "*" not in principals
    assert not any(p.endswith(":root") for p in principals)


def test_the_operator_gets_read_only_and_never_aoss_star(monkeypatch):
    """Security review M1. The eval harness only ever queries.

    An earlier version appended the operator to the same Principal list that
    carries the collection-wide and index-wide `aoss:*` rules, so running a
    read-only harness required handing a human principal DeleteIndex and
    WriteDocument on the index built from the corpus — and deferred narrowing it
    to the SPEC/05 write/read split. A *new* widening must not ride out on an
    existing TODO, and read-only here needed no split, only its own statement.

    Asserted as an exact permission set, not a `"aoss:*" not in ...` check: a
    later edit that granted `aoss:CreateIndex` alongside the reads would pass
    the negative form while re-opening most of what this closes.
    """
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    template = synth({"devPrincipalArn": DEV_ARN})
    assert permissions_for(template, DEV_ARN) == {
        "aoss:DescribeIndex", "aoss:ReadDocument"}
    # And the Lambda roles keep theirs — this narrowed one principal, not all.
    assert "aoss:*" in permissions_for(template, QUERY_ROLE)


def test_the_operators_statement_grants_no_collection_level_access(monkeypatch):
    """Index-level reads only. A collection-level rule would carry
    CreateCollectionItems / DeleteCollectionItems, which is how a read-only
    intent turns back into index deletion by a different route."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    stmts = [s for s in access_statements(synth({"devPrincipalArn": DEV_ARN}))
             if DEV_ARN in s["Principal"]]
    assert len(stmts) == 1, "the operator should appear in exactly one statement"
    assert {r["ResourceType"] for r in stmts[0]["Rules"]} == {"index"}


def test_the_reindex_lambda_ships_the_shared_source_tree():
    """The mapping and the SigV4 client must have ONE copy. A second asset
    directory is how _EDGE_PREDICATE drifted in M01c, and a mapping that
    disagrees with the query tier makes cross-tier Jaccard measure the
    disagreement instead of retrieval."""
    template = synth()
    handlers = [r["Properties"]["Handler"] for r in template["Resources"].values()
                if r["Type"] == "AWS::Lambda::Function"]
    assert "retrieval.reindex.handler" in handlers


def lambda_env(template: dict) -> dict:
    for res in template["Resources"].values():
        if res["Type"] == "AWS::Lambda::Function" and \
                res["Properties"]["Handler"] == "retrieval.reindex.handler":
            return res["Properties"].get("Environment", {}).get("Variables", {})
    raise AssertionError("no reindex Lambda in the template")


def test_the_env_var_path_also_widens_the_policy(monkeypatch):
    """The env fallback is the one that can widen a deploy invisibly.

    `-c devPrincipalArn=` is visible in the deploy command; a leftover
    `export REGDELTA_DEV_PRINCIPAL_ARN=...` in a shell profile silently widens
    EVERY subsequent `make up`. Every other test here deletes the variable
    first, so before this one the env path was never exercised as a widening —
    they proved the CONTEXT default is empty, not the environment one.
    """
    monkeypatch.setenv("REGDELTA_DEV_PRINCIPAL_ARN", DEV_ARN)
    principals = access_principals(synth())
    assert DEV_ARN in principals, \
        "the env fallback is documented as a supported path; if it is removed, " \
        "delete it from the comment too"


@pytest.mark.parametrize("bad", [
    "arn:aws:sts::111122223333:assumed-role/Admin/session",  # what STS returns
    "arn:aws:iam::999988887777:user/someone",                # cross-account
    "arn:aws:iam::111122223333:root",                         # account root
    "*",
    "someone",
])
def test_a_principal_that_is_not_an_in_account_iam_arn_fails_synth(monkeypatch, bad):
    """Unvalidated, this string lands in a policy granting aoss:* on a collection
    whose network policy is AllowFromPublic — so a mistyped account id is corpus
    data leaving the account, one token away.

    The assumed-role form matters most: it is exactly what
    `aws sts get-caller-identity --query Arn` returns under SSO, which is what
    `make up` passes. AOSS does not match on it, and the symptom is a bare 403
    that reads like policy propagation.
    """
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    with pytest.raises(Exception, match=r"devPrincipalArn|assumed-role|account"):
        synth({"devPrincipalArn": bad})


def test_the_fault_hook_is_absent_unless_asked_for(monkeypatch):
    """REINDEX_FAULT_DROP is a deliberately deploy-breaking switch.

    reindex.py reads it from the Lambda environment, so its presence in a normal
    deploy would mean a normal deploy fails. The mirror of the devPrincipalArn
    opt-in test — and the wiring commit shipped without it.
    """
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    assert "REINDEX_FAULT_DROP" not in lambda_env(synth())


def test_the_fault_hook_reaches_the_lambda_when_asked_for(monkeypatch):
    """The hook was unit-tested and UNREACHABLE before this wiring existed: the
    stack passed only CORPUS_BUCKET and COLLECTION_ENDPOINT, so SPEC/02
    Done-when (B) had no way to be triggered on a real deploy."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    assert lambda_env(synth({"faultDrop": 3}))["REINDEX_FAULT_DROP"] == "3"


@pytest.mark.parametrize("bad", [0, -3])
def test_a_fault_drop_that_cannot_fail_a_deploy_is_rejected(monkeypatch, bad):
    """A value below 1 drops nothing and deploys normally, while the operator
    believes the fault fired — the wrong direction for evidence-gathering, since
    (B) needs a deploy that FAILED. Silence there is worse than an error."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    with pytest.raises(Exception, match="faultDrop"):
        synth({"faultDrop": bad})
