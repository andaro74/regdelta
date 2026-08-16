"""Hydration count-parity (SPEC/02 Done-when B) — the partial-index failure.

A partial index is the worst kind of broken: it answers, with citations, and
the missing chunks are invisible. The only defence is that the deploy fails,
so these tests pin that the raise actually happens and that nothing in the
module can turn it off.

(B) also requires evidence from a real deploy — a failed CloudFormation event
captured in milestones/M02/. These tests are the unit half; they do not
substitute for it, and a test asserting that a raise raises would be worth
very little on its own.
"""
import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def reindex(monkeypatch):
    monkeypatch.setenv("CORPUS_BUCKET", "corpus")
    monkeypatch.setenv("COLLECTION_ENDPOINT",
                       "https://abc123.us-west-2.aoss.amazonaws.com")
    sys.modules.pop("retrieval.reindex", None)
    from retrieval import reindex as mod
    # A real deploy waits up to 5 minutes for AOSS to refresh. A test asserting
    # that a SHORT count raises would otherwise spend that 5 minutes waiting
    # for a count that is never going to arrive.
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


def wire(monkeypatch, mod, source: list[dict], indexed_count):
    """Stand in for S3 and AOSS. `indexed_count` may be an int or a callable."""
    sent: list[dict] = []
    monkeypatch.setattr(mod, "_iter_chunk_records", lambda bucket: iter(source))
    monkeypatch.setattr(mod, "_create_index", lambda ep: None)
    monkeypatch.setattr(mod, "_bulk", lambda ep, docs: sent.extend(docs))
    monkeypatch.setattr(mod, "_count", lambda ep: (
        indexed_count(sent) if callable(indexed_count) else indexed_count))
    monkeypatch.setattr(mod, "_assert_knn_mapping", lambda ep: None)
    return sent


def test_a_complete_hydration_returns_both_counts(reindex, monkeypatch):
    src = records(1200)
    sent = wire(monkeypatch, reindex, src, lambda s: len(s))
    out = reindex.handler({}, None)
    assert out["source"] == 1200
    assert out["indexed"] == 1200
    assert len(sent) == 1200


def test_bulk_batches_at_500(reindex, monkeypatch):
    sizes = []
    monkeypatch.setattr(reindex, "_iter_chunk_records", lambda b: iter(records(1200)))
    monkeypatch.setattr(reindex, "_create_index", lambda ep: None)
    monkeypatch.setattr(reindex, "_bulk", lambda ep, docs: sizes.append(len(docs)))
    monkeypatch.setattr(reindex, "_count", lambda ep: 1200)
    monkeypatch.setattr(reindex, "_assert_knn_mapping", lambda ep: None)
    reindex.handler({}, None)
    assert sizes == [500, 500, 200]


def test_a_short_index_fails_the_deploy(reindex, monkeypatch):
    """The whole point of (B). 1199 of 1200 must raise, not warn."""
    wire(monkeypatch, reindex, records(1200), 1199)
    with pytest.raises(RuntimeError, match="hydration count mismatch"):
        reindex.handler({}, None)


def test_the_fault_hook_produces_exactly_the_failure_it_advertises(reindex,
                                                                   monkeypatch):
    """REINDEX_FAULT_DROP is how the milestone gets a REAL failed deploy.

    It drops records before indexing; the count assertion then fails on its
    own. Nothing about the assertion is bypassed, which is why this hook
    cannot manufacture the outcome it tests for (a partial index reporting
    success).
    """
    monkeypatch.setattr(reindex, "FAULT_DROP", 3)
    wire(monkeypatch, reindex, records(10), lambda s: len(s))
    with pytest.raises(RuntimeError, match="hydration count mismatch"):
        reindex.handler({}, None)


def test_no_switch_in_the_module_can_relax_the_assertion(reindex):
    """Guards the fault hook against growing an escape hatch later.

    If someone adds `if FAULT_DROP: return result` to make the fault run
    "succeed", this fails. Reading the source is a blunt instrument, but the
    property — there is exactly one comparison and it always raises — is not
    otherwise expressible.
    """
    import inspect
    src = inspect.getsource(reindex.handler)
    assert src.count("indexed != source") == 1
    assert "raise RuntimeError" in src


