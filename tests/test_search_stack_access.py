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
    # The REINDEX role keeps aoss:* — it creates the index and writes every
    # document in it. Its ARN is a CFN token, so it reads as the placeholder
    # access_statements() substitutes. The query role does not; see below.
    assert "aoss:*" in permissions_for(template, "<cfn-token>")


def test_the_query_role_gets_read_only_too(monkeypatch):
    """Security review of the M04 IAM scoping, finding 1 — and the same
    argument as the test above, applied to the principal it exempted.

    That test narrowed the human operator and left the two Lambda roles sharing
    one `aoss:*` statement, on the SPEC/05 deferral. The query role has since
    become the only role in this account driven by ANONYMOUS requests, and
    `core_stack` scoped its IAM grant to `collection/*` explicitly citing this
    data access policy as "the control that actually admits the request".

    That citation was false while this statement granted it `aoss:*`. The
    internet-facing role could DeleteIndex and WriteDocument on the corpus index
    the answers are drawn from — corpus poisoning of cited regulatory deadlines,
    reachable from the same role that feeds untrusted Federal Register text to
    an LLM.

    It needs neither: src/retrieval/aoss_tier.py issues `_search` and `_msearch`
    and nothing else. Exact permission set, for the reason the test above gives.
    """
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    template = synth({"devPrincipalArn": DEV_ARN})
    assert permissions_for(template, QUERY_ROLE) == {
        "aoss:DescribeIndex", "aoss:ReadDocument"}


def test_the_query_role_has_no_collection_level_access(monkeypatch):
    """A collection-level rule carries CreateCollectionItems and
    DeleteCollectionItems, which is how a read-only intent turns back into index
    deletion by a different route — the same trap the operator's statement
    avoids."""
    monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)
    template = synth({"devPrincipalArn": DEV_ARN})
    for stmt in access_statements(template):
        if QUERY_ROLE not in stmt["Principal"]:
            continue
        for rule in stmt["Rules"]:
            assert rule["ResourceType"] == "index", \
                f"query role granted {rule['ResourceType']}-level access: {rule}"


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


def staged_asset_files(monkeypatch=None) -> list[str]:
    """The file list CDK actually stages for the reindex Lambda.

    Synthesised into a real assembly directory, because the asset is copied at
    synth time and the template records only a hash. Everything above reads the
    TEMPLATE, and the template cannot say whether the module is in the zip.
    """
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent / "infra"))
    import aws_cdk as cdk
    from aws_cdk import aws_s3 as s3
    from search.search_stack import RegDeltaSearchStack

    if monkeypatch is not None:
        # The same delenv every other test in this file performs. A leftover
        # export is the invisible-widening path this file documents, and here
        # an assume-role or cross-account value fails synth on an unrelated
        # ValueError — a red test about the wrong thing.
        monkeypatch.delenv("REGDELTA_DEV_PRINCIPAL_ARN", raising=False)

    app = cdk.App(outdir=tempfile.mkdtemp())
    host = cdk.Stack(app, "host", env=cdk.Environment(
        account="111122223333", region="us-west-2"))
    bucket = s3.Bucket(host, "Corpus")
    RegDeltaSearchStack(
        app, "regdelta-search", corpus_bucket=bucket,
        query_lambda_role_arn=QUERY_ROLE,
        env=cdk.Environment(account="111122223333", region="us-west-2"))
    assembly = app.synth()

    # Located through the TEMPLATE's own S3 key rather than by picking a
    # directory: the assembly stages a second asset for the CDK trigger
    # provider, and "the first asset directory" would silently be that one.
    template = assembly.get_stack_by_name("regdelta-search").template
    key = next(r["Properties"]["Code"]["S3Key"]
               for r in template["Resources"].values()
               if r["Type"] == "AWS::Lambda::Function"
               and r["Properties"]["Handler"] == "retrieval.reindex.handler")
    root = Path(assembly.directory) / f"asset.{key.removesuffix('.zip')}"
    assert root.is_dir(), f"no staged asset at {root}"
    return sorted(str(f.relative_to(root)).replace("\\", "/")
                  for f in root.rglob("*") if f.is_file())


