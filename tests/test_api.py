"""SPEC/04's API surface, driven in-process through the real app.

The centrepiece is `test_all_four_refusals_are_byte_identical`. SPEC/04's
Done-when names four conditions — a token minted for a different thread, a
malformed token, no token at all, and a thread that never existed — and
requires all four to return 404 with byte-identical bodies, so the response
cannot distinguish "not yours" from "does not exist". A test with one negative
case would pass while the 404 came from an unrelated route-not-found.

The graph is stubbed throughout. These test the HTTP surface and the access
rule; whether the graph answers correctly is the golden set's job.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import api as m, resume_token as rt

TRACE = "trace-fixed-for-comparison"


@pytest.fixture
def client(monkeypatch):
    """A client whose graph is stubbed and whose token store is in memory.

    `m._compiled` is cleared per test. The app caches its compiled graph — it
    used to rebuild one per request, which is how the real end-to-end run
    resumed against a graph that had never checkpointed anything — so a stub
    left in that cache would leak into the next test.
    """
    store: dict[str, str] = {}
    monkeypatch.setattr(m, "_store_token", lambda tid, dig: store.__setitem__(tid, dig))
    monkeypatch.setattr(m, "_load_token", lambda tid: store.get(tid))
    monkeypatch.setattr(m, "_compiled", {})
    return TestClient(m.app), store


def _stub_graph(monkeypatch, state: dict, *, resumable: bool = True):
    """Put a fixed final state into the app's compiled-graph cache.

    Stubs at `_compiled` rather than at `build_graph`, because that is the seam
    the request path actually reads. Stubbing the builder passed while the app
    was rebuilding per request and stopped meaning anything once it cached —
    the test would have kept passing against a stale stub.
    """
    class _App:
        def invoke(self, *a, **k):
            return state

    monkeypatch.setattr(m, "_compiled", {"app": _App(), "resumable": resumable})


def _paused(reason="no product or label claim to apply a rule to"):
    class _Interrupt:
        def __init__(self):
            self.value = {"status": "needs_input", "reason": reason}

    return {"__interrupt__": [_Interrupt()], "answer": "", "verdict_rows": [],
            "citations": [], "confidence": 0.0}


def _answered():
    return {"answer": "Compliance is due February 25, 2028.", "verdict_rows": [],
            "citations": ["89 FR 106064"], "confidence": 0.91, "status": "ok"}


# --------------------------------------------------------------- /health
def test_health_reports_the_active_tier(client, monkeypatch):
    c, _ = client
    import retrieval.router as rr
    monkeypatch.setattr(rr, "active_tier", lambda: "aoss")
    body = c.get("/health").json()
    assert body == {"status": "ok", "tier": "aoss"}


def test_health_does_not_500_when_the_tier_cannot_be_resolved(client, monkeypatch):
    """A health endpoint that fails when a dependency fails cannot report that
    the dependency failed."""
    c, _ = client
    import retrieval.router as rr

    def boom():
        raise RuntimeError("ssm unreachable")

    monkeypatch.setattr(rr, "active_tier", boom)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["tier"] == "unknown"


# ---------------------------------------------------------------- /query
def test_a_question_is_required(client):
    c, _ = client
    for payload in ({}, {"question": ""}, {"question": "   "}):
        r = c.post("/query", json=payload)
        assert r.status_code == 400, payload


def test_an_answered_run_gets_no_resume_token(client, monkeypatch):
    """A token on every response is a credential handed out for nothing, and
    SPEC/04 says these fields appear only when the run paused."""
    c, store = client
    _stub_graph(monkeypatch, _answered())
    body = c.post("/query", json={"question": "when?"}).json()
    assert body["status"] == "ok"
    assert "resume_token" not in body
    assert "thread_id" not in body
    assert store == {}


def test_a_paused_run_gets_a_thread_id_and_a_token(client, monkeypatch):
    c, store = client
    _stub_graph(monkeypatch, _paused())
    body = c.post("/query", json={"question": "are we affected?"}).json()
    assert body["status"] == "needs_input"
    assert body["thread_id"] and body["resume_token"]
    # Only the DIGEST is persisted; the plaintext leaves exactly once.
    assert store[body["thread_id"]] == rt.digest(body["resume_token"])
    assert body["resume_token"] not in json.dumps(store)


# --------------------------------------------------------------- /resume
def test_the_right_token_resumes(client, monkeypatch):
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    started = c.post("/query", json={"question": "are we affected?"}).json()

    _stub_graph(monkeypatch, _answered())
    r = c.post(f"/resume/{started['thread_id']}",
               json={"resume_token": started["resume_token"],
                     "company_profile": {"claims": ["healthy"]}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_all_four_refusals_are_byte_identical(client, monkeypatch):
    """SPEC/04's Done-when, in one assertion.

    The same trace id is supplied for all four so the bodies are comparable
    byte-for-byte; trace_id is the only field the spec permits to vary, and it
    is what ties the caller's 404 to the reason in the log.
    """
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    mine = c.post("/query", json={"question": "are we affected?"}).json()

    other = c.post("/query", json={"question": "are we affected?"}).json()
    assert other["thread_id"] != mine["thread_id"]

    # A thread that never existed must fail in the graph, not before it.
    def explode(*a, **k):
        raise KeyError("no checkpoint for thread")

    responses = []
    headers = {"x-amzn-trace-id": TRACE}

    # 1. a token minted for a DIFFERENT thread
    responses.append(c.post(f"/resume/{mine['thread_id']}",
                            json={"resume_token": other["resume_token"]},
                            headers=headers))
    # 2. a malformed token
    responses.append(c.post(f"/resume/{mine['thread_id']}",
                            json={"resume_token": "not-a-real-token"},
                            headers=headers))
    # 3. no token at all
    responses.append(c.post(f"/resume/{mine['thread_id']}", json={},
                            headers=headers))
    # 4. a thread that was never created
    class _Boom:
        invoke = explode

    monkeypatch.setattr(m, "_compiled", {"app": _Boom(), "resumable": True})
    responses.append(c.post("/resume/00000000-0000-0000-0000-000000000000",
                            json={"resume_token": mine["resume_token"]},
                            headers=headers))

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    bodies = {r.content for r in responses}
    assert len(bodies) == 1, (
        "the four refusals are distinguishable:\n"
        + "\n".join(r.content.decode() for r in responses))


def test_each_refusal_is_logged_with_its_own_reason(client, monkeypatch, caplog):
    """Indistinguishable to the caller, diagnosable to the operator. The spec
    accepted the opaque 404 only because this line is required to exist."""
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    mine = c.post("/query", json={"question": "are we affected?"}).json()
    other = c.post("/query", json={"question": "are we affected?"}).json()

    with caplog.at_level("WARNING", logger="regdelta.api"):
        c.post(f"/resume/{mine['thread_id']}",
               json={"resume_token": other["resume_token"]})
        c.post(f"/resume/{mine['thread_id']}", json={})

    reasons = [r.getMessage() for r in caplog.records if "resume refused" in r.getMessage()]
    assert len(reasons) == 2
    assert reasons[0] != reasons[1], f"reasons collapsed: {reasons}"
    assert all("trace_id=" in r for r in reasons)


def test_the_refusal_body_never_names_the_thread_or_the_reason(client, monkeypatch):
    """The whole point: a 404 whose body reads "token does not match thread
    t-abc" satisfies "404 not 403" and leaks anyway."""
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    mine = c.post("/query", json={"question": "are we affected?"}).json()

    body = c.post(f"/resume/{mine['thread_id']}", json={}).content.decode()
    assert mine["thread_id"] not in body
    for leak in ("token", "match", "expired", "exists", "stored"):
        assert leak not in body.lower(), f"{leak!r} leaks the reason: {body}"