def test_an_empty_corpus_is_a_failure_not_a_healthy_empty_index(reindex,
                                                                monkeypatch):
    """0 == 0 passes a naive count check. An empty hot tier then answers every
    query with nothing, which reads as a retrieval bug for as long as it takes
    someone to check the deploy."""
    wire(monkeypatch, reindex, [], 0)
    with pytest.raises(RuntimeError, match="no chunk records"):
        reindex.handler({}, None)


def test_await_count_gives_aoss_time_to_refresh(reindex, monkeypatch):
    """AOSS refreshes on its own schedule and exposes no refresh API, so a
    count read straight after bulk is low because the index has not refreshed
    — not because documents are missing. Reading once would fail every healthy
    deploy."""
    seq = iter([0, 0, 5, 10])
    monkeypatch.setattr(reindex, "_count", lambda ep: next(seq))
    assert reindex._await_count("https://x", 10, deadline_s=99) == 10


def test_await_count_gives_up_at_the_deadline(reindex, monkeypatch):
    """It must return the short count rather than looping forever — the
    handler is what decides that a short count fails."""
    monkeypatch.setattr(reindex, "_count", lambda ep: 3)
    assert reindex._await_count("https://x", 10, deadline_s=-1) == 3


# ------------------------------------------- index-visibility propagation (404)
def test_count_reports_an_invisible_index_as_none_not_zero(reindex, monkeypatch):
    """The failure that killed the third `make up`.

    AOSS decouples ingest compute from search compute, and index metadata
    reaches them separately. On a fresh collection the PUT succeeded, a
    500-document `_bulk` was ACCEPTED against `chunks`, and `chunks/_count`
    then answered 404 index_not_found — 11 seconds in. That is not an empty
    index, and 0 would be the wrong answer to give the caller.
    """
    from retrieval import aoss_client
    monkeypatch.setattr(reindex.aoss_client, "request",
                        lambda *a, **k: (_ for _ in ()).throw(
                            aoss_client.AossError(
                                'POST chunks/_count -> 404: {"error":'
                                '{"type":"index_not_found_exception"}}')))
    assert reindex._count("https://x") is None


def test_count_does_not_swallow_other_errors(reindex, monkeypatch):
    """Only index_not_found is a propagation story. A 403 here is the data
    access policy and must not be reported as 'not visible yet' — that would
    spend the whole deadline before failing with the wrong explanation."""
    from retrieval import aoss_client
    monkeypatch.setattr(reindex.aoss_client, "request",
                        lambda *a, **k: (_ for _ in ()).throw(
                            aoss_client.AossError("POST chunks/_count -> 403")))
    with pytest.raises(aoss_client.AossError, match="403"):
        reindex._count("https://x")


def test_await_count_waits_out_an_invisible_index(reindex, monkeypatch):
    """Same shape as waiting out a low count, one step earlier."""
    seq = iter([None, None, 0, 10])
    monkeypatch.setattr(reindex, "_count", lambda ep: next(seq))
    assert reindex._await_count("https://x", 10, deadline_s=99) == 10


def test_an_index_that_never_appears_fails_the_deploy(reindex, monkeypatch):
    """Waiting out the 404 may only DELAY a failure, never convert one into a
    success — the same property that makes the 403 retry safe. If the index is
    still missing at the deadline the deploy fails, and says so distinctly:
    'ingest accepted writes search cannot resolve' is a different bug from
    'some documents are missing'."""
    wire(monkeypatch, reindex, records(10), None)
    with pytest.raises(RuntimeError, match="never visible to the search path"):
        reindex.handler({}, None)


def test_a_dynamically_mapped_index_fails_the_deploy(reindex, monkeypatch):
    """Closes the hole tolerating index_not_found opens.

    If a create ever silently no-ops, `_bulk` auto-creates `chunks` with a
    dynamic mapping: every document lands, the count assertion passes, and
    `embedding` is a float array. That deploy reports success and every kNN
    query fails afterwards.
    """
    monkeypatch.setattr(reindex.aoss_client, "request", lambda *a, **k: {
        "chunks": {"mappings": {"properties": {"embedding": {"type": "float"}}}}})
    with pytest.raises(RuntimeError, match="not 'knn_vector'"):
        reindex._assert_knn_mapping("https://x")

    monkeypatch.setattr(reindex.aoss_client, "request", lambda *a, **k: {
        "chunks": {"mappings": {"properties": {
            "embedding": {"type": "knn_vector", "dimension": 1024}}}}})
    reindex._assert_knn_mapping("https://x")


