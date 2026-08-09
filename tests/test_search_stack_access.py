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


def access_principals(template: dict) -> list[str]:
    """The reindex role's ARN is a CFN token, so the policy synthesises as an
    Fn::Join of literals and Fn::GetAtt fragments rather than a plain string.
    Tokens are rendered as a placeholder — what matters here is the LITERAL
    principals, since those are the ones a reader of the template can widen
    without noticing."""
    for res in template["Resources"].values():
        if res["Type"] != "AWS::OpenSearchServerless::AccessPolicy":
            continue
        policy = res["Properties"]["Policy"]
        if not isinstance(policy, str):
            policy = "".join(p if isinstance(p, str) else "<cfn-token>"
                             for p in policy["Fn::Join"][1])
        return json.loads(policy)[0]["Principal"]
    raise AssertionError("no data access policy in the template")


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
    """No account root, no wildcard. The policy grants aoss:* today (the
    read/write split is SPEC/05), so an over-broad principal list here is
    write access to the index."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    principals = access_principals(synth({"devPrincipalArn": DEV_ARN}))
    assert len(principals) == 3
    assert "*" not in principals
    assert not any(p.endswith(":root") for p in principals)


def test_the_reindex_lambda_ships_the_shared_source_tree():
    """The mapping and the SigV4 client must have ONE copy. A second asset
    directory is how _EDGE_PREDICATE drifted in M01c, and a mapping that
    disagrees with the query tier makes cross-tier Jaccard measure the
    disagreement instead of retrieval."""
    template = synth()
    handlers = [r["Properties"]["Handler"] for r in template["Resources"].values()
                if r["Type"] == "AWS::Lambda::Function"]
    assert "retrieval.reindex.handler" in handlers
