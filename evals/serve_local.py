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


def answer_agent(question: str, profile: dict) -> dict:
    """Run the SPEC/03 graph and shape its state for the eval runner.

    `run_evals.check()` reads `answer_rows`, `answer`, `citations` and `status`
    (run_evals.py:69-102), so the mapping below is the contract between the
    graph and the scorecard. Everything else on the response is provenance.

    NO CHECKPOINTER here, deliberately. The local shim has no DynamoDB, and a
    graph compiled without one still runs to completion and still reports
    `pending_review` — what it cannot do is be RESUMED. That is the honest
    boundary of what this shim measures: SPEC/03's HITL criterion has two
    halves, and the local path covers the pause, not the resume. The resume
    half needs graph.checkpoint.DynamoDBSaver and a `/resume/{id}` route, which
    is SPEC/04's surface.
    """
    from dataclasses import asdict

    from graph.graph import build_graph
    from graph.nodes import _cache_state
    from retrieval import router
    from shared import config

    if "app" not in _graph:
        _graph["app"] = build_graph()

    state = _graph["app"].invoke({"query": question, "company_profile": profile})
    rows = [asdict(r) for r in state.get("verdict_rows") or []]

    return {
        "answer": state.get("answer", ""),
        "answer_rows": rows,
        "citations": state.get("citations") or [],
        "confidence": state.get("confidence"),
        "status": state.get("status", "degraded"),
        "mode": "agent",
        "review_reason": state.get("review_reason"),
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

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
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
    print(f"serving POST /query?mode=naive|agent on http://127.0.0.1:{args.port}",
          flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
