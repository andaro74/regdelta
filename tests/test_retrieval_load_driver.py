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
    state = {"service_ms": 5.0, "fail_every": 0, "calls": 0,
             "span_status": "sent", "tier": "aoss", "fallback": None,
             # `fall_back_every`: the silent fallback the real router performs
             # on an AossError. Nth call reports the OTHER tier, exactly as
             # `router._resolve` does — it does not raise, and that is the
             # whole difficulty.
             "fall_back_every": 0,
             # A call that never comes back before the join deadline. Not an
             # error — an error returns a sample. This one is in no sample at
             # all, which is the whole point of the completeness gate.
             "hang_every": 0, "hang_s": 0.5,
             # A resolution that names a tier and carries no timing. Not an
             # error and not a fallback: the call succeeded and the instrument
             # did not. `router.retrieve_traced` returns `resolution.elapsed_ms`
             # and nothing in its type forbids None.
             "untimed": False}
    counter_lock = threading.Lock()

    def observed(_name, _fn, on_span=None):
        """The stub honours `on_span`'s contract, INCLUDING on the error path.

        The real wrapper fires the sink from a `finally`, so an errored call
        still reports what became of its span. A stub that fired it only on
        success would let the driver's aggregation look right here while
        reporting every failed retrieval as `no-sink` in the region.

        What this stub CANNOT establish is that the real wrapper behaves this
        way — it is the driver's author's own specimen of the collaborator.
        `test_the_real_wrapper_reports_the_span_status_on_both_paths` below
        drives `graph.instrument.observed` itself for that.
        """
        def run(_state, *a, **kw):
            with counter_lock:
                state["calls"] += 1
                mine = state["calls"]
            try:
                if state["hang_every"] and mine % state["hang_every"] == 0:
                    time.sleep(state["hang_s"])
                time.sleep(state["service_ms"] / 1000.0)
                if state["fail_every"] and mine % state["fail_every"] == 0:
                    raise RuntimeError("AossError: 503 from the search backend")
                fell_back = (state["fall_back_every"]
                             and mine % state["fall_back_every"] == 0)
                return {
                    "retrieval_ms": (None if state["untimed"]
                                     else state["service_ms"]),
                    "retrieval_tier": "s3vectors" if fell_back else state["tier"],
                    "retrieval_fallback": ("AossError: 403" if fell_back
                                           else state["fallback"]),
                    "retrieved": [1, 2, 3]}
            finally:
                if on_span is not None:
                    on_span((state["span_status"], None))
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
                                  expected_tier="aoss", label="open-loop")
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
                                  expected_tier="aoss", label="unmeetable")

    assert out["achieved_rate"] < 1000
    assert out["rate_within_5pct"] is False
    assert out["dispositive_eligible"] is False


def test_a_step_that_meets_its_rate_is_eligible(node):
    """The other side of the same gate — it must be reachable.

    A guard that can only refuse is indistinguishable from one that is broken.
    """
    node["service_ms"] = 1.0
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")
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
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

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
    out = retrieval_load.run_step(rate=30, seconds=0.5, questions=["q"],
                                  expected_tier="aoss")

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
    out = retrieval_load.run_step(rate=10, seconds=0.2, questions=["q"],
                                  expected_tier="aoss")
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


# --------------------------------------------------------------- span status
# SPEC/06 defines the measured interval as the one carried on the per-node
# retrieval span, and the amended clause requires the report to record what
# became of that span. Three things have to hold and they are separable:
#
#   1. the real wrapper hands a status to a sink, on BOTH paths
#      -> tests/test_instrument_span_sink.py, which this module's autouse stub
#         would otherwise replace out from under the assertion
#   2. the driver collects one per call and tallies them        (below)
#   3. the driver does not read `observability.emission_report()`, which is
#      module-level and cannot attribute a status under concurrency (below)


def test_the_step_report_tallies_the_span_status_per_call(node):
    node["service_ms"] = 1.0
    node["span_status"] = "sent"
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")
    assert out["span_status"] == {"sent": out["returned"]}
    assert out["returned"] > 0


def test_an_unemitted_span_is_reported_and_does_not_masquerade_as_sent(node):
    """Off is a legitimate state — no daemon outside Lambda — and must READ as
    off. A report that could only say "sent" would be evidence of nothing."""
    node["service_ms"] = 1.0
    node["span_status"] = "off"
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")
    assert out["span_status"] == {"off": out["returned"]}


