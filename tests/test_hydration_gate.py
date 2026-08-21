"""The endpoint parameter is hydration's output, not the stack's (SPEC/05 #4).

The M02 deferral (milestones/M02/README.md:591): `/regdelta/search/endpoint`
was written by CloudFormation, which knows a collection exists and knows
nothing about whether an index was filled. `EndpointParam` carried no
`DependsOn` at all. So on a stack UPDATE, a Trigger failure rolled the Lambda's
environment back but not the AOSS index contents, the parameter from the
previous successful deploy survived, and `router.active_endpoint()` — which
reads only that parameter — routed to a knowingly-short index. That answers,
with citations. A scorecard can be recorded against it.

Three halves, tested here as three:

  INSIDE   `reindex.handler` retires the parameter before it touches the
           index and republishes it only after BOTH assertions pass.
  TEMPLATE the parameter is created before the Trigger and CloudFormation
           still owns it, so `cdk destroy` still takes it away.
  OUTSIDE  `evals/check_hydration.py` is what `make up` gates on, and ADR-0013
           says a guard has to be run against everything it can refuse. Every
           refusal branch is exercised below.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))


# --------------------------------------------------------------- the inside


@pytest.fixture
def reindex(monkeypatch):
    monkeypatch.setenv("CORPUS_BUCKET", "corpus")
    monkeypatch.setenv("COLLECTION_ENDPOINT",
                       "https://abc123.us-west-2.aoss.amazonaws.com")
    sys.modules.pop("retrieval.reindex", None)
    from retrieval import reindex as mod
    monkeypatch.setattr(mod, "COUNT_DEADLINE_S", 0.0)
    monkeypatch.setattr(mod, "COUNT_POLL_S", 0.0)
    monkeypatch.setattr(mod, "AUTHZ_PROPAGATION_S", 0.0)
    monkeypatch.setattr(mod, "AUTHZ_POLL_S", 0.0)
    yield mod
    sys.modules.pop("retrieval.reindex", None)


def records(n: int) -> list[dict]:
    return [{"chunk_id": f"2024-29957#{i:04d}", "text": f"body {i}",
             "citation_path": "89 FR 106064", "embedding": [0.1] * 4,
             "doc_type": "final_rule", "cfr_title": "21", "cfr_part": "101",
             "pub_date": "2024-12-27", "effective_date": "2025-04-28",
             "compliance_date": "2028-02-25"} for i in range(n)]


def journal(monkeypatch, mod, source, indexed_count, mapping_raises=False):
    """Run the handler's collaborators for their ORDER, not their effects.

    Every step appends its own name, so a test can assert that `publish`
    appears after `count` and after `mapping` rather than merely that it
    happened. Ordering is the entire property: a publish that runs before the
    assertions is exactly the bug this milestone closes, and it would pass any
    test that only checked the parameter was written.
    """
    log: list[str] = []
    sent: list[dict] = []

    def mapping(ep):
        log.append("mapping")
        if mapping_raises:
            raise RuntimeError("embedding is not a knn_vector")

    monkeypatch.setattr(mod, "iter_chunk_records", lambda b: iter(source))
    monkeypatch.setattr(mod, "_create_index",
                        lambda ep: log.append("create_index"))
    monkeypatch.setattr(mod, "_bulk",
                        lambda ep, docs: (sent.extend(docs), log.append("bulk")))
    monkeypatch.setattr(mod, "_count", lambda ep: (
        indexed_count(sent) if callable(indexed_count) else indexed_count))
    monkeypatch.setattr(mod, "_assert_knn_mapping", mapping)
    monkeypatch.setattr(mod, "_retire_endpoint",
                        lambda: (log.append("retire"), True)[1])
    monkeypatch.setattr(mod, "_publish_endpoint",
                        lambda ep: log.append(f"publish:{ep}"))
    return log, sent


def test_a_healthy_hydration_publishes_the_endpoint_last(reindex, monkeypatch):
    log, _ = journal(monkeypatch, reindex, records(600), lambda s: len(s))
    result = reindex.handler({}, None)

    assert log[0] == "retire", (
        "the parameter must be retired BEFORE _create_index, which DELETEs the "
        f"index as its opening move; order was {log}")
    assert log.index("retire") < log.index("create_index")
    assert log[-1].startswith("publish:"), (
        f"publish must be the last act, after the mapping assert; order was {log}")
    assert log.index("mapping") < len(log) - 1
    assert result["endpoint_published"]


def test_the_published_parameter_is_the_one_the_router_reads(reindex):
    """Not a fourth copy of the string.

    `router.active_endpoint()` reads `config.SSM_SEARCH_ENDPOINT`. A writer
    that names the parameter separately can disagree with its reader, and the
    disagreement looks exactly like a hot tier that is down.
    """
    from retrieval import router
    from shared import config

    src = Path(reindex.__file__).read_text(encoding="utf-8")
    assert "config.SSM_SEARCH_ENDPOINT" in src
    assert '"/regdelta/search/endpoint"' not in src, (
        "reindex.py spells the parameter name itself instead of importing the "
        "constant the router reads")
    assert router.SSM_SEARCH_ENDPOINT is config.SSM_SEARCH_ENDPOINT


@pytest.mark.parametrize("case,source,indexed,mapping_raises", [
    ("count is short", records(600), lambda s: len(s) - 1, False),
    ("index never visible", records(600), None, False),
    ("mapping is dynamic", records(600), lambda s: len(s), True),
    ("corpus is empty", [], 0, False),
])
def test_no_failure_path_publishes_an_endpoint(
        reindex, monkeypatch, case, source, indexed, mapping_raises):
    """The property that makes the gate a gate.

    Whatever went wrong, the parameter stays retired — so
    `router.active_endpoint()` returns None and retrieval answers from S3
    Vectors, which is never short, instead of from a hot tier nobody verified.
    """
    log, _ = journal(monkeypatch, reindex, source, indexed,
                     mapping_raises=mapping_raises)
    with pytest.raises(RuntimeError):
        reindex.handler({}, None)
    assert "retire" in log, f"{case}: never took the old endpoint out of service"
    assert not [x for x in log if x.startswith("publish")], (
        f"{case}: published an endpoint on a failing hydration — this is the "
        "partial-index bug, restored")


def test_the_fault_hook_cannot_publish(reindex, monkeypatch):
    """SPEC/02 (B)'s deliberate fault is a failure like any other."""
    monkeypatch.setattr(reindex, "FAULT_DROP", 3)
    log, _ = journal(monkeypatch, reindex, records(600), lambda s: len(s))
    with pytest.raises(RuntimeError, match="count mismatch"):
        reindex.handler({}, None)
    assert not [x for x in log if x.startswith("publish")]


