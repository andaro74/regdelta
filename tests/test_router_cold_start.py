"""The tier lookup on a COLD process — where `monotonic()` starts near zero.

THE DEFECT. `router._cache` starts `{"endpoint": None, "at": 0.0}` and the
refresh is guarded by `now - _cache["at"] > _TTL`. With `at` seeded to 0.0 that
reads `time.monotonic() > 60.0`, which is not a staleness check at all — it is a
check on how long the MACHINE has been up.

On any laptop or long-lived server `monotonic()` is thousands of seconds, so the
first lookup always fires and the code looks correct. Every test in this repo ran
that way. In a Lambda microVM the clock starts near zero at boot, so for the
first ~60 seconds of a container's life `active_endpoint()` returns the seeded
`None` WITHOUT EVER CALLING SSM — and the router routes to S3 Vectors while SSM
holds an AOSS endpoint, silently, with no fallback_reason because nothing
failed.

Observed on the deployed API at M04, in this order: `s3vectors` on a fresh
container, `aoss` two minutes later on the same warm one, then `s3vectors` again
immediately after a redeploy replaced it. `GET /health` reports the same wrong
answer, because it reads the same function — so the endpoint that exists to say
which tier is live is unable to notice.

This is the third form of the same M04 defect and the worst of them: the first
two produced a false SCORECARD, this one produces false ROUTING. A cold Lambda
answers real user questions on the wrong tier, and the response now carries
`tier: s3vectors` truthfully — the answer is honest about a routing decision
that was itself made on stale state.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from retrieval import router  # noqa: E402

ENDPOINT = "https://abc123.us-west-2.aoss.amazonaws.com"


@pytest.fixture
def cold(monkeypatch):
    """A process that has just started: monotonic near zero, cache unseeded."""
    calls = []

    class FakeSsm:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, Name):  # noqa: N803 — boto3's own kwarg
            calls.append(Name)
            return {"Parameter": {"Value": ENDPOINT}}

    monkeypatch.setattr(router, "_ssm", FakeSsm())
    # EXACTLY the module's own import-time seed, so these tests exercise the
    # real cold-start state rather than one invented to fail.
    monkeypatch.setattr(router, "_cache", {"endpoint": None, "at": 0.0})
    return calls


def test_a_cold_process_reads_ssm_on_the_first_call(monkeypatch, cold):
    """1.5 seconds since boot is a Lambda cold start. The old guard skipped the
    lookup entirely for the first 60 of them."""
    monkeypatch.setattr(router.time, "monotonic", lambda: 1.5)
    assert router.active_endpoint() == ENDPOINT
    assert cold == ["/regdelta/search/endpoint"], \
        "SSM was never consulted; the seeded None was returned as an answer"


def test_a_cold_process_reports_the_configured_tier_not_the_default(monkeypatch, cold):
    """The consequence in the terms that matter: real questions routed to the
    wrong tier for the first minute of every container's life."""
    monkeypatch.setattr(router.time, "monotonic", lambda: 0.4)
    assert router.active_tier() == "aoss"


def test_the_lookup_is_still_cached_within_the_ttl(monkeypatch, cold):
    """The cache has to keep working — it exists because active_endpoint() is
    called per request and an SSM read per request is a real cost."""
    monkeypatch.setattr(router.time, "monotonic", lambda: 1.5)
    router.active_endpoint()
    monkeypatch.setattr(router.time, "monotonic", lambda: 20.0)
    router.active_endpoint()
    assert len(cold) == 1, f"re-read SSM inside the TTL: {cold}"


def test_the_lookup_refreshes_after_the_ttl(monkeypatch, cold):
    monkeypatch.setattr(router.time, "monotonic", lambda: 1.5)
    router.active_endpoint()
    monkeypatch.setattr(router.time, "monotonic", lambda: 1.5 + router._TTL + 1)
    router.active_endpoint()
    assert len(cold) == 2, "never refreshed; a make up/down flip would go unseen"


def test_reset_cache_forces_a_read_on_a_cold_clock(monkeypatch, cold):
    """`reset_cache()` is what `make demo-parity` calls between tier runs — both
    halves happen in one process inside one TTL window. Seeding `at` to 0.0
    there has the same defect for the same reason, and on a cold clock it would
    leave the second tier reading the first tier's endpoint."""
    monkeypatch.setattr(router.time, "monotonic", lambda: 1.5)
    router.active_endpoint()
    router.reset_cache()
    router.active_endpoint()
    assert len(cold) == 2, "reset_cache() did not force a re-read"