def test_the_span_status_of_a_failed_call_is_recorded_too(node):
    """The errored calls are the ones whose spans matter most, and they are
    counted under their own status rather than dropped with their latency."""
    node["service_ms"] = 1.0
    node["fail_every"] = 3
    out = retrieval_load.run_step(rate=30, seconds=0.5, questions=["q"],
                                  expected_tier="aoss")
    assert out["errors"] > 0
    assert sum(out["span_status"].values()) == out["returned"]


def test_the_driver_does_not_read_the_module_level_emission_report():
    """The mis-attribution guard, asserted on the source.

    `observability.emission_report()` returns a process-global whose stated
    precondition — one request at a time — this driver is the first thing in
    the repo to break. Under 80 in-flight retrievals it returns whichever call
    finished last, for every call. Reading it here would produce a report that
    looks complete and attributes statuses at random.
    """
    from pathlib import Path

    src = (Path(__file__).parent.parent / "src" / "ops" / "retrieval_load.py"
           ).read_text(encoding="utf-8")
    assert "emission_report" not in src.replace(
        "`observability.emission_report()`", "")


# ------------------------------------------------------- the tier assertion
# THE DEFECT THIS GUARDS, in one sentence: the router falls back to S3 Vectors
# silently and by design, the disposition's default outcome is RETIREMENT, and
# so a Tier B step that never reached Tier B retires Tier B while reporting
# zero errors and a clean rate. Measured on this code before the check existed
# (security-reviewer, M06 infra diff):
#
#   tiers_observed: ["s3vectors"]  errors: 0  error_rate: 0.0
#   dispositive_eligible: true     resolved_tier: "aoss"
#
# `run_evals` and `run_parity` have asserted the same property since SPEC/02
# criterion 2. The dispositive instrument did not.


def test_a_step_that_reached_the_tier_it_was_pointed_at_is_eligible(node):
    """The positive half, first. A guard that can only refuse is
    indistinguishable from one that is broken."""
    node["service_ms"] = 1.0
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")
    assert out["tiers_observed"] == ["aoss"]
    assert out["expected_tier"] == "aoss"
    assert out["tier_as_asked"] is True
    assert out["fallbacks"] == 0
    assert out["dispositive_eligible"] is True


def test_a_wholesale_fallback_is_a_100_percent_error_rate(node):
    """THE FINDING, and Part IIb E's answer to it. Every call falls back;
    nothing raises.

    The rate is met, no Titan throttle fires, and the latencies are real — they
    are just Tier A's. The first fix made a fallback a DISQUALIFIER, which the
    product seat's reviewer showed produces no error, no dispositive step, no
    failed measurement and no attempt: unbounded re-runs, with the clause's
    default outcome unreachable by the behaviour it exists to measure.

    The split: a fallback is a SEARCH-BACKEND FAILURE. It goes in the error
    rate — SPEC/06's numerator is "AOSS or S3 Vectors 5xx" and that is exactly
    what happened — and it contributes no latency, because the latency belongs
    to the tier that rescued it. A tier that fell back on everything therefore
    records a 100% error rate and no p95, which is the honest description.
    """
    node["service_ms"] = 1.0
    node["fall_back_every"] = 1
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")

    assert out["error_rate"] == 1.0, "every call was a search-backend failure"
    assert out["fallbacks"] == out["returned"]
    assert out["errors_raised"] == 0, "the router does not raise on a fallback"
    assert out["rate_within_5pct"] is True, "the rate was met; that is the trap"
    assert out["n"] == 0 and out["p95_ms"] is None, (
        "a fallen-back call's latency is the OTHER tier's and must not be "
        "filed under this one")
    assert out["tiers_observed"] == []
    assert out["dispositive_eligible"] is False