def test_retire_tolerates_an_absent_parameter(reindex, monkeypatch):
    """`make down` leaves nothing behind, so the next `make up` finds none."""
    class NotFoundError(Exception):
        pass

    class FakeSsm:
        exceptions = type("E", (), {"ParameterNotFound": NotFoundError})

        def delete_parameter(self, Name):
            raise NotFoundError()

    monkeypatch.setattr(reindex, "_ssm_client", FakeSsm)
    assert reindex._retire_endpoint() is False


def test_retire_reports_when_one_was_there(reindex, monkeypatch):
    from shared import config

    seen = {}

    class FakeSsm:
        exceptions = type("E", (), {"ParameterNotFound": KeyError})

        def delete_parameter(self, Name):
            seen["name"] = Name

    monkeypatch.setattr(reindex, "_ssm_client", FakeSsm)
    assert reindex._retire_endpoint() is True
    assert seen["name"] == config.SSM_SEARCH_ENDPOINT


def test_publish_overwrites(reindex, monkeypatch):
    from shared import config

    seen = {}

    class FakeSsm:
        def put_parameter(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(reindex, "_ssm_client", FakeSsm)
    reindex._publish_endpoint("https://x.us-west-2.aoss.amazonaws.com")
    assert seen["Name"] == config.SSM_SEARCH_ENDPOINT
    assert seen["Value"] == "https://x.us-west-2.aoss.amazonaws.com"
    assert seen["Overwrite"] is True, (
        "without Overwrite a republish onto a parameter CloudFormation just "
        "created fails, and a healthy deploy reports a hydration failure")


# ------------------------------------------------------------- the template


aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")


def synth() -> dict:
    sys.path.insert(0, str(Path(__file__).parent.parent / "infra"))
    import aws_cdk as cdk
    from aws_cdk import aws_s3 as s3
    from search.search_stack import RegDeltaSearchStack

    app = cdk.App()
    host = cdk.Stack(app, "host", env=cdk.Environment(
        account="111122223333", region="us-west-2"))
    bucket = s3.Bucket(host, "Corpus")
    RegDeltaSearchStack(
        app, "regdelta-search", corpus_bucket=bucket,
        query_lambda_role_arn="arn:aws:iam::111122223333:role/QueryFn",
        env=cdk.Environment(account="111122223333", region="us-west-2"))
    return app.synth().get_stack_by_name("regdelta-search").template


def logical_id(template: dict, cfn_type: str) -> str:
    ids = [k for k, v in template["Resources"].items() if v["Type"] == cfn_type]
    assert len(ids) == 1, f"expected exactly one {cfn_type}, got {ids}"
    return ids[0]


def test_the_trigger_runs_after_the_parameter_exists():
    """Ordering, not decoration.

    The Lambda republishes the parameter at the end of hydration. If
    CloudFormation were still free to create it afterwards — and it was, the
    resource had no DependsOn at all — the create would land on a name the
    Lambda had just written and fail with ParameterAlreadyExists.
    """
    template = synth()
    param = logical_id(template, "AWS::SSM::Parameter")
    trigger = logical_id(template, "Custom::Trigger")
    assert param in (template["Resources"][trigger].get("DependsOn") or []), (
        f"{trigger} does not depend on {param}: CloudFormation may create the "
        "endpoint parameter after hydration has already published it")


def test_cloudformation_still_owns_the_parameter():
    """What makes `cdk destroy` return retrieval to S3 Vectors.

    The Lambda only takes the parameter away and gives it back. If the stack
    stopped declaring it, `make down` and the nightly janitor would destroy the
    collection and leave the router pointing at it.
    """
    template = synth()
    param = template["Resources"][logical_id(template, "AWS::SSM::Parameter")]
    assert param["Properties"]["Name"] == "/regdelta/search/endpoint"


def test_the_reindex_role_may_write_only_that_parameter():
    template = synth()
    ssm_statements = [
        st
        for res in template["Resources"].values()
        if res["Type"] == "AWS::IAM::Policy"
        for st in res["Properties"]["PolicyDocument"]["Statement"]
        if any(a.startswith("ssm:")
               for a in ([st["Action"]] if isinstance(st["Action"], str)
                         else st["Action"]))
    ]
    assert len(ssm_statements) == 1, (
        f"expected exactly one ssm statement, got {ssm_statements}")
    st = ssm_statements[0]
    assert set(st["Action"]) == {"ssm:PutParameter", "ssm:DeleteParameter"}
    rendered = json.dumps(st["Resource"])
    assert "parameter/regdelta/search/endpoint" in rendered, rendered
    assert "*" not in rendered, (
        f"the reindex role can write parameters beyond the endpoint: {rendered}")


# -------------------------------------------------------------- the outside


@pytest.fixture
def gate(monkeypatch):
    """`evals/check_hydration.py`, with AWS replaced and the poll instant."""
    sys.modules.pop("check_hydration", None)
    import check_hydration as mod
    monkeypatch.setattr(mod, "COUNT_DEADLINE_S", 0.0)
    monkeypatch.setattr(mod, "COUNT_POLL_S", 0.0)
    yield mod
    sys.modules.pop("check_hydration", None)


def wire_gate(monkeypatch, mod, *, endpoint="https://x.aoss.amazonaws.com",
              corpus=600, count=600, embedding="knn_vector", raises=None):
    """Stand in for SSM, S3 and AOSS. `raises` is an AossError message."""
    monkeypatch.setattr(mod.router, "reset_cache", lambda: None)
    monkeypatch.setattr(mod.router, "active_endpoint", lambda: endpoint)
    monkeypatch.setattr(mod.reindex, "iter_chunk_records",
                        lambda b: iter(range(corpus)))

    def request(ep, method, path, *a, **kw):
        if raises is not None:
            raise mod.aoss_client.AossError(raises)
        if path.endswith("_count"):
            return {"count": count}
        if embedding is None:
            return {mod.aoss_client.INDEX_NAME: {"mappings": {}}}
        return {mod.aoss_client.INDEX_NAME: {
            "mappings": {"properties": {"embedding": {"type": embedding}}}}}

    monkeypatch.setattr(mod.aoss_client, "request", request)


def reasons(report: dict) -> str:
    return " | ".join(r["reason"] for r in report["refusals"])


def checks(report: dict) -> set[str]:
    return {r["check"] for r in report["refusals"]}


def test_a_hydrated_tier_passes(gate, monkeypatch):
    wire_gate(monkeypatch, gate)
    ok, report = gate.run("corpus-bucket")
    assert ok, report
    assert report["indexed"] == report["corpus"] == 600
    assert report["embedding_type"] == "knn_vector"


def test_refuses_when_the_endpoint_parameter_is_absent(gate, monkeypatch):
    """The M02 residue, seen from outside: a deploy that left no endpoint."""
    wire_gate(monkeypatch, gate, endpoint=None)
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "endpoint" in checks(report)
    assert "routes to S3 Vectors" in reasons(report)


def test_refuses_a_short_index(gate, monkeypatch):
    """The partial index. It answers, with citations, and looks healthy."""
    wire_gate(monkeypatch, gate, corpus=600, count=599)
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "count_parity" in checks(report)
    assert "599 indexed vs 600" in reasons(report)


def test_refuses_a_dynamic_mapping_the_count_cannot_see(gate, monkeypatch):
    """Every document present, every kNN query broken."""
    wire_gate(monkeypatch, gate, embedding="float")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "embedding_type" in checks(report)
    assert "knn_vector" in reasons(report)


def test_refuses_an_unreadable_mapping(gate, monkeypatch):
    wire_gate(monkeypatch, gate, embedding=None)
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "embedding_type" in checks(report)


def test_refuses_an_index_that_is_not_there(gate, monkeypatch):
    wire_gate(monkeypatch, gate, raises="chunks -> 404 index_not_found")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "indexed" in checks(report)
    assert "does not exist" in reasons(report)


def test_refuses_a_403_and_says_which_of_the_two_doors_is_shut(gate, monkeypatch):
    """A bare AOSS 403 is ambiguous; the message has to name the policy."""
    wire_gate(monkeypatch, gate, raises="chunks/_count -> 403 Forbidden")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "devPrincipalArn" in reasons(report)


def test_refuses_when_the_index_cannot_be_read_at_all(gate, monkeypatch):
    wire_gate(monkeypatch, gate, raises="connection reset")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "cannot read the index" in reasons(report)


def test_refuses_an_unset_corpus_bucket(gate, monkeypatch):
    wire_gate(monkeypatch, gate)
    ok, report = gate.run("")
    assert not ok
    assert "corpus" in checks(report)


def test_refuses_an_empty_corpus_rather_than_passing_zero_against_zero(
        gate, monkeypatch):
    wire_gate(monkeypatch, gate, corpus=0, count=0)
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "corpus" in checks(report)
    assert "0 == 0" in reasons(report)


def test_reports_every_refusal_not_only_the_first(gate, monkeypatch):
    """Twenty minutes per `make up` is too long to learn one fault at a time."""
    wire_gate(monkeypatch, gate, corpus=600, count=599, embedding="float")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert checks(report) == {"count_parity", "embedding_type"}


def test_the_expected_mapping_is_read_off_the_one_the_stack_ships(monkeypatch):
    """ADR-0013: the instrument reads the field its own claim is about.

    A guard carrying its own copy of "knn_vector" keeps passing after someone
    changes the real mapping — which is the change it exists to catch.

    Asserting `EXPECTED_EMBEDDING_TYPE == INDEX_MAPPING[...]` would NOT catch
    that: both sides read "knn_vector" today whether the guard derived it or
    spelled it. So the shipped mapping is CHANGED and the guard re-imported —
    a literal does not follow, a derivation does. (Written the equal-values
    way first, which is the same defect this milestone has now hit three
    times.)
    """
    from retrieval import aoss_client

    mutated = json.loads(json.dumps(aoss_client.INDEX_MAPPING))
    mutated["mappings"]["properties"]["embedding"]["type"] = "sparse_vector"
    monkeypatch.setattr(aoss_client, "INDEX_MAPPING", mutated)

    sys.modules.pop("check_hydration", None)
    import check_hydration as reloaded
    try:
        assert reloaded.EXPECTED_EMBEDDING_TYPE == "sparse_vector", (
            "the guard did not follow the shipped mapping, so it holds its own "
            "copy of the expected type and cannot detect a mapping change")
    finally:
        sys.modules.pop("check_hydration", None)


def test_the_gate_reads_the_parameter_the_router_reads(gate, monkeypatch):
    """Not a CloudFormation output, not the collection list.

    Whether the hot tier is "up" is decided by exactly one value: the one
    `router.active_endpoint()` returns. A gate that consulted anything else
    could pass while retrieval routed somewhere else.
    """
    calls = []
    monkeypatch.setattr(gate.router, "reset_cache", lambda: calls.append("reset"))
    monkeypatch.setattr(gate.router, "active_endpoint",
                        lambda: calls.append("read") or "https://x.aoss.amazonaws.com")
    assert gate.resolve_endpoint() == "https://x.aoss.amazonaws.com"
    assert calls == ["reset", "read"], (
        "the cached endpoint has a 60s TTL and `make up` flips the parameter "
        "inside that window, so the gate must drop the cache before reading")


def test_an_unexpected_error_becomes_a_refusal_not_a_traceback(gate, monkeypatch):
    """The report is the whole product of this script, and it was losable.

    `router.active_endpoint()` catches only ParameterNotFound and
    `iter_chunk_records` goes straight to S3, so an expired token or an
    AccessDenied used to raise out of `run()` as a botocore traceback — after
    a twenty-minute deploy, with OCU billing, discarding every refusal already
    collected. Found by eng-code-reviewer.
    """
    wire_gate(monkeypatch, gate)
    monkeypatch.setattr(gate.router, "active_endpoint",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("ExpiredToken: the token has expired")))
    ok, report = gate.run("corpus-bucket")

    assert not ok
    assert "endpoint" in checks(report)
    assert "ExpiredToken" in reasons(report)
    # And the rest of the pass still ran, so one twenty-minute run reports
    # everything it can see rather than the first thing that broke.
    assert report["corpus"] == 600


