"""The load driver delivers the rate it claims, and says so when it does not.

A load driver that quietly falls behind is the classic coordinated-omission
defect: the tier looks fast because the driver stopped asking. SPEC/06's
amended clause makes "achieved within 5% of driven" the condition for a step
being dispositive, so that is the load-bearing assertion here — and the test
that matters most is the one where the driver CANNOT keep up and has to admit
it.

## The autouse stub is a safety guard, not a convenience

The first version of this file stubbed the retrieval node in a fixture that
three of its six tests did not request. Those three called `run_step` against
the REAL `graph.nodes.retrieval_agent` — which reaches Bedrock and S3 Vectors —
and one of them asked for 50,000 calls per second. It hung, was killed, and
`AWS/Bedrock` shows no Titan invocations for the window, so nothing was spent.
That was luck, not design.

So the stub is `autouse=True` and `_forbid_real_calls` fails any test that
reaches a boto3 client at all. A unit test that can spend money is a worse
defect than anything it might be testing, and the fix belongs at the file level
where it cannot be forgotten per-test.
"""
from __future__ import annotations

import threading
import time

import pytest

from ops import retrieval_load


@pytest.fixture(autouse=True)
def _forbid_real_calls(monkeypatch):
    """No test in this module may construct an AWS client.

    Belt and braces with the stub below: the stub replaces the node, and this
    catches any path that goes around it — a helper importing boto3 directly, a
    future edit to `_one_call`, or a test that forgets the stub.
    """
    import boto3

    def refuse(*a, **kw):
        raise AssertionError(
            "the load-driver unit tests must never construct an AWS client; "
            "this test would have made real Bedrock and S3 Vectors calls")

    monkeypatch.setattr(boto3, "client", refuse)
    monkeypatch.setattr(boto3, "resource", refuse)


@pytest.fixture(autouse=True)
def node(monkeypatch):
    """Replace the node the driver looks up, for EVERY test in this module.

    Patched on `graph.instrument.observed` — the symbol the driver actually
    resolves — so the test still exercises the driver's own wiring, including
    that it goes through `instrument.observed` at all. That is what makes the
    measured interval the one SPEC/06's clause names.
    """
    state = {"service_ms": 5.0, "fail_every": 0, "calls": 0}
    counter_lock = threading.Lock()

    def observed(_name, _fn):
        def run(_state, *a, **kw):
            with counter_lock:
                state["calls"] += 1
                mine = state["calls"]
            time.sleep(state["service_ms"] / 1000.0)
            if state["fail_every"] and mine % state["fail_every"] == 0:
                raise RuntimeError("AossError: 503 from the search backend")
            return {"retrieval_ms": state["service_ms"],
                    "retrieval_tier": "aoss", "retrieval_fallback": None,
                    "retrieved": [1, 2, 3]}
        return run

    import graph.instrument as real

    monkeypatch.setattr(real, "observed", observed)
    return state


def test_it_dispatches_on_a_schedule_not_on_completion(node):
    """The open-loop property, measured.

    Service time is 40ms and the interval is 20ms. A closed loop with one
    worker would manage 25/s; an open loop must still deliver 50/s, because it
    does not wait for the previous call.
    """
    node["service_ms"] = 40.0
    out = retrieval_load.run_step(rate=50, seconds=1.0, questions=["q"],
                                  label="open-loop")
    assert out["dispatched"] >= 45
    assert out["achieved_rate"] == pytest.approx(50, rel=0.15)
    # Concurrency is arrival rate x service time = 50 * 0.04 = 2, and the
    # amended clause requires the report to CARRY it rather than assume it.
    assert out["inflight_peak"] >= 2
    assert out["inflight_mean"] > 0


def test_a_driver_that_cannot_keep_up_reports_it_and_is_not_dispositive(monkeypatch):
    """The coordinated-omission guard, exercised by making it fire.

    Dispatch itself is slowed to 2ms while the schedule asks for one every
    1ms, so the driver physically cannot meet the rate. It must say so rather
    than reporting whatever it managed as though that were the offered load.
    """
    real_thread = retrieval_load.threading.Thread

    class SlowThread(real_thread):
        def start(self):
            time.sleep(0.002)
            super().start()

    monkeypatch.setattr(retrieval_load.threading, "Thread", SlowThread)
    out = retrieval_load.run_step(rate=1000, seconds=0.1, questions=["q"],
                                  label="unmeetable")

    assert out["achieved_rate"] < 1000
    assert out["rate_within_5pct"] is False
    assert out["dispositive_eligible"] is False