def test_a_partial_fallback_is_measured_rather_than_refused(node):
    """Part IIb E, and the case that decides whether the clause terminates.

    One call in three falls back. Under the old rule the step was disqualified
    and the half became a gate refusal that consumed no attempt — so a Tier B
    degrading under concurrency, which is the ONLY regime its remaining case is
    about, could never produce a verdict.

    Under the split it produces the right one: the fallen-back third is a 33%
    error rate, the two thirds AOSS actually answered give the p95, and the
    step stays dispositive. The comparability gate in the orchestrator then
    decides whether that p95 may be compared at all.
    """
    node["service_ms"] = 1.0
    node["fall_back_every"] = 3
    out = retrieval_load.run_step(rate=30, seconds=0.5, questions=["q"],
                                  expected_tier="aoss")

    assert out["tiers_observed"] == ["aoss"], (
        "the tier that ANSWERED, over the calls that were not rescued")
    assert out["fallbacks"] > 0
    assert 0.2 < out["error_rate"] < 0.5
    assert out["n"] == out["returned"] - out["errors"] > 0
    assert out["tier_as_asked"] is True
    assert out["dispositive_eligible"] is True, (
        "a measurable degradation must be measurable; refusing it is how the "
        "clause failed to terminate")


def test_a_fallback_that_lands_on_the_expected_tier_is_still_a_failure(node):
    """The router reporting `retrieval_tier: aoss` alongside a fallback reason
    still means the search backend failed on that call.

    It goes in the error rate like any other fallback, and it contributes no
    latency — the reason a fallback has no latency is that the timing describes
    a rescue, not the tier under test, and that holds however the rescue
    resolved.
    """
    node["service_ms"] = 1.0
    node["fallback"] = "AossError: 503, retried on the same tier"
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["fallbacks"] == out["returned"] > 0
    assert out["error_rate"] == 1.0
    assert out["n"] == 0
    assert out["dispositive_eligible"] is False


def test_a_step_where_nothing_reported_a_tier_is_not_a_pass(node):
    """`tiers_observed == []` is a miss, not an absence of disagreement.

    Every call raises before the router can name a tier. An `expected not in
    observed` formulation reads the empty list as agreement.
    """
    node["service_ms"] = 1.0
    node["fail_every"] = 1
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["tiers_observed"] == []
    assert out["tier_as_asked"] is False
    assert out["dispositive_eligible"] is False


def test_the_tier_check_is_an_equality_on_the_observed_set():
    """The predicate on its own, at the three boundaries a load run cannot
    reliably reproduce in a unit test."""
    assert retrieval_load._tier_is_as_asked(["aoss"], "aoss") is True
    assert retrieval_load._tier_is_as_asked(["s3vectors"], "aoss") is False
    assert retrieval_load._tier_is_as_asked(["aoss", "s3vectors"], "aoss") is False
    assert retrieval_load._tier_is_as_asked([], "aoss") is False


def test_the_expected_tier_has_no_default():
    """Required, not defaulted. A default of `router.active_tier()` would
    compare the SSM parameter against itself and pass for any fallback."""
    with pytest.raises(TypeError):
        retrieval_load.run_step(rate=1, seconds=0.01, questions=["q"])


def test_the_handler_refuses_an_invocation_that_names_no_tier(monkeypatch):
    """`make tier-disposition` supplies it per half. A console Test-button
    invocation that omits it must fail loudly rather than measure something
    nobody can label."""
    import sys
    import types

    stub = types.ModuleType("retrieval.router")
    stub.reset_cache = lambda: None
    stub.active_tier = lambda: "aoss"
    monkeypatch.setitem(sys.modules, "retrieval.router", stub)

    with pytest.raises(KeyError):
        retrieval_load.handler({"rate": 1, "seconds": 0.01}, None)


# ------------------------------------------------------- the log-line budget
def test_the_fallback_list_is_capped_and_counted(node):
    """`handler` prints the whole result as ONE CloudWatch log event, and that
    caps at 256 KiB. Uncapped, a 90-call/s step in which everything fell back
    is 5,400 reasons of up to 300 characters — 1.7 MB — so the event is
    truncated and `span_status`, `error_rate` and `dispositive_eligible` are
    what get lost, in exactly the run where they matter."""
    node["service_ms"] = 1.0
    node["fall_back_every"] = 1
    out = retrieval_load.run_step(rate=40, seconds=0.5, questions=["q"],
                                  expected_tier="aoss")

    assert out["fallbacks"] == out["returned"] > 5
    assert isinstance(out["fallbacks"], int)
    assert len(out["fallback_sample"]) == 5


