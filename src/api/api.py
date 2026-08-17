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


@router.post("/query")
def query(payload: dict, request: Request) -> dict:
    """Answer a question. Mints a resume capability if the run pauses."""
    from graph.graph import build_graph

    trace_id = _trace_id(request)
    question = str(payload.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400,
                            content={"detail": "question is required",
                                     "trace_id": trace_id})

    thread_id = str(uuid.uuid4())
    state = build_graph().invoke(
        {"query": question, "company_profile": payload.get("company_profile") or {}},
        _config(thread_id))

    body = _shape(state, thread_id)
    body["trace_id"] = trace_id

    # The capability is minted ONLY for a run that actually paused, and returned
    # exactly once. A token on every response would be a credential handed out
    # for nothing, and SPEC/04's contract says these fields are present only
    # when status is needs_input or pending_review.
    if body.get("status") in ("needs_input", "pending_review"):
        token, stored = rt.mint()
        _store_token(thread_id, stored)
        body["resume_token"] = token
    else:
        body.pop("thread_id", None)
    return body


@router.post("/resume/{thread_id}")
def resume(thread_id: str, payload: dict, request: Request):
    """Continue a paused run. Refuses identically for every reason it can refuse."""
    from langgraph.types import Command

    from graph.graph import build_graph

    trace_id = _trace_id(request)

    if rt.enabled():
        try:
            rt.verify(payload.get("resume_token"), _load_token(thread_id))
        except rt.ResumeDeniedError as denied:
            return _refuse(trace_id, denied.reason)

    decision = {k: v for k, v in payload.items() if k != "resume_token"}
    try:
        state = build_graph().invoke(Command(resume=decision), _config(thread_id))
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
    return {"configurable": {"thread_id": thread_id}}


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