def test_enforcement_can_be_disabled_for_the_offline_shim(client, monkeypatch):
    """RESUME_TOKEN_REQUIRED=0 exists so harnesses that predate tokens keep
    working. It must be the ONLY thing that disables the check."""
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    mine = c.post("/query", json={"question": "are we affected?"}).json()

    monkeypatch.setenv("RESUME_TOKEN_REQUIRED", "0")
    _stub_graph(monkeypatch, _answered())
    r = c.post(f"/resume/{mine['thread_id']}", json={})
    assert r.status_code == 200


def test_a_pause_with_no_checkpointer_gets_no_token(client, monkeypatch):
    """A token for an unresumable run is a promise the next request cannot keep.

    With STATE_TABLE unset the graph still runs and still pauses, but nothing is
    checkpointed. Handing out a capability there would leave the caller holding
    a credential and receiving a 404 that reads as a refusal rather than as a
    missing capability — so the body says `resumable: false` instead.
    """
    c, store = client
    _stub_graph(monkeypatch, _paused(), resumable=False)
    body = c.post("/query", json={"question": "are we affected?"}).json()
    assert body["status"] == "needs_input"
    assert "resume_token" not in body
    assert body["resumable"] is False
    assert "not resumable" in body["review_reason"]
    assert store == {}