def test_the_reindex_asset_actually_contains_the_module_it_handles(monkeypatch):
    """The deploy failed on this, and the test above passed throughout.

    "Handler is retrieval.reindex.handler" is a claim about the template; the
    Lambda needs the MODULE. Under CDK's default GLOB ignore mode the asset's
    exclude list pruned every directory under src/ and staged two files, so the
    hot tier could not come up at all: "Unable to import module
    'retrieval.reindex': No module named 'retrieval'".
    """
    files = staged_asset_files(monkeypatch)
    assert "retrieval/reindex.py" in files, files[:20]
    assert "retrieval/aoss_client.py" in files, files[:20]


def stage(tmp_path, tree: dict) -> list[str]:
    """Stage `tree` through the STACK'S OWN asset policy. Returns the file list.

    Imports ASSET_EXCLUDE and ASSET_IGNORE_MODE rather than restating them: a
    test carrying its own copy of the patterns asserts a duplicate, and stays
    green while the stack ships something else entirely.
    """
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent / "infra"))
    import aws_cdk as cdk
    from aws_cdk import aws_lambda as _lambda
    from search.search_stack import ASSET_EXCLUDE, ASSET_IGNORE_MODE

    src = tmp_path / "src"
    for rel, body in tree.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    app = cdk.App(outdir=tempfile.mkdtemp())
    stack = cdk.Stack(app, "s", env=cdk.Environment(account="111122223333",
                                                    region="us-west-2"))
    _lambda.Function(stack, "F", runtime=_lambda.Runtime.PYTHON_3_14,
                     handler="retrieval.reindex.handler",
                     code=_lambda.Code.from_asset(
                         str(src), exclude=ASSET_EXCLUDE,
                         ignore_mode=ASSET_IGNORE_MODE))
    assembly = app.synth()
    root = next(p for p in Path(assembly.directory).glob("asset.*") if p.is_dir())
    return sorted(str(f.relative_to(root)).replace("\\", "/")
                  for f in root.rglob("*") if f.is_file())


# The shapes security review finding L4 named, plus the ones the M04 review
# found this list still let through. PLANTED rather than hoped for: asserting
# over the real src/ is an assertion about whatever happens to be in the tree
# today, and it passes vacuously in a clean checkout — under the BUGGY ignore
# mode a clean src/ stages one file and leaks nothing. That is the same
# green-by-construction defect this repo keeps finding, one level down: the
# first version of this test was green for the wrong reason and would have
# stayed green against `exclude=[]`. Security review of the M04 fix.
HOSTILE_TREE = {
    "retrieval/reindex.py": "handler = 1",
    "retrieval/__init__.py": "",
    "nested/deep/deeper/mod.py": "",
    ".env": "SECRET=1",
    ".aws/credentials": "[default]",
    "retrieval/.env": "SECRET=2",
    "data/.env.local": "SECRET=3",
    "dev.env": "X=1",
    "secrets.json": "{}",
    "credentials": "no extension at all",
    "service-account.json": "{}",
    "key.p12": "",
    "keys.py/secret.txt": "a DIRECTORY whose name ends in .py",
    "retrieval/__pycache__/reindex.cpython-314.pyc": "",
}


def test_the_asset_allowlist_ships_python_and_nothing_else(tmp_path):
    """Security review L4's finding, asserted against a hostile tree.

    The list is an ALLOWLIST so it holds against whatever lands in src/ later —
    a scratch .env, a downloaded credential, a key file. Under the default
    ignore mode it did the opposite: minimatch's `*` does not match
    dot-prefixed names, so a root-level `.env` shipped from a real synth while
    the source tree did not.

    Case-insensitive on the suffix deliberately: the DOCKER and GLOB matchers
    disagree about `UPPER.PY`, so an exact `.py` comparison would report a
    source file as a leak on one platform and not the other.
    """
    leaked = [f for f in stage(tmp_path, HOSTILE_TREE)
              if not f.lower().endswith(".py")]
    assert leaked == [], f"non-Python files staged into the Lambda: {leaked}"


