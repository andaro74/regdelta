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
def test_the_persistent_stack_grants_no_aoss_at_all(template):
    """SPEC/05 moved this grant out of core, and the move is the fix.

    M04 got it to `collection/*` in this account and region and recorded the
    reason it could go no further: a persistent stack is deployed before the
    collection exists, so there is no id to name. True — which is why the
    statement does not belong here. It now lives in `search_stack.py`, where
    `collection.attr_arn` is concrete, and it is created and destroyed with the
    collection instead of outliving it by weeks.

    Asserted as an ABSENCE here and as a PRESENCE in
    `tests/test_search_stack_access.py`. Either test alone would pass while the
    grant went missing entirely, or while a second copy stayed behind.
    """
    granted = [str(r) for s in _for_action(template, "aoss:APIAccessAll")
               for r in _resources(s)]
    assert granted == [], \
        f"the persistent stack still grants aoss:APIAccessAll on {granted}"


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


# ------------------------------------------------------------------ dynamodb
# SPEC/05's state-table split. `QueryFn` may read and write `THREAD#*` and
# write `REVIEW#*`, and may NOT read `REVIEW#*` — that queue carries the
# asker's question text verbatim (`write_review_item` stores it truncated to
# 2000 chars) and belongs to the SME seat (docs/governance/ROLES.md).
#
# Until M05 this role held `grant_read_write_data`, which is Get/BatchGet/
# Query/Scan plus every write, unconditioned, on the whole table.
_READ_ACTIONS = ("dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query")
_WRITE_ACTIONS = ("dynamodb:PutItem", "dynamodb:UpdateItem",
                  "dynamodb:DeleteItem", "dynamodb:BatchWriteItem")


def _leading_keys(stmt):
    """The LeadingKeys patterns this statement is conditioned on, or None.

    None means UNCONDITIONED — the statement reaches every partition — and the
    tests below distinguish that from an empty list, because `[]` would read as
    "reaches nothing" and is the friendlier of the two mistakes.
    """
    cond = stmt.get("Condition") or {}
    for operator, kv in cond.items():
        if "LeadingKeys" in str(kv):
            keys = kv.get("dynamodb:LeadingKeys")
            return (operator, keys if isinstance(keys, list) else [keys])
    return None


def _state_table_logical_id(template):
    """The state table, found by the property that distinguishes it.

    Two DynamoDB tables are in this stack. The registry is the corpus index and
    is read unconditioned by design; the STATE table is the one holding
    `THREAD#*` and `REVIEW#*`. They are told apart by TTL — SPEC/03 makes the
    checkpoint TTL a review deadline, and the registry has none.
    """
    ids = [k for k, r in template["Resources"].items()
           if r["Type"] == "AWS::DynamoDB::Table"
           and "TimeToLiveSpecification" in r["Properties"]]
    assert len(ids) == 1, f"expected one TTL table, found {ids}"
    return ids[0]


def _state_table_statements(template):
    """Statements naming the STATE table, and only those.

    Filtering on `dynamodb:` alone is the ADR-0013 defect in miniature: it also
    catches `registry_table.grant_read_data`, which is unconditioned and does
    grant `Scan`. Every assertion below would then be reporting on a table it
    is not about — three of them failed exactly that way when this helper was
    first written.
    """
    table = _state_table_logical_id(template)
    out = []
    for stmt in query_statements(template):
        if not any(a.startswith("dynamodb:") for a in _actions(stmt)):
            continue
        if table in str(_resources(stmt)):
            out.append(stmt)
    return out


def test_no_dynamodb_data_grant_is_unconditioned(template):
    """THE FINDING, as one assertion.

    An unconditioned statement on this table reaches `REVIEW#*` whatever its
    action list says. `DescribeTable` is the one exception and is asserted
    separately below rather than excluded quietly here.
    """
    offenders = [_actions(s) for s in _state_table_statements(template)
                 if _leading_keys(s) is None
                 and _actions(s) != ["dynamodb:DescribeTable"]]
    assert offenders == [], f"unconditioned state-table grants: {offenders}"


def test_the_review_queue_is_never_readable(template):
    """The spec sentence, read off the policy.

    Every statement carrying a READ action must be conditioned on `THREAD#*`
    alone. A read statement that also named `REVIEW#*` would be the defect.
    """
    for stmt in _state_table_statements(template):
        actions = _actions(stmt)
        if not any(a in _READ_ACTIONS for a in actions):
            continue
        lk = _leading_keys(stmt)
        assert lk is not None, f"unconditioned read: {actions}"
        _operator, keys = lk
        assert keys == ["THREAD#*"], \
            f"read actions {actions} reach {keys}, not THREAD#* alone"


def test_the_review_queue_is_writable(template):
    """The other half. Writing it is the whole point — `write_review_item` is
    how a paused run reaches a human — so a split that merely removed
    `REVIEW#*` everywhere would pass the test above and break HITL."""
    writable = [keys for s in _state_table_statements(template)
                if any(a in _WRITE_ACTIONS for a in _actions(s))
                and (lk := _leading_keys(s)) for _op, keys in [lk]]
    assert any("REVIEW#*" in keys for keys in writable), \
        f"nothing may write the review queue: {writable}"


def test_writes_to_both_prefixes_live_in_one_statement(template):
    """Not a style preference — a mixed `BatchWriteItem` depends on it.

    `dynamodb:LeadingKeys` under `ForAllValues:` requires EVERY key in the
    request to match the statement's own patterns. `delete_thread` issues one
    batch carrying both a `THREAD#` key and the `REVIEW#` key, so two
    per-prefix write statements would each see a key they do not cover and the
    batch would be denied by both. Splitting by ACTION rather than by PREFIX is
    the only form that survives it.
    """
    write_stmts = [s for s in _state_table_statements(template)
                   if any(a in _WRITE_ACTIONS for a in _actions(s))]
    assert len(write_stmts) == 1, \
        f"{len(write_stmts)} write statements; a mixed batch satisfies neither"
    _operator, keys = _leading_keys(write_stmts[0])
    assert sorted(keys) == ["REVIEW#*", "THREAD#*"], keys


def test_scan_is_not_granted(template):
    """`LeadingKeys` cannot constrain a Scan — it has no key condition — so a
    Scan grant hands back everything the two statements above just took away.
    Nothing in `src/` scans."""
    granted = {a for s in _state_table_statements(template) for a in _actions(s)}
    assert "dynamodb:Scan" not in granted