def test_the_graph_is_compiled_once_not_per_request(monkeypatch):
    """It rebuilt per request, which is why the real end-to-end resume ran
    against a graph that had never checkpointed anything."""
    import graph.graph as gg

    monkeypatch.setattr(m, "_compiled", {})
    monkeypatch.setattr(m, "_store_token", lambda *a: None)
    monkeypatch.setattr(m, "_load_token", lambda *a: None)

    builds = []

    def counting_build(checkpointer=None):
        builds.append(checkpointer)

        class _App:
            def invoke(self, *a, **k):
                return _answered()
        return _App()

    monkeypatch.setattr(gg, "build_graph", counting_build)
    c = TestClient(m.app)
    for _ in range(3):
        c.post("/query", json={"question": "when?"})
    assert len(builds) == 1, f"compiled {len(builds)} times for 3 requests"


def test_the_run_config_carries_resumable_not_just_thread_id(monkeypatch):
    """`hitl_gate` reads `configurable.resumable` and, without it, reports the
    review status and STOPS instead of calling `interrupt()`.

    Omitting it produced a response that looked entirely correct — 200,
    `status: needs_input`, a reason — with no checkpoint written and nothing
    actually pausable. The resume then re-ran from the top, paused the same
    way, and returned 200 with the same body, which reads like success. Found
    by running the real graph; invisible to every stubbed test in this file.
    """
    monkeypatch.setattr(m, "_compiled", {"app": object(), "resumable": True})
    cfg = m._config("t-1")["configurable"]
    assert cfg["thread_id"] == "t-1"
    assert cfg["resumable"] is True

    monkeypatch.setattr(m, "_compiled", {"app": object(), "resumable": False})
    assert m._config("t-1")["configurable"]["resumable"] is False


def test_resumable_is_derived_from_the_checkpointer_not_asserted(monkeypatch):
    """A run configured resumable against a graph with nowhere to checkpoint is
    the failure hitl_gate's own docstring describes, so the two must not be
    able to disagree."""
    import graph.graph as gg
    from shared import config as shared_config

    monkeypatch.setattr(m, "_compiled", {})
    monkeypatch.setattr(shared_config, "STATE_TABLE", "")
    monkeypatch.setattr(gg, "build_graph", lambda checkpointer=None: object())
    assert m._config("t-1")["configurable"]["resumable"] is False


# ------------------------------------------------------- the response cache
def test_a_cache_hit_short_circuits_the_graph(client, monkeypatch):
    """The hit must be served without invoking the graph at all — otherwise the
    cache is a write-through log and buys nothing."""
    c, _ = client
    stored = {"status": "ok", "answer": "cached", "citations": ["90 FR 4628"]}
    monkeypatch.setattr(m.cache, "get", lambda q, p: dict(stored))

    class _NeverCalled:
        def invoke(self, *a, **k):
            raise AssertionError("the graph was invoked on a cache hit")

    monkeypatch.setattr(m, "_compiled", {"app": _NeverCalled(), "resumable": True})
    body = c.post("/query", json={"question": "when?"}).json()
    assert body["answer"] == "cached"
    assert body["cache"] == m.cache.HIT
    assert body["trace_id"]