def test_the_allowlist_still_ships_every_module_at_every_depth(tmp_path):
    """The other half, and the half the failed deploy was missing. An allowlist
    that ships nothing also leaks nothing."""
    files = stage(tmp_path, HOSTILE_TREE)
    assert "retrieval/reindex.py" in files, files
    assert "nested/deep/deeper/mod.py" in files, files


def test_a_directory_named_like_a_module_does_not_re_include_its_subtree(tmp_path):
    """`*` excludes the DIRECTORY `keys.py`; `!**/*.py` then matches that
    directory and re-includes everything beneath it. Found by security review
    of the first fix, which shipped keys.py/secret.txt."""
    assert "keys.py/secret.txt" not in stage(tmp_path, HOSTILE_TREE)


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


# ------------------------------------------------- the query role's IAM grant
# The other half of SPEC/05's `aoss:APIAccessAll` scoping. `tests/
# test_query_fn_iam.py` asserts the persistent stack grants none; these assert
# THIS stack grants it, on the collection ARN. Split deliberately: either test
# alone passes while the grant vanishes entirely, or while a second copy is
# left behind in core.
def query_role_aoss_statements(template: dict) -> list[dict]:
    """`aoss:APIAccessAll` statements attached to the imported query role.

    Found by the role the policy is attached to, not by policy name — CDK
    derives the name from a construct path, and pinning that would make this
    test fail on a rename that changes nothing.

    MATCHED ON THE ROLE NAME, NOT THE ARN. `AWS::IAM::Policy.Roles` carries
    names; an imported role appears there as the last ARN segment
    (`"QueryFn"`), never as `arn:aws:iam::...:role/QueryFn`. Filtering on the
    ARN found nothing and reported the grant missing while the template held it
    — the same instrument-reads-the-wrong-field shape as ADR-0013, in the test
    written to check the fix.
    """
    role_name = QUERY_ROLE.rsplit("/", 1)[-1]
    out = []
    for res in template["Resources"].values():
        if res["Type"] != "AWS::IAM::Policy":
            continue
        if role_name not in res["Properties"].get("Roles", []):
            continue
        for stmt in res["Properties"]["PolicyDocument"]["Statement"]:
            actions = stmt["Action"]
            if "aoss:APIAccessAll" in (actions if isinstance(actions, list)
                                       else [actions]):
                out.append(stmt)
    return out


def test_the_query_role_is_granted_aoss_on_the_collection_arn():
    """The grant SPEC/05 asks for, on the resource SPEC/05 names.

    `Fn::GetAtt: [Collection, Arn]` is the collection ITSELF — the id AWS
    generates at creation — and not `collection/*`, which is the widest thing
    the persistent stack could say.
    """
    template = synth()
    stmts = query_role_aoss_statements(template)
    assert len(stmts) == 1, f"expected one aoss grant on the query role: {stmts}"
    assert stmts[0]["Resource"] == {"Fn::GetAtt": ["Collection", "Arn"]}, \
        stmts[0]["Resource"]


def test_the_grant_dies_with_the_collection():
    """Why it lives here rather than in core, as a property of the template.

    The statement is in an `AWS::IAM::Policy` OWNED BY THIS STACK, so
    `cdk destroy regdelta-search` removes it. In core it survived `make down`,
    leaving the one internet-facing role in the account holding AOSS reach over
    every collection here — including other projects' — until the next
    `make up`.
    """
    template = synth()
    stmts = query_role_aoss_statements(template)
    assert stmts, "the grant is not in the ephemeral stack; it cannot expire"


def test_the_query_role_gets_no_write_permission_from_iam_either():
    """IAM is the necessary half; the data-access policy above is the
    sufficient half. Both must be read-only for this role, and a test of one
    is not a test of the other."""
    template = synth()
    for stmt in query_role_aoss_statements(template):
        actions = stmt["Action"]
        actions = actions if isinstance(actions, list) else [actions]
        assert actions == ["aoss:APIAccessAll"], \
            f"the query role's IAM grant carries more than API access: {actions}"
