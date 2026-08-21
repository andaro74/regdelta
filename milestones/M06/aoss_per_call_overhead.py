"""What Tier B's client pays per call that Tier A's does not.

Offline, no AWS, no network: both quantities below are LOCAL work that happens
inside `router.retrieve()` — the interval SPEC/06's clause defines the p95
over — on every AOSS request and on no S3 Vectors request.

  1. `botocore.session.get_session().get_credentials()` per request.
     `get_session()` constructs a NEW Session, which loads botocore's JSON
     service data and runs the credential resolver chain. boto3 clients build
     one session once and reuse the resolved credentials.

  2. SigV4 signing per request — shared by both, so not a difference; measured
     anyway so the first number is not mistaken for it.

The TCP+TLS handshake per call is the third and largest, and it is NOT
measurable here: `urllib.request.urlopen` opens a new connection every call
because nothing installs an opener with a pool, while botocore holds a urllib3
pool. That one is structural and is reported as such.
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import botocore.session  # noqa: E402
from botocore.auth import SigV4Auth  # noqa: E402
from botocore.awsrequest import AWSRequest  # noqa: E402

N = 30


def timed(fn, n=N):
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


# What aoss_client.request does, once per call.
per_call = timed(lambda: botocore.session.get_session().get_credentials())

# What a pooled client does instead: resolve once, reuse.
_session = botocore.session.get_session()
_creds = _session.get_credentials()
reused = timed(lambda: _creds.get_frozen_credentials())


def sign():
    aws = AWSRequest(method="POST", url="https://x.us-west-2.aoss.amazonaws.com/i/_search",
                     data=b"{}", headers={"Content-Type": "application/json"})
    SigV4Auth(_creds.get_frozen_credentials(), "aoss", "us-west-2").add_auth(aws)


signing = timed(sign)


def line(label, samples):
    print(f"{label:52s} median {statistics.median(samples):8.3f} ms   "
          f"max {max(samples):8.3f} ms")


print(f"n = {N} per row, local CPU only, no network\n")
line("get_session().get_credentials()  [per AOSS call]", per_call)
line("frozen credentials from a reused session", reused)
line("SigV4 signing  [both tiers pay this]", signing)
overhead = statistics.median(per_call) - statistics.median(reused)
print(f"\nper-call overhead AOSS pays and S3 Vectors does not: "
      f"{overhead:.3f} ms median")

#: The clause's pre-registered top step, calls per second.
TOP_RATE = 90
print(f"at {TOP_RATE} calls/s that is {TOP_RATE * overhead:.0f} ms of "
      f"GIL-bound CPU per second of wall clock, in a ~1.2-vCPU Lambda")

Path(__file__).with_suffix(".json").write_text(json.dumps({
    "n": N,
    "basis": "local CPU only, no network, no AWS call",
    "get_session_get_credentials_ms": {
        "median": round(statistics.median(per_call), 3),
        "max": round(max(per_call), 3)},
    "frozen_from_reused_session_ms": {
        "median": round(statistics.median(reused), 3),
        "max": round(max(reused), 3)},
    "sigv4_signing_ms_both_tiers": {
        "median": round(statistics.median(signing), 3),
        "max": round(max(signing), 3)},
    "aoss_only_overhead_ms_median": round(overhead, 3),
    "cpu_ms_per_wall_second_at_90_calls_s": round(TOP_RATE * overhead),
    "fixed_in": "src/retrieval/aoss_client.py, _credentials()",
    "not_measured_here": "the TCP+TLS handshake urllib.request.urlopen pays on "
                         "every call because nothing installs an opener with a "
                         "pool, while botocore holds a urllib3 pool per client. "
                         "Structural, larger, not measurable offline, and "
                         "raised with the seat rather than changed "
                         "unilaterally in the week Tier B is disposed of.",
}, indent=2) + "\n", encoding="utf-8")