def test_every_response_reports_its_cache_status(client, monkeypatch):
    """`make demo-parity` records this field per scenario per tier; a response
    that does not say whether it was cached cannot be part of that evidence."""
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    monkeypatch.setattr(m.cache, "get", lambda q, p: None)
    monkeypatch.setattr(m.cache, "put", lambda *a: None)

    monkeypatch.setattr(m.cache, "enabled", lambda: True)
    assert c.post("/query", json={"question": "when?"}).json()["cache"] == m.cache.MISS

    monkeypatch.setattr(m.cache, "enabled", lambda: False)
    assert c.post("/query", json={"question": "when?"}).json()["cache"] == m.cache.DISABLED


def test_bypass_skips_the_read_and_the_write(client, monkeypatch):
    """SPEC/04 control 1. Without this `make demo-parity` measures the cache:
    the two tier runs are minutes apart inside a 1h TTL, so the second is a hit
    returning the first tier's answer and the citations agree by construction."""
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    reads, writes = [], []
    monkeypatch.setattr(m.cache, "get", lambda q, p: reads.append(q) or None)
    monkeypatch.setattr(m.cache, "put", lambda q, p, b: writes.append(q))

    body = c.post("/query", json={"question": "when?", "no_cache": True}).json()
    assert body["cache"] == m.cache.BYPASS
    assert reads == [] and writes == []

    body = c.post("/query", json={"question": "when?"},
                  headers={"x-regdelta-no-cache": "1"}).json()
    assert body["cache"] == m.cache.BYPASS
    assert reads == [] and writes == []


def test_a_paused_response_is_never_written_to_the_cache(client, monkeypatch):
    """It carries thread_id and resume_token — a capability bound to one caller.
    Caching it hands the next caller someone else's thread and the credential
    to resume it."""
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    writes = []
    monkeypatch.setattr(m.cache, "get", lambda q, p: None)
    monkeypatch.setattr(m.cache, "put", lambda q, p, b: writes.append(b))

    body = c.post("/query", json={"question": "are we affected?"}).json()
    assert body["status"] == "needs_input" and body["resume_token"]
    assert writes == [], "a paused response reached the cache"


# ------------------------------------------------- the Lambda transport itself
# Everything above drives the app through TestClient, which never goes through
# Mangum. That gap shipped a deploy where every route returned FastAPI's own
# 404: an HTTP API with a NAMED stage puts the stage segment into the event's
# `rawPath`, so /api/health arrived as `/api/health` and the app has `/health`.
#
# The infra tests asserted the stage NAME and the CloudFront path pattern — the
# shape — and nothing exercised a request, so nothing could see it. These hand
# the handler a real API Gateway v2 event.
def _v2_event(raw_path: str, method: str = "GET", body: str | None = None) -> dict:
    return {
        "version": "2.0", "rawPath": raw_path, "rawQueryString": "",
        "headers": {"host": "x.execute-api.us-west-2.amazonaws.com",
                    "content-type": "application/json"},
        "requestContext": {
            "http": {"method": method, "path": raw_path, "sourceIp": "1.2.3.4",
                     "protocol": "HTTP/1.1"},
            "stage": "api", "apiId": "x", "requestId": "r",
            "domainName": "x.execute-api.us-west-2.amazonaws.com",
            "timeEpoch": 0, "accountId": "1"},
        "body": body, "isBase64Encoded": False,
    }


def test_the_stage_prefix_is_stripped_before_routing(monkeypatch):
    """The deployed failure, reproduced. API_BASE_PATH is what the stack passes
    the function, taken from the same constant it names the stage with."""
    monkeypatch.setenv("API_BASE_PATH", "/api")
    resp = m.handler(_v2_event("/api/health"), None)
    assert resp["statusCode"] == 200, resp["body"]
    assert json.loads(resp["body"])["status"] == "ok"


def test_without_the_prefix_a_default_stage_still_routes(monkeypatch):
    """A `$default` stage prefixes nothing, so the handler must work with
    API_BASE_PATH unset — which is also how it behaves before the stack sets
    it."""
    monkeypatch.delenv("API_BASE_PATH", raising=False)
    resp = m.handler(_v2_event("/health"), None)
    assert resp["statusCode"] == 200, resp["body"]


def test_a_mismatched_prefix_is_a_404_and_not_a_500(monkeypatch):
    """If the two ever drift, the symptom should stay a clean 404 rather than an
    exception — the failure has to be diagnosable from the response."""
    monkeypatch.setenv("API_BASE_PATH", "/wrong")
    resp = m.handler(_v2_event("/api/health"), None)
    assert resp["statusCode"] == 404