def test_a_longer_index_is_not_reported_as_short(gate, monkeypatch):
    """`index_count` returns as soon as it sees >= expected, so a stale index
    with extra documents is reachable. Calling that "short" sends the reader
    hunting for a missing chunk that does not exist."""
    wire_gate(monkeypatch, gate, corpus=600, count=601)
    ok, report = gate.run("corpus-bucket")
    assert not ok
    assert "count_parity" in checks(report)
    assert "short" not in reasons(report), reasons(report)
    assert "601 indexed vs 600" in reasons(report)


# `--refusals`: the refusal SET, for a caller that must branch on it


def test_the_refusal_set_is_reported_sorted_and_space_separated(gate, monkeypatch):
    """`make fault-drop` has to tell "the parameter is gone" (safe) from "the
    parameter is live and the index is unverified" (not safe).

    Grepping the JSON for one check name got that wrong: any non-count_parity
    refusal read as proof the tier was out of service, so a 403 or a missing
    index printed "Retrieval is on S3 Vectors" while the endpoint was still
    live. A caller that needs the set should be handed the set.
    """
    wire_gate(monkeypatch, gate, corpus=600, count=599, embedding="float")
    _, report = gate.run("corpus-bucket")
    names = sorted(r["check"] for r in report["refusals"])
    assert names == ["count_parity", "embedding_type"]
    assert " ".join(names) == "count_parity embedding_type"


def test_a_healthy_tier_has_an_empty_refusal_set(gate, monkeypatch):
    """The empty set is what distinguishes "repaired" from every failure."""
    wire_gate(monkeypatch, gate)
    ok, report = gate.run("corpus-bucket")
    assert ok
    assert [r["check"] for r in report["refusals"]] == []


def test_a_live_endpoint_over_an_unverifiable_index_is_not_an_endpoint_refusal(
        gate, monkeypatch):
    """The false pass, pinned.

    A 403 leaves `/regdelta/search/endpoint` LIVE and the index unchecked.
    Reading that as "the tier is out of service" is what made `make fault-drop`
    report success over an unverified index.
    """
    wire_gate(monkeypatch, gate, raises="chunks/_count -> 403 Forbidden")
    ok, report = gate.run("corpus-bucket")
    assert not ok
    names = {r["check"] for r in report["refusals"]}
    # BOTH reads fail on a 403 — the count and the mapping — and both are
    # reported, which is the multi-refusal behaviour working.
    assert names == {"indexed", "embedding_type"}
    assert "endpoint" not in names, (
        "a 403 must NOT look like an absent endpoint — the parameter is still "
        "live and pointing at an index nobody verified")
    assert report["endpoint"]