def test_an_unrecognised_mapping_body_does_not_fail_the_deploy(reindex,
                                                                monkeypatch):
    """This guard runs after a full hydration has passed the count assertion,
    and the AOSS response shape it reads is not verified anywhere in CI. A
    wrong guess about that shape must not fail an otherwise-healthy deploy —
    it degrades to a log line instead."""
    monkeypatch.setattr(reindex.aoss_client, "request",
                        lambda *a, **k: {"unexpected": {}})
    reindex._assert_knn_mapping("https://x")


# --------------------------------------------------------- document shape
def test_null_dates_are_omitted_not_sent_as_null(reindex):
    """The mapping types dates as `date`. A range query excludes documents
    that LACK the field — which is ADR-0006's rule falling out of the mapping.
    An explicit null would be accepted and would not obviously break anything,
    which is what makes it worth pinning."""
    doc = reindex._document({
        "chunk_id": "2025-03118#0003", "text": "body",
        "citation_path": "90 FR 10592", "embedding": [0.1],
        "doc_type": "delay_notice", "cfr_title": "21", "cfr_part": "101",
        "pub_date": "2025-02-25", "effective_date": "2025-04-28",
        "compliance_date": None})
    assert "compliance_date" not in doc
    assert doc["effective_date"] == "2025-04-28"


def test_the_jsonl_text_field_becomes_chunk_text(reindex):
    """The JSONL calls it `text`, S3 Vectors calls it `chunk_text`. One
    renaming point, so Chunk.from_metadata reads both tiers."""
    doc = reindex._document({"chunk_id": "a#0000", "text": "hello",
                             "citation_path": "c", "embedding": [0.1]})
    assert doc["chunk_text"] == "hello"
    assert "text" not in doc


def test_both_tiers_agree_on_field_names(reindex):
    """The duplication guard. The AOSS mapping, the AOSS document and the S3
    Vectors metadata must use identical keys or Chunk.from_metadata silently
    returns half-empty chunks on one tier — and criterion 3's Jaccard gate
    would be measuring that instead of retrieval drift."""
    from retrieval import aoss_client
    doc = reindex._document(records(1)[0])
    mapped = set(aoss_client.INDEX_MAPPING["mappings"]["properties"])
    assert set(doc) <= mapped, set(doc) - mapped


def test_bulk_payload_is_ndjson_with_an_index_action_per_document(reindex,
                                                                  monkeypatch):
    captured = {}

    def fake_request(endpoint, method, path, body=None, **kw):
        captured.update(path=path, body=body, ct=kw.get("content_type"))
        return {"errors": False, "items": []}

    monkeypatch.setattr(reindex.aoss_client, "request", fake_request)
    reindex._bulk("https://abc123.us-west-2.aoss.amazonaws.com",
                  [{"chunk_id": "a"}, {"chunk_id": "b"}])
    lines = captured["body"].decode().splitlines()
    assert captured["path"] == "_bulk"
    assert captured["ct"] == "application/x-ndjson"
    assert len(lines) == 4
    assert json.loads(lines[0]) == {"index": {"_index": "chunks"}}
    assert json.loads(lines[1])["chunk_id"] == "a"