# ------------------------------------------------------- daily ceiling (429)
#
# The quota is stubbed at `m.quota` rather than at DynamoDB: what these assert
# is the HTTP CONTRACT the ceiling produces — which status, which header, and
# crucially WHERE in the request path it is claimed. `test_daily_quota.py` owns
# the arithmetic and the conditional write.
def _quota(monkeypatch, raises=None):
    """Replace the quota with a recording stub. Returns the call log."""
    calls = []

    def _consume(now=None):
        calls.append(now)
        if raises is not None:
            raise raises
        return len(calls)

    monkeypatch.setattr(m.quota, "consume", _consume)
    monkeypatch.setattr(m.quota, "seconds_until_reset", lambda now=None: 3600)
    return calls


def test_over_the_daily_ceiling_a_query_is_429(client, monkeypatch):
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    _quota(monkeypatch, raises=m.quota.QuotaExceededError("200 already served"))
    r = c.post("/query", json={"question": "what changed?"})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "3600"
    assert r.json()["retry_after_seconds"] == 3600


def test_an_unverifiable_ceiling_is_503_not_429(client, monkeypatch):
    """The two say different things and must not collapse.

    429 means "come back tomorrow" and reads as the service working. Reporting
    a BROKEN quota that way would hide it exactly as `response_cache`'s
    swallowed AccessDenied hid a dead cache from M05 to M06.
    """
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    _quota(monkeypatch, raises=m.quota.QuotaUnavailableError("dynamodb down"))
    r = c.post("/query", json={"question": "what changed?"})
    assert r.status_code == 503
    assert r.json()["detail"] != ""


def test_a_refused_query_never_reaches_the_graph(client, monkeypatch):
    """The ceiling has to bound SPEND, not just responses.

    A 429 returned after `_app().invoke` would report a limit while paying the
    Bedrock bill it exists to prevent — the one defect that would make the whole
    module decorative.
    """
    c, _ = client
    invoked = []

    class _App:
        def invoke(self, *a, **k):
            invoked.append(1)
            return _answered()

    monkeypatch.setattr(m, "_compiled", {"app": _App(), "resumable": True})
    _quota(monkeypatch, raises=m.quota.QuotaExceededError("full"))
    assert c.post("/query", json={"question": "q"}).status_code == 429
    assert invoked == [], "the graph ran for a request that was refused"


def test_a_cache_hit_does_not_consume_the_allowance(client, monkeypatch):
    """A hit spends no Bedrock, so it must not spend the ceiling either.

    Counting hits would let one caller replaying a single cached question lock
    every other visitor out for the day — a denial of service built out of the
    control installed to prevent one.
    """
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    monkeypatch.setattr(m.cache, "enabled", lambda: True)
    monkeypatch.setattr(m.cache, "get",
                        lambda q, p: {"answer": "stored", "citations": ["x"],
                                      "status": "ok"})
    calls = _quota(monkeypatch)
    assert c.post("/query", json={"question": "q"}).status_code == 200
    assert calls == [], "a cache hit claimed an allowance unit"


def test_a_missed_query_consumes_exactly_one_unit(client, monkeypatch):
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    monkeypatch.setattr(m.cache, "enabled", lambda: False)
    monkeypatch.setattr(m.cache, "get", lambda q, p: None)
    calls = _quota(monkeypatch)
    assert c.post("/query", json={"question": "q"}).status_code == 200
    assert len(calls) == 1


def test_a_refused_resume_does_not_consume_the_allowance(client, monkeypatch):
    """Claiming BEFORE verification would make garbage tokens the cheapest way
    to exhaust the day's ceiling — a denial of service against the control."""
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    calls = _quota(monkeypatch)
    r = c.post("/resume/never-existed", json={"resume_token": "nonsense"})
    assert r.status_code == 404
    assert calls == [], "a refused resume claimed an allowance unit"


