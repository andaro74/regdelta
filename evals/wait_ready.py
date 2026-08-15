#!/usr/bin/env python
"""Block until the loopback shim answers /health, or fail loudly.

`make agent-evals` and `make baseline` background evals/serve_local.py and then
slept a fixed 2-3 seconds before running the golden set. A fixed sleep cannot
tell "still starting" from "never started", and on 2026-08-15 it did not: the
shim exited immediately on an unset VECTOR_BUCKET, the sleep expired, the run
made ten connection-refused requests and recorded a 0/10 scorecard under a real
commit sha. Both cards were false evidence and had to be withdrawn by hand.

run_evals.py now refuses to record a run where nothing reached the API, which is
the durable half of the fix. This is the other half: fail before spending the
Bedrock calls, and say why.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

TIMEOUT_S = 20.0
POLL_S = 0.4


def main() -> int:
    if len(sys.argv) < 2:
        return print("usage: wait_ready.py URL [timeout_s]", file=sys.stderr) or 2
    url = sys.argv[1].rstrip("/") + "/health"
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else TIMEOUT_S

    deadline = time.monotonic() + limit
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return 0
                last = f"HTTP {r.status}"
        except urllib.error.HTTPError as e:      # up, but unhappy — still up
            return 0 if e.code < 500 else _sleep(f"HTTP {e.code}")
        except Exception as e:                   # noqa: BLE001 — not up yet
            last = f"{type(e).__name__}: {e}"
        time.sleep(POLL_S)

    print(f"\nthe local shim never came up at {url} after {limit:.0f}s "
          f"(last: {last}).\n"
          f"It exits on startup if its environment is incomplete — the usual "
          f"cause is VECTOR_BUCKET or CORPUS_BUCKET being unset. Run it in the "
          f"foreground to see the reason:\n\n"
          f"    python evals/serve_local.py --port 8000\n\n"
          f"Not running the golden set: it would only record connection errors.",
          file=sys.stderr)
    return 1


def _sleep(msg: str) -> int:
    time.sleep(POLL_S)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