# ------------------------------------------------- is the sample set complete
# THE FAMILY THE MUTATION HARNESS DID NOT HAVE. security-reviewer found it by
# writing the mutation this file could not fail: `t.join(timeout=...)` -> 0,
# deleting the driver's entire wait-for-stragglers behaviour, and everything
# here stayed green. Every assertion was stated relative to `returned`, and the
# single use of `dispatched` never compared the two.
#
# A dropped call is in NO sample, so it is invisible in `n` and in the error
# rate, and the p95 becomes a statistic about the calls that survived. That is
# the sample exclusion the amended clause refuses in writing, performed
# invisibly — and biased, because the calls that hang are the slow ones, so the
# tier that fails more has more of its slow calls dropped and its p95 improves.


def test_a_well_behaved_step_accounts_for_every_call_it_dispatched(node):
    """The positive half. The three populations must agree when nothing went
    wrong, or the gate below could only ever refuse."""
    node["service_ms"] = 1.0
    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")
    assert out["dispatched"] == out["returned"] > 0
    assert out["unaccounted"] == 0
    assert out["accounted_for_every_call"] is True
    assert out["sample_completeness"] == 1.0
    assert out["dispositive_eligible"] is True


def test_stragglers_are_waited_for_rather_than_abandoned(node):
    """HARNESS S1/S2 — the mutation that survived.

    Every call is still in flight when the window closes: the service time is
    longer than the whole step. The driver must wait for them, not walk away
    with whatever had finished.
    """
    node["service_ms"] = 250.0
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")
    assert out["dispatched"] >= 5
    assert out["returned"] == out["dispatched"], (
        "the driver abandoned calls that were still in flight; their latencies "
        "are the slow ones, so dropping them flatters the tier")
    assert out["unaccounted"] == 0


def test_a_call_that_never_returns_makes_the_step_ineligible(monkeypatch, node):
    """HARNESS S3, and the security review's Attack B reproduced.

    Measured on this code before the gate existed: 2 of 20 calls returned,
    `errors 0`, `error_rate 0.0`, `tier_as_asked true`, `dispositive_eligible
    true`, and a p95 over two samples.

    `errors` cannot see this and neither can `rate_within_5pct`: `achieved` is
    `dispatched / elapsed` over a window held to its full length, so it tests
    the dispatcher's own loop and nothing downstream.
    """
    monkeypatch.setattr(retrieval_load, "JOIN_TIMEOUT_S", 0.05)
    node["service_ms"] = 1.0
    node["hang_every"] = 1
    node["hang_s"] = 2.0

    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["unaccounted"] > 0
    assert out["returned"] < out["dispatched"]
    assert out["errors"] == 0, "a call that never returned is not an error"
    assert out["rate_within_5pct"] is True, "the dispatcher kept up; that is the trap"
    assert out["accounted_for_every_call"] is False
    assert out["dispositive_eligible"] is False
    assert out["sample_completeness"] < 1.0


def test_a_step_where_everything_raised_is_reported_and_is_not_dispositive(node):
    """HARNESS S4. Every call returns — as an error — so the account is
    complete and there is still no latency to compare. A real fact about the
    tier, and not a latency measurement."""
    node["service_ms"] = 1.0
    node["fail_every"] = 1
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["accounted_for_every_call"] is True
    assert out["n"] == 0 and out["p95_ms"] is None
    assert out["error_rate"] == 1.0
    assert out["dispositive_eligible"] is False


def test_a_step_that_resolved_a_tier_but_timed_nothing_is_not_dispositive(node):
    """HARNESS S4, and the case where `bool(latencies)` is the SOLE refusal.

    The first version of this assertion used `fail_every`, which also empties
    `tiers_observed` — so the tier check refused first and the mutation that
    deleted this clause survived. The case that isolates it is a call that
    SUCCEEDED, named its tier, and carried no `retrieval_ms`: the account is
    complete, the tier is right, nothing fell back, and there is still no
    latency to put a p95 over.

    A step like that must be reported and must not be dispositive. Silently, it
    would contribute `p95_ms: None` to the comparison, where neither disjunct
    holds and Tier B retires on an instrument failure.
    """
    node["service_ms"] = 1.0
    node["untimed"] = True
    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["tiers_observed"] == ["aoss"], "the tier resolved fine"
    assert out["accounted_for_every_call"] is True
    assert out["errors"] == 0 and out["fallbacks"] == 0
    assert out["n"] == 0 and out["p95_ms"] is None
    assert out["dispositive_eligible"] is False