def test_an_authorised_resume_consumes_one_unit(client, monkeypatch):
    """A resume runs the graph, so it spends Bedrock and must count. A paused
    question therefore costs two units across its two requests — two model runs,
    which is the honest number."""
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    calls = _quota(monkeypatch)
    first = c.post("/query", json={"question": "are we affected?"}).json()
    _stub_graph(monkeypatch, _answered())
    c.post(f"/resume/{first['thread_id']}",
           json={"resume_token": first["resume_token"], "answer": "yes"})
    assert len(calls) == 2


def test_over_the_ceiling_a_resume_is_429_and_never_reaches_the_graph(client, monkeypatch):
    """The ordering decision in `/resume`, pinned so a change to it fails loudly.

    The diff spends twenty lines arguing that claiming AFTER token verification
    is right despite narrowing SPEC/04's indistinguishability — an exhausted
    quota answers 429 to a valid token where an invalid one still gets the
    opaque 404. That trade-off was reviewed and accepted; what was missing was
    anything asserting the behaviour it describes, so a later refactor could
    have silently collapsed the 429 into the 404 (losing the honest signal) or
    the 404 into the 429 (leaking token validity to everyone). Both directions
    now fail here. eng-code-reviewer L4.
    """
    c, _ = client
    _stub_graph(monkeypatch, _paused())
    first = c.post("/query", json={"question": "are we affected?"}).json()

    invoked = []

    class _App:
        def invoke(self, *a, **k):
            invoked.append(1)
            return _answered()

    monkeypatch.setattr(m, "_compiled", {"app": _App(), "resumable": True})
    _quota(monkeypatch, raises=m.quota.QuotaExceededError("full"))

    r = c.post(f"/resume/{first['thread_id']}",
               json={"resume_token": first["resume_token"], "answer": "yes"})
    assert r.status_code == 429
    assert invoked == [], "the graph ran for a resume that was refused"
    # And the other half of the oracle: an unauthorised resume still 404s
    # rather than revealing the ceiling.
    assert c.post("/resume/never-existed",
                  json={"resume_token": "nonsense"}).status_code == 404


def test_a_refusal_emits_a_metric_with_its_reason(client, monkeypatch):
    """The merge blocker, pinned.

    Both refusal paths used to return before `_request_metrics`, so a 503 storm
    presented on the dashboard as ZERO QUERIES — indistinguishable from a quiet
    day on a low-traffic demo, under a module whose own argument is against
    controls nobody can see fire. `reason` is a dimension because
    `observability.QuotaUnavailableAlarm` fires on `unavailable` only:
    `exhausted` is the ceiling working. security-reviewer F1, eng-code-reviewer M3.
    """
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    emitted = []
    monkeypatch.setattr("shared.observability.emit",
                        lambda metrics, dims, props=None, **kw: emitted.append((metrics, dims)))

    _quota(monkeypatch, raises=m.quota.QuotaExceededError("full"))
    c.post("/query", json={"question": "q"})
    _quota(monkeypatch, raises=m.quota.QuotaUnavailableError("dynamodb down"))
    c.post("/query", json={"question": "q"})

    refusals = [(mt, d) for mt, d in emitted if "QuotaRefused" in mt]
    assert [d["reason"] for _, d in refusals] == ["exhausted", "unavailable"]


def test_the_503_does_not_tell_clients_to_come_back_tomorrow(client, monkeypatch):
    """429 and 503 are kept apart in the status code; the header must agree.

    `seconds_until_reset()` on the 503 branch meant a two-second DynamoDB blip
    at 00:30 UTC handed every well-behaved client `Retry-After: 84600` and
    emptied the demo for the rest of the day over a fault that had healed.
    security-reviewer F4.
    """
    c, _ = client
    _stub_graph(monkeypatch, _answered())
    monkeypatch.setattr(m.quota, "seconds_until_reset", lambda now=None: 84600)

    monkeypatch.setattr(m.quota, "consume",
                        lambda now=None: (_ for _ in ()).throw(
                            m.quota.QuotaExceededError("full")))
    assert c.post("/query", json={"question": "q"}).headers["Retry-After"] == "84600"

    monkeypatch.setattr(m.quota, "consume",
                        lambda now=None: (_ for _ in ()).throw(
                            m.quota.QuotaUnavailableError("blip")))
    r = c.post("/query", json={"question": "q"})
    assert int(r.headers["Retry-After"]) <= 60, "a transient fault must not cost a day"
