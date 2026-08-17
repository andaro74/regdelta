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
    """A client whose graph is stubbed and whose token store is in memory."""
    store: dict[str, str] = {}
    monkeypatch.setattr(m, "_store_token", lambda tid, dig: store.__setitem__(tid, dig))
    monkeypatch.setattr(m, "_load_token", lambda tid: store.get(tid))
    return TestClient(m.app), store


def _stub_graph(monkeypatch, state: dict):
    """Point the app's late-bound `build_graph` at a fixed final state."""
    import graph.graph as gg

    class _App:
        def invoke(self, *a, **k):
            return state

    monkeypatch.setattr(gg, "build_graph", lambda *a, **k: _App())


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
    import graph.graph as gg

    class _Boom:
        invoke = explode
    monkeypatch.setattr(gg, "build_graph", lambda *a, **k: _Boom())
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
