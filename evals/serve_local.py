#!/usr/bin/env python3
"""Local eval target — stdlib HTTP shim exposing POST /query?mode=naive.

SPEC/00b requires the baseline to be reachable at POST /query?mode=naive so
the golden set can target it. The deployed API Gateway is SPEC/04 work, so
until M04 exists this shim is how M00b (and any pre-M04 milestone) gets
scored. It adds no dependency: stdlib http.server only. When SPEC/04 lands,
src/api/api.py becomes the permanent target and this stays as the offline
path.

    python evals/serve_local.py &
    python evals/run_evals.py --mode naive --api-url http://127.0.0.1:8000

Requires VECTOR_BUCKET (and AWS credentials) in the environment.
"""
import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

MAX_BODY = 64 * 1024

_graph: dict = {}


def _app():
    """Compile once, with a checkpointer when there is somewhere to checkpoint.

    STATE_TABLE is what decides. With it, a paused run persists and
    `/resume/{thread_id}` can continue it — SPEC/03's HITL criterion has two
    halves and this is the second. Without it the graph still runs and still
    reports `pending_review`; it simply cannot be resumed, and `resumable` is
    left off so `hitl_gate` reports instead of calling `interrupt()`, which
    would raise with no checkpointer behind it.
    """
    if "app" not in _graph:
        from graph.checkpoint import DynamoDBSaver
        from graph.graph import build_graph
        from shared import config

        saver = DynamoDBSaver() if config.STATE_TABLE else None
        _graph["app"] = build_graph(checkpointer=saver)
        _graph["resumable"] = saver is not None
    return _graph["app"]


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id,
                             "resumable": _graph.get("resumable", False)}}


def answer_agent(question: str, profile: dict) -> dict:
    """Start a run. Returns the answer, or the pause and how to resume it."""
    import uuid

    thread_id = str(uuid.uuid4())
    state = _app().invoke({"query": question, "company_profile": profile},
                          _config(thread_id))
    return _shape(state, thread_id)


def resume_agent(thread_id: str, decision: dict) -> dict:
    """Continue a paused run from its checkpoint.

    SPEC/04 owns the real `POST /resume/{checkpoint_id}`; this is the same
    contract on the offline path, so the HITL criterion can be demonstrated
    before that milestone exists. The thread id IS the checkpoint id here —
    LangGraph keys checkpoints by thread, and `DynamoDBSaver` stores every
    superstep under `THREAD#<id>`, so resuming needs nothing else.
    """
    from langgraph.types import Command

    if not _graph.get("resumable", False):
        return {"error": "not resumable: STATE_TABLE is unset, so this run was "
                         "never checkpointed", "status": "degraded"}
    state = _app().invoke(Command(resume=decision), _config(thread_id))
    return _shape(state, thread_id)


