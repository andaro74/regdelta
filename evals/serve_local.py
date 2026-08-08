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
        if mode != "naive":
            # Do not silently answer as the baseline — that would let an
            # unbuilt agent inherit the control's scorecard.
            return self._send(501, {"error": "mode=agent is SPEC/03; "
                                             "only mode=naive is served here"})

        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self._send(400, {"error": "bad Content-Length"})
            question = json.loads(self.rfile.read(length)).get("question")
            if not isinstance(question, str) or not question.strip():
                return self._send(400, {"error": "question must be a non-empty string"})
        except (ValueError, TypeError, AttributeError):
            return self._send(400, {"error": "malformed request body"})

        try:
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
    print(f"serving POST /query?mode=naive on http://127.0.0.1:{args.port}",
          flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