def test_a_step_that_meets_its_rate_is_eligible(node):
    """The other side of the same gate — it must be reachable.

    A guard that can only refuse is indistinguishable from one that is broken.
    """
    node["service_ms"] = 1.0
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"])
    assert out["rate_within_5pct"] is True
    assert out["bedrock_retries"]["total"] == 0
    assert out["dispositive_eligible"] is True


def test_a_bedrock_throttle_disqualifies_the_step(monkeypatch, node):
    """Titan throttles are excluded from the error rate and poison the latency.

    `shared.util.retry` turns one throttle into up to 14 seconds of sleep
    INSIDE the measured interval. The clause excludes Bedrock throttles from
    the error rate, so that exclusion means something only if a step carrying
    one cannot be the dispositive step.
    """
    node["service_ms"] = 1.0
    monkeypatch.setattr(retrieval_load.util, "retry_stats",
                        lambda: {"total": 1, "by_error": {"ThrottlingException": 1}})
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"])

    assert out["rate_within_5pct"] is True      # the rate was met...
    assert out["dispositive_eligible"] is False  # ...and it still cannot count
    assert out["bedrock_retries"]["total"] == 1


def test_the_retry_helper_actually_counts_a_throttle(monkeypatch):
    """The counter the test above stubs, exercised for real.

    Without this, `bedrock_retries` could be permanently zero and every step
    would look eligible — the exclusion enforced by a number nobody produces.
    """
    from shared import util

    monkeypatch.setattr(util.time, "sleep", lambda _s: None)
    util.reset_retry_stats()

    calls = {"n": 0}

    def throttled():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ThrottlingException: slow down")
        return "ok"

    assert util.retry(throttled) == "ok"
    assert util.retry_stats()["total"] == 1
    assert util.retry_stats()["by_error"] == {"RuntimeError": 1}

    util.reset_retry_stats()
    assert util.retry_stats()["total"] == 0


def test_errors_are_counted_separately_from_latency(node):
    """A failed call must not contribute a latency sample.

    Its elapsed time is the time to fail, which is not a retrieval latency;
    folding it in would make a broken tier look fast or slow depending on how
    it broke.
    """
    node["service_ms"] = 2.0
    node["fail_every"] = 3
    out = retrieval_load.run_step(rate=30, seconds=0.5, questions=["q"])

    assert out["errors"] > 0
    assert out["n"] == out["returned"] - out["errors"]
    assert 0 < out["error_rate"] < 1
    assert out["error_sample"]


def test_the_percentile_method_is_nearest_rank_and_is_stated():
    """Matched to the M04 artifact deliberately: two percentile methods over
    the same samples can differ by more than the effect being measured."""
    values = [float(v) for v in range(1, 101)]
    assert retrieval_load._percentile(values, 0.95) == 95.0
    assert retrieval_load._percentile(values, 0.50) == 50.0
    assert retrieval_load._percentile([], 0.95) is None
    assert retrieval_load._percentile([7.0], 0.95) == 7.0


def test_the_report_states_the_percentile_method(node):
    node["service_ms"] = 1.0
    out = retrieval_load.run_step(rate=10, seconds=0.2, questions=["q"])
    assert "nearest-rank" in out["percentile_method"]
    assert out["n"] > 0


def test_the_question_set_is_varied_and_is_not_the_golden_set():
    """One repeated query would let a tier's own caching answer without doing
    the work being timed. The golden set is the SME seat's and measures
    correctness, not latency — borrowing it would put a latency harness in the
    path of ground truth."""
    import json
    from pathlib import Path

    questions = retrieval_load._default_questions()
    assert len(questions) >= 5
    assert len(set(questions)) == len(questions)

    golden = json.loads(
        (Path(__file__).parent.parent / "evals" / "golden_questions.json")
        .read_text(encoding="utf-8"))
    rows = golden if isinstance(golden, list) else golden.get("questions", [])
    stems = {q.get("question") for q in rows if isinstance(q, dict)}
    assert stems, "could not read the golden set; this check would be vacuous"
    assert not (set(questions) & stems), "the driver is reusing golden questions"
