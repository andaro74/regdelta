"""FastAPI surface (SPEC/04): POST /query, POST /resume/{thread_id}, GET /health.

ONE APP, TWO TRANSPORTS. Mangum adapts this same object to Lambda; the tests
drive it in-process with `fastapi.testclient`. There is deliberately no second
HTTP implementation — `evals/serve_local.py` already exists as the offline shim
and a second one would be a second thing to keep honest.

WHAT THIS FILE DOES NOT DO. It does not decide anything about an answer. The
graph produces the verdict; this maps it onto HTTP and enforces one access
rule. `_shape` is intentionally the same mapping the shim uses, because
`run_evals.check()` reads `answer_rows`, `answer`, `citations` and `status`,
and a second mapping is a second contract to drift.

THE ONE ACCESS RULE. `/resume` serves a checkpoint only to a caller holding the
token minted with it (SPEC/04, "`/resume` is not an open door"). `/query`
stays open: it answers questions about public FDA rules. `/resume` hands back
one asker's checkpointed state — their company profile and the passages
retrieved for them — and those are not alike.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from api import resume_token as rt

log = logging.getLogger("regdelta.api")

app = FastAPI(title="RegDelta", version="0.4.0")
router = APIRouter()

# THE ONLY BODY /resume EVER RETURNS ON REFUSAL.
#
# SPEC/04 requires all four rejection conditions — another thread's token, a
# malformed token, no token, a thread that never existed — to be
# indistinguishable to the caller. Rendering them through one constant rather
# than four call sites is what makes that structural instead of a convention
# somebody has to remember. `trace_id` is filled per request; nothing else varies.
_REFUSAL = "not found"


def _refuse(trace_id: str, reason: str) -> JSONResponse:
    """One response for every refusal; the distinguishing reason goes to the log.

    The asymmetry is the spec's ruling and is load-bearing: the opaque 404 was
    accepted ONLY because the reason is required to exist against the trace_id.
    Without the log line an operator cannot tell a legitimate resume failure
    from an attack, and the honest ruling would have been against the 404.
    """
    log.warning("resume refused trace_id=%s reason=%s", trace_id, reason)
    return JSONResponse(status_code=404,
                        content={"detail": _REFUSAL, "trace_id": trace_id})


@router.get("/health")
def health() -> dict:
    """Which retrieval tier is live, per SPEC/04.

    Resolved through the router rather than read from configuration, because
    the tier is a property of what is DEPLOYED (an SSM parameter) and a config
    value would report what someone intended rather than what is answering.
    """
    from retrieval import router as retrieval_router

    try:
        tier = retrieval_router.active_tier()
    except Exception as e:                      # noqa: BLE001 — health must not 500
        # A health endpoint that fails when a dependency fails cannot report
        # that the dependency failed.
        log.warning("active_tier() failed: %s", e)
        tier = "unknown"
    return {"status": "ok", "tier": tier}


_compiled: dict = {}


def _app():
    """The graph, compiled ONCE, with a checkpointer when there is one.

    Two defects this fixes, both found by running the API against the real
    graph rather than a stub — every test in tests/test_api.py stubs
    `build_graph`, so neither was visible there.

    1. `build_graph()` with no argument compiles WITHOUT a checkpointer.
       `/query` still pauses and still returns an `__interrupt__`, so the
       response looked correct — but nothing was persisted, and `/resume` then
       built a SECOND graph that found no checkpoint and raised. The end-to-end
       run returned 404 on a resume holding the correct token.
    2. It recompiled the graph on every request. The shim has compiled once
       since M03; this had not.

    `resumable` is false when STATE_TABLE is unset. That is not an error — the
    graph still runs and still reports `needs_input` — it simply cannot be
    resumed, and `/query` must not hand out a token promising otherwise.
    """
    if "app" not in _compiled:
        from graph.graph import build_graph
        from shared import config

        saver = None
        if config.STATE_TABLE:
            from graph.checkpoint import DynamoDBSaver
            saver = DynamoDBSaver()
        _compiled["app"] = build_graph(checkpointer=saver)
        _compiled["resumable"] = saver is not None
        log.info("graph compiled, resumable=%s", _compiled["resumable"])
    return _compiled["app"]


def _resumable() -> bool:
    _app()
    return bool(_compiled.get("resumable"))


@router.post("/query")
def query(payload: dict, request: Request) -> dict:
    """Answer a question. Mints a resume capability if the run pauses."""
    trace_id = _trace_id(request)
    question = str(payload.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400,
                            content={"detail": "question is required",
                                     "trace_id": trace_id})

    thread_id = str(uuid.uuid4())
    state = _app().invoke(
        {"query": question, "company_profile": payload.get("company_profile") or {}},
        _config(thread_id))

    body = _shape(state, thread_id)
    body["trace_id"] = trace_id

    # The capability is minted ONLY for a run that actually paused, and returned
    # exactly once. A token on every response would be a credential handed out
    # for nothing, and SPEC/04's contract says these fields are present only
    # when status is needs_input or pending_review.
    #
    # And only when the run is actually RESUMABLE. With no STATE_TABLE there is
    # no checkpoint behind the pause, so a token would be a promise the next
    # request cannot keep — the caller would hold a credential and get a 404
    # that looks like a refusal rather than a missing capability. Say so in the
    # body instead.
    if body.get("status") in ("needs_input", "pending_review"):
        if _resumable():
            token, stored = rt.mint()
            _store_token(thread_id, stored)
            body["resume_token"] = token
        else:
            body["resumable"] = False
            body["review_reason"] = (
                (body.get("review_reason") or "")
                + " (not resumable: STATE_TABLE is unset, so this run was never "
                  "checkpointed)").strip()
    else:
        body.pop("thread_id", None)
    return body


@router.post("/resume/{thread_id}")
def resume(thread_id: str, payload: dict, request: Request):
    """Continue a paused run. Refuses identically for every reason it can refuse."""
    from langgraph.types import Command

    trace_id = _trace_id(request)

    if rt.enabled():
        try:
            rt.verify(payload.get("resume_token"), _load_token(thread_id))
        except rt.ResumeDeniedError as denied:
            return _refuse(trace_id, denied.reason)

    decision = {k: v for k, v in payload.items() if k != "resume_token"}
    try:
        state = _app().invoke(Command(resume=decision), _config(thread_id))
    except Exception as e:                      # noqa: BLE001 — see below
        # A thread that never existed reaches LangGraph as an empty checkpoint
        # and surfaces however that library chooses to surface it. It must not
        # be distinguishable from a wrong token, so it lands in the SAME
        # refusal — not a 500, which would answer "this thread exists" by
        # failing differently.
        return _refuse(trace_id, f"resume failed: {type(e).__name__}: {e}"[:300])

    body = _shape(state, thread_id)
    body["trace_id"] = trace_id
    return body


app.include_router(router)


# --------------------------------------------------------------------- glue
def _trace_id(request: Request) -> str:
    """Correlates the response a caller sees with the reason in the log."""
    return request.headers.get("x-amzn-trace-id") or str(uuid.uuid4())


def _config(thread_id: str) -> dict:
    """Run-time configuration for one invocation.

    `resumable` is NOT decoration. `hitl_gate` reads it out of `configurable`
    and, when it is absent or false, takes the branch that reports the review
    status and STOPS — it never calls `interrupt()`. Omitting it therefore
    produces a response that looks entirely correct (`status: needs_input`,
    with a reason) while no checkpoint is ever written and nothing is actually
    pausable. The resume then re-runs from the top and pauses again in the same
    way, returning 200 with the same body, which reads like success.

    That is what the first end-to-end run against the real graph did, and no
    unit test could see it: the tests stub the graph, and a stub does not care
    what is in `configurable`.

    It is derived from whether a checkpointer exists rather than passed in,
    because the two must not be able to disagree — a run configured resumable
    against a graph with nowhere to checkpoint is the failure `hitl_gate`'s own
    docstring describes.
    """
    return {"configurable": {"thread_id": thread_id, "resumable": _resumable()}}


def _shape(state: dict, thread_id: str) -> dict:
    """Graph state onto the response body.

    Deliberately the same mapping as evals/serve_local.py:_shape. That file is
    the offline shim the golden set runs against, and if these two disagree
    then `make evals` and the deployed API are measuring different things.
    """
    from dataclasses import asdict

    rows = [asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r)
            for r in state.get("verdict_rows") or []]
    paused = (state.get("__interrupt__") or [None])[0]
    request = dict(getattr(paused, "value", None) or {}) if paused else {}

    return {
        "thread_id": thread_id,
        "answer": state.get("answer", ""),
        "answer_rows": rows,
        "citations": state.get("citations") or [],
        "confidence": state.get("confidence"),
        "status": request.get("status") or state.get("status", "degraded"),
        "review_reason": request.get("reason") or state.get("review_reason", ""),
    }


def _token_table():
    import boto3

    from shared import config

    return boto3.resource("dynamodb", region_name=config.REGION).Table(config.STATE_TABLE)


def _store_token(thread_id: str, stored_digest: str) -> None:
    """Persist the DIGEST beside the checkpoint it authorises.

    Same partition as the checkpoint (`THREAD#<id>`) so `delete_thread` sweeps
    it with everything else — a token that outlives its checkpoint is a
    credential for something that no longer exists.
    """
    from graph.checkpoint import CHECKPOINT_TTL_DAYS, _now

    _token_table().put_item(Item={
        "pk": f"THREAD#{thread_id}",
        "sk": "RESUME_TOKEN",
        "digest": stored_digest,
        "ttl": _now() + CHECKPOINT_TTL_DAYS * 86400,
    })


def _load_token(thread_id: str) -> str | None:
    """The stored digest, or None. None is a refusal, never an error."""
    try:
        item = _token_table().get_item(
            Key={"pk": f"THREAD#{thread_id}", "sk": "RESUME_TOKEN"}).get("Item")
    except Exception as e:                      # noqa: BLE001
        # An unreadable table must deny rather than admit. Failing open here
        # would turn a transient DynamoDB error into an open door.
        log.warning("resume token lookup failed for %s: %s", thread_id, e)
        return None
    return str(item["digest"]) if item and item.get("digest") else None


def handler(event, context):
    """Lambda entry point. Mangum wraps the app above."""
    from mangum import Mangum

    return Mangum(app, lifespan="off")(event, context)