def _shape(state: dict, thread_id: str) -> dict:
    """Map graph state onto the response the eval runner reads.

    `run_evals.check()` reads `answer_rows`, `answer`, `citations` and `status`
    (run_evals.py:69-102), so this mapping is the contract between the graph
    and the scorecard. Everything else is provenance.
    """
    from dataclasses import asdict

    from graph.nodes import _cache_state
    from retrieval import router
    from shared import config

    rows = [asdict(r) for r in state.get("verdict_rows") or []]

    # A paused run reports the pause and what would release it. The status is
    # taken from the interrupt payload rather than from state, because state
    # holds whatever the last completed node wrote — `hitl_gate` has not
    # returned yet, so its status is not there to read.
    paused = (state.get("__interrupt__") or [None])[0]
    request = dict(getattr(paused, "value", None) or {}) if paused else {}

    return {
        "thread_id": thread_id,
        "answer": state.get("answer", ""),
        "answer_rows": rows,
        "citations": state.get("citations") or [],
        "confidence": state.get("confidence"),
        "status": request.get("status") or state.get("status", "degraded"),
        "mode": "agent",
        "review_reason": request.get("reason") or state.get("review_reason"),
        "paused": bool(paused),
        # What a reviewer has to send back for the resume to be worth anything.
        "needs": request.get("needs"),
        "resume_with": (f"POST /resume/{thread_id}" if paused else None),
        # A model that reached for authority the sources did not carry is a
        # finding about the answer, not noise — q03 is why it is surfaced.
        "dropped_citations": state.get("dropped_citations") or [],
        "provenance": {
            "model_fast": config.MODEL_FAST,
            "model_verdict": config.MODEL_VERDICT,
            "tier": router.active_tier(),
            "top_k": config.NAIVE_TOP_K,
            "rerank": config.RERANK,
            "lexical_lane": config.RETRIEVAL_LEXICAL_LANE,
            "prompt_cache": config.PROMPT_CACHE and _cache_state.get("supported", True),
            "prompt_cache_note": _cache_state.get("reason"),
            # NOTHING PER-QUESTION BELONGS HERE. run_evals.py keeps one
            # `provenance` for the whole card and overwrites it on every
            # question (run_evals.py:136), so a per-question count recorded
            # here is silently the LAST question's while reading as the run's.
            # Counts of retrieved chunks, timeline facts and crossrefs are on
            # each /query response, which is where they are true.
        },
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/health":
            return self._send(200, {"tier": "s3vectors", "surface": "local-shim"})
        self._send(404, {"error": "not found"})

    def _resume(self, thread_id: str):
        """POST /resume/{thread_id} — SPEC/03's second HITL half.

        The body is the reviewer's decision: `{"company_profile": {...}}` to
        supply what was missing, or `{"reviewer_decision": "approve"|"reject"}`
        to release or refuse the draft. SPEC/04 owns the deployed route; this
        is the same contract offline so the criterion can be demonstrated
        before that milestone exists.
        """
        thread_id = urllib.parse.unquote(thread_id)
        if not thread_id or "/" in thread_id:
            return self._send(400, {"error": "resume needs a single thread id"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self._send(400, {"error": "bad Content-Length"})
            decision = json.loads(self.rfile.read(length))
            if not isinstance(decision, dict):
                return self._send(400, {"error": "decision must be an object"})
        except (ValueError, TypeError, AttributeError):
            return self._send(400, {"error": "malformed request body"})

        try:
            self._send(200, resume_agent(thread_id, decision))
        except Exception as e:  # noqa: BLE001 — surface as a failed resume
            # Detail to stderr only, same as /query: botocore error strings
            # embed the account id, role ARN and table name.
            sys.stderr.write(f"resume failed: {type(e).__name__}: {e}\n")
            self._send(500, {"error": "internal error", "type": type(e).__name__})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/resume/"):
            return self._resume(url.path[len("/resume/"):])
        if url.path != "/query":
            return self._send(404, {"error": "not found"})

        mode = urllib.parse.parse_qs(url.query).get("mode", ["agent"])[0]
        if mode not in ("naive", "agent"):
            # Do not silently answer as the baseline — that would let an
            # unbuilt agent inherit the control's scorecard. The guard predates
            # mode=agent and still holds: an unknown mode is refused rather
            # than defaulted to something that scores.
            return self._send(501, {"error": f"unknown mode {mode!r}; "
                                             "expected naive or agent"})

        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self._send(400, {"error": "bad Content-Length"})
            body = json.loads(self.rfile.read(length))
            question = body.get("question")
            profile = body.get("company_profile") or {}
            if not isinstance(question, str) or not question.strip():
                return self._send(400, {"error": "question must be a non-empty string"})
            if not isinstance(profile, dict):
                return self._send(400, {"error": "company_profile must be an object"})
        except (ValueError, TypeError, AttributeError):
            return self._send(400, {"error": "malformed request body"})

        try:
            if mode == "agent":
                return self._send(200, answer_agent(question, profile))
            from baseline.naive import answer_naive
            self._send(200, answer_naive(question))
        except Exception as e:  # noqa: BLE001 — surface as a failed answer
            # Detail to stderr only: botocore error strings embed the account
            # id, role ARN and bucket name. This handler is the template
            # SPEC/04 will copy for an internet-facing surface.
            sys.stderr.write(f"query failed: {type(e).__name__}: {e}\n")
            self._send(500, {"error": "internal error", "type": type(e).__name__})

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    # Fail at boot, not per question: without this the whole golden set
    # returns 500s and records as a 0/10 "baseline result".
    from shared import config
    if not config.VECTOR_BUCKET:
        sys.exit("VECTOR_BUCKET is unset — the golden set would record 0/10.")

    # Loopback only, deliberately. Never add a --host/--bind flag: this
    # shim has no authentication.
    #
    # BIND FIRST, THEN ANNOUNCE, AND REFUSE TO SHARE THE PORT. Both halves of
    # that are corrections, and together they cost a mislabelled scorecard.
    #
    # http.server.HTTPServer sets `allow_reuse_address = 1`. On Linux that
    # only relaxes TIME_WAIT; on WINDOWS it lets a second process bind an
    # address another process is actively LISTENING on, and the two then split
    # incoming connections. The banner also printed BEFORE the bind, so a
    # second instance announced success either way.
    #
    # What that produced: a stale shim survived its kill, the replacement
    # printed the new banner and bound alongside it, and the golden run was
    # served by the OLD code — so the recorded card carried the previous
    # commit's provenance under the new commit's sha. That is the same class
    # of defect as recording from a dirty tree, arriving through the port
    # instead of through git, and it is exactly what a scorecard must not do.
    class _ExclusiveHTTPServer(HTTPServer):
        allow_reuse_address = False

    server = _ExclusiveHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving POST /query?mode=naive|agent on http://127.0.0.1:{args.port}",
          flush=True)
    server.serve_forever()