def test_the_three_populations_are_reported_separately(node):
    """`n` beside a p95, with no dispatch count, is a survivor statistic
    wearing the name of a measurement."""
    node["service_ms"] = 1.0
    node["fail_every"] = 4
    out = retrieval_load.run_step(rate=30, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")
    assert out["dispatched"] == out["returned"]
    assert out["n"] == out["returned"] - out["errors"] < out["dispatched"]
    assert 0 < out["sample_completeness"] < 1.0


# --------------------------------------------- the thread ceiling and the join
# eng-code-reviewer, M06. A Lambda execution environment has a hard 1,024
# process/thread quota; in-flight is `rate x service time`, and the top step is
# exactly where a saturating tier's service time rises. Unbounded, the driver
# reaches the quota, `Thread.start()` raises in the dispatch loop, and the whole
# 90/s step is lost — at the one rate Tier B's remaining case is about.


def test_a_refused_dispatch_is_recorded_and_the_step_is_not_dispositive(monkeypatch, node):
    """A refusal is DATA, not a skip and not a block.

    Blocking for a slot would close the loop: the offered load would become a
    function of the tier's own latency, which is the single property this
    driver exists to avoid. So the driver refuses, says how often, and the step
    cannot be dispositive because it did not offer the load it recorded.
    """
    monkeypatch.setattr(retrieval_load, "THREAD_CEILING", 2)
    node["service_ms"] = 80.0
    out = retrieval_load.run_step(rate=50, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")

    assert out["dispatch_refused"] > 0
    assert out["offered"] > out["dispatched"]
    assert out["dispositive_eligible"] is False
    assert out["accounted_for_every_call"] is False


def test_the_achieved_rate_is_over_offered_not_over_dispatched(monkeypatch, node):
    """Otherwise a driver that refused half its dispatches reports the reduced
    rate as though it were the schedule — coordinated omission by another
    route, and the achieved-rate check would call it well behaved."""
    monkeypatch.setattr(retrieval_load, "THREAD_CEILING", 2)
    node["service_ms"] = 80.0
    out = retrieval_load.run_step(rate=50, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")

    assert out["achieved_rate"] == pytest.approx(50, rel=0.2), (
        "the schedule offered 50/s; the driver could not deliver it, and the "
        "honest report is 'offered 50, dispatched fewer'")
    assert out["rate_within_5pct"] is True
    assert out["dispositive_eligible"] is False, (
        "meeting the offered rate is not enough when the calls never started")


def test_the_join_deadline_is_absolute_not_per_thread(monkeypatch, node):
    """`for t in threads: t.join(timeout=120)` gives EVERY hung thread its own
    120 seconds. LoadDriverFn has 300 s total and a 60 s step leaves ~240, so
    two hung threads kill the invocation and the step is lost as an invocation
    error — instead of reporting `unaccounted > 0` and refusing itself.

    Three threads hang here against a 150 ms budget. Per-thread the join would
    take at least 450 ms; absolute, it takes about 150.
    """
    monkeypatch.setattr(retrieval_load, "JOIN_TIMEOUT_S", 0.15)
    node["service_ms"] = 1.0
    node["hang_every"] = 1
    node["hang_s"] = 3.0

    t0 = time.perf_counter()
    out = retrieval_load.run_step(rate=10, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")
    join_budget = time.perf_counter() - t0 - 0.3

    assert out["threads_abandoned"] >= 3
    assert join_budget < 0.45, (
        f"the join took {join_budget:.2f}s of straggler budget; an absolute "
        "deadline caps it at JOIN_TIMEOUT_S however many threads hang")
    assert out["dispositive_eligible"] is False


def test_abandoned_threads_are_reported_so_the_next_step_can_be_distrusted(
        monkeypatch, node):
    """The ghost-load leak. A thread the driver walked away from is still
    running when the orchestrator invokes the next step into the same warm
    container, so step N+1's offered load silently includes calls step N
    abandoned. Nothing in N+1 can see them — they are not in its `dispatched`,
    its `achieved_rate` or its `_InFlight`.

    The driver cannot stop that; what it can do is SAY it happened, so the
    orchestrator can refuse the following step too."""
    monkeypatch.setattr(retrieval_load, "JOIN_TIMEOUT_S", 0.05)
    node["service_ms"] = 1.0
    node["hang_every"] = 2
    node["hang_s"] = 2.0

    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")
    assert out["threads_abandoned"] > 0


def test_mean_concurrency_does_not_move_the_integral_it_reads(node):
    """`mean()` used to `_accrue()`, so it moved the integral it read: a second
    call returned a different answer from the first.

    MEASURED WITH NOTHING IN FLIGHT, and the first version of this test was
    flaky for want of that. With a call still in flight the integral is
    genuinely still growing, so two reads a few microseconds apart differ by a
    few microseconds' worth — `round(..., 2)` hid it about four times in five.
    A flaky test inside a mutation harness is worse than a missing one: a red
    run reads as a mutation KILLED, so the flake manufactures evidence that a
    guard works.

    With the call finished, `current` is 0 and the area is frozen, so any
    difference between two reads is the accrual bug and nothing else.
    """
    inflight = retrieval_load._InFlight()
    inflight.enter()
    time.sleep(0.02)
    inflight.leave()

    first = inflight.mean(0.02)
    time.sleep(0.01)
    second = inflight.mean(0.02)

    assert first == second, "mean() is a getter and must not move the integral"
    assert first > 0


def test_mean_concurrency_is_taken_before_the_stragglers_are_waited_for(
        monkeypatch, node):
    """The other half of the same fix, asserted where it is actually true.

    `mean()` integrates to NOW and divides by the window the caller hands it,
    so it is only meaningful if the caller reads it AT the window's close. The
    driver does; a version that read it after the join would divide a longer
    integral by the same window and report a mean above the peak.

    THE FIRST VERSION OF THIS TEST ASSERTED `mean(0.05) <= 1.0` after a
    `sleep(0.05)` with one call in flight, and failed every time — `sleep`
    sleeps a little LONGER than asked, so the honest ratio is 1.01. That was
    the test being wrong about arithmetic, not the code being wrong, and it is
    recorded here because a test whose premise is false is the same defect as a
    comment whose claim is false.

    The invariant that does hold: the mean over the window cannot exceed the
    peak concurrency observed during it.
    """
    monkeypatch.setattr(retrieval_load, "JOIN_TIMEOUT_S", 0.05)
    node["service_ms"] = 1.0
    node["hang_every"] = 2
    node["hang_s"] = 1.0

    out = retrieval_load.run_step(rate=20, seconds=0.3, questions=["q"],
                                  expected_tier="aoss")

    assert out["threads_abandoned"] > 0, "the case only arises with stragglers"
    assert 0 < out["inflight_mean"] <= out["inflight_peak"], (
        f"mean {out['inflight_mean']} exceeds peak {out['inflight_peak']}; the "
        "integral was read after the window it is divided by had closed")


def test_a_step_answered_by_the_other_tier_is_not_a_measurement_of_this_one(node):
    """HIGH 1 in its purest form, and the case the mutation harness found
    uncovered.

    Every other tier test here reaches ineligibility by a second route as well:
    a wholesale fallback leaves no latency, and a step where everything raised
    leaves no tier AND no latency. So deleting `tier_ok` from the eligibility
    conjunction survived — `bool(latencies)` was covering for it.

    This is the shape with no second route. The router resolves the OTHER tier
    and answers from it cleanly: real latencies, a complete account, no
    fallback reason, the rate met, no throttle. Physically reachable — the SSM
    parameter can change between the orchestrator deriving the tier and the
    step running, and a data-access-policy propagation delay after `make up`
    produces the same thing.

    Nothing but the tier check refuses it, and if nothing refuses it, Tier A's
    latencies are filed under Tier B in a clause whose default outcome is
    retirement.
    """
    node["service_ms"] = 1.0
    node["tier"] = "s3vectors"

    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="aoss")

    assert out["tiers_observed"] == ["s3vectors"]
    assert out["n"] > 0, "these calls carry real latencies; that is the trap"
    assert out["errors"] == 0 and out["fallbacks"] == 0
    assert out["accounted_for_every_call"] is True
    assert out["rate_within_5pct"] is True
    assert out["tier_as_asked"] is False
    assert out["dispositive_eligible"] is False, (
        "a step answered by the other tier is not a measurement of this one")


def test_the_same_step_pointed_at_the_tier_that_answered_is_eligible(node):
    """The control. Without it the test above passes for a step that was
    ineligible for some unrelated reason."""
    node["service_ms"] = 1.0
    node["tier"] = "s3vectors"

    out = retrieval_load.run_step(rate=20, seconds=0.4, questions=["q"],
                                  expected_tier="s3vectors")
    assert out["tier_as_asked"] is True
    assert out["dispositive_eligible"] is True