def test_a_bulk_error_response_raises(reindex, monkeypatch):
    """`_bulk` returns HTTP 200 with `errors: true` when individual documents
    fail. Trusting the status code would index fewer documents than it sent
    and let the count check report the shortfall without the reason."""
    monkeypatch.setattr(reindex.aoss_client, "request", lambda *a, **k: {
        "errors": True,
        "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}]})
    with pytest.raises(reindex.aoss_client.AossError, match="mapper_parsing"):
        reindex._bulk("https://abc123.us-west-2.aoss.amazonaws.com", [{"a": 1}])


def test_the_endpoint_must_be_an_aoss_collection(reindex):
    """An SSM parameter is writable by anything with ssm:PutParameter, and the
    request carries SigV4 headers. Pinning the host shape means a tampered
    parameter cannot hand signed credentials to an arbitrary listener."""
    from retrieval import aoss_client
    ok = "https://abc123.us-west-2.aoss.amazonaws.com"
    assert aoss_client.check_endpoint(ok + "/") == ok
    for bad in ("http://abc123.us-west-2.aoss.amazonaws.com",
                "https://evil.example.com",
                "https://abc123.us-west-2.aoss.amazonaws.com.evil.com",
                "https://abc123.us-west-2.es.amazonaws.com",
                ""):
        with pytest.raises(aoss_client.AossError):
            aoss_client.check_endpoint(bad)


def test_index_creation_tolerates_a_missing_index_but_not_other_errors(reindex,
                                                                       monkeypatch):
    """DELETE on a fresh collection 404s and that is fine. Any other failure
    must propagate — swallowing it would create the index over stale settings
    or skip creation entirely and leave hydration writing into a dynamically
    mapped index with no knn_vector field."""
    from retrieval import aoss_client
    calls = []

    def fake(endpoint, method, path, body=None, **kw):
        calls.append((method, path))
        if method == "DELETE":
            raise aoss_client.AossError("DELETE chunks -> 404: index_not_found")
        return {}

    monkeypatch.setattr(reindex.aoss_client, "request", fake)
    reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")
    assert calls == [("DELETE", "chunks"), ("PUT", "chunks")]

    def fake_403(endpoint, method, path, body=None, **kw):
        raise aoss_client.AossError("DELETE chunks -> 403: AccessDenied")

    monkeypatch.setattr(reindex.aoss_client, "request", fake_403)
    with pytest.raises(aoss_client.AossError, match="403"):
        reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")


# ------------------------------------------------------------- SigV4 (aoss)
def test_every_request_carries_the_payload_hash_header():
    """aoss REQUIRES x-amz-content-sha256 and reports its absence as a bare
    `403 Forbidden` with an OpenSearch-shaped body — indistinguishable from a
    data-access-policy denial. Two deploys were spent on that ambiguity.

    botocore's generic SigV4Auth folds the payload hash into the canonical
    request but never emits it as a header; only S3SigV4Auth does. So a signer
    that looks correct, and whose signature IS correct, is rejected.
    """
    import hashlib

    from retrieval import aoss_client

    sent = {}

    class FakeResponse:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["headers"] = {k.lower(): v for k, v in req.headers.items()}
        sent["body"] = req.data
        return FakeResponse()

    import botocore.credentials
    creds = botocore.credentials.Credentials("AKIA_TEST", "secret")
    import botocore.session
    session = botocore.session.get_session()
    orig_get, orig_open = session.get_credentials, aoss_client.urllib.request.urlopen
    try:
        botocore.session.get_session = lambda: type(
            "S", (), {"get_credentials": staticmethod(lambda: creds)})()
        aoss_client.urllib.request.urlopen = fake_urlopen
        aoss_client.request("https://abc123.us-west-2.aoss.amazonaws.com",
                            "PUT", "chunks", {"mappings": {}})
    finally:
        botocore.session.get_session = lambda: session
        session.get_credentials = orig_get
        aoss_client.urllib.request.urlopen = orig_open

    expected = hashlib.sha256(sent["body"]).hexdigest()
    assert sent["headers"]["x-amz-content-sha256"] == expected
    # Signed, not merely present: it must appear in SignedHeaders, or a future
    # reader may "tidy" it to a post-signing addition and change what is
    # covered by the signature.
    assert "x-amz-content-sha256" in sent["headers"]["authorization"]


# ------------------------------------- data-access-policy propagation (403)
def test_index_creation_waits_out_a_403_from_a_policy_still_propagating(
        reindex, monkeypatch):
    """The failure that killed the first `make up`.

    AOSS data access policies are eventually consistent on the data plane, and
    the CDK Trigger fires the moment CloudFormation reports the policy created.
    The DELETE returned 404 (no index yet) and the PUT came back 403 from a
    policy that already existed and was already correct.
    """
    from retrieval import aoss_client
    monkeypatch.setattr(reindex, "AUTHZ_PROPAGATION_S", 60.0)
    attempts = []

    def fake(endpoint, method, path, body=None, **kw):
        attempts.append(method)
        if method == "DELETE":
            raise aoss_client.AossError("DELETE chunks -> 404: index_not_found")
        if attempts.count("PUT") < 3:
            raise aoss_client.AossError(
                'PUT chunks -> 403: {"status":403,"error":'
                '{"reason":"403 Forbidden","type":"Forbidden"}}')
        return {}

    monkeypatch.setattr(reindex.aoss_client, "request", fake)
    reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")
    assert attempts.count("PUT") == 3


def test_a_403_that_outlives_the_window_still_fails_the_deploy(reindex,
                                                               monkeypatch):
    """Retrying 403 forever would turn a permissions bug into a timeout — the
    same bug wearing a disguise. The error must also name the caller, because
    the entire ambiguity of an AOSS 403 is whether the signing principal is the
    one the data access policy lists."""
    from retrieval import aoss_client
    monkeypatch.setattr(reindex, "_caller_arn",
                        lambda: "arn:aws:sts::1:assumed-role/ReindexFn/x")

    def fake(endpoint, method, path, body=None, **kw):
        if method == "DELETE":
            raise aoss_client.AossError("DELETE chunks -> 404: index_not_found")
        raise aoss_client.AossError("PUT chunks -> 403: Forbidden")

    monkeypatch.setattr(reindex.aoss_client, "request", fake)
    with pytest.raises(aoss_client.AossError) as exc:
        reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")
    assert "DATA ACCESS POLICY" in str(exc.value)
    assert "assumed-role/ReindexFn" in str(exc.value)


def test_only_403_is_retried(reindex, monkeypatch):
    """A 400 on the mapping is a bug in the mapping. Waiting three minutes to
    re-report it would hide a fast, deterministic failure behind a slow one."""
    from retrieval import aoss_client
    monkeypatch.setattr(reindex, "AUTHZ_PROPAGATION_S", 600.0)
    calls = []

    def fake(endpoint, method, path, body=None, **kw):
        calls.append(method)
        if method == "DELETE":
            raise aoss_client.AossError("DELETE chunks -> 404: index_not_found")
        raise aoss_client.AossError(
            "PUT chunks -> 400: mapper_parsing_exception")

    monkeypatch.setattr(reindex.aoss_client, "request", fake)
    with pytest.raises(aoss_client.AossError, match="mapper_parsing"):
        reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")
    assert calls.count("PUT") == 1


def test_a_403_on_delete_is_never_retried_or_swallowed(reindex, monkeypatch):
    """DELETE tolerates only 'index not found'. A 403 there is the same
    authorization problem, but retrying it belongs to the create path — and
    swallowing it would create the index over stale settings."""
    from retrieval import aoss_client
    monkeypatch.setattr(reindex.aoss_client, "request",
                        lambda *a, **k: (_ for _ in ()).throw(
                            aoss_client.AossError("DELETE chunks -> 403: Forbidden")))
    with pytest.raises(aoss_client.AossError, match="403"):
        reindex._create_index("https://abc123.us-west-2.aoss.amazonaws.com")


def test_iter_chunk_records_skips_non_jsonl_keys(reindex, monkeypatch):
    """corpus/chunks/ holds only JSONL today, but the source count is what the
    parity assertion compares against — counting a stray object would fail
    every deploy with a mismatch that has nothing to do with hydration."""
    pages = [{"Contents": [{"Key": "chunks/101/a.jsonl"},
                           {"Key": "chunks/101/a.jsonl.bak"},
                           {"Key": "chunks/"}]}]
    body = SimpleNamespace(read=lambda: b'{"chunk_id":"a#0000"}\n\n')
    monkeypatch.setattr(reindex, "_s3_client", lambda: SimpleNamespace(
        get_paginator=lambda op: SimpleNamespace(paginate=lambda **kw: pages),
        get_object=lambda Bucket, Key: {"Body": body}))
    got = list(reindex._iter_chunk_records("corpus"))
    assert [r["chunk_id"] for r in got] == ["a#0000"]
