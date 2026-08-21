"""One step of the retrieval-concurrency profile, run in-region (SPEC/06).

This is the driver behind the Tier B disposition. One Lambda invocation is ONE
STEP: a fixed arrival rate, held for a fixed duration, against whichever tier
the SSM parameter currently names.

## Open loop, and that is the whole point

Requests are dispatched **on a schedule**, not when the previous one finishes.
A closed loop — N workers each looping "call, wait, call again" — makes the
offered load a function of the tier's own latency, so the slower tier receives
proportionally more concurrency and the comparison is no longer controlled.
`milestones/M06/spec06-disposition-amendment.md` has the arithmetic: SPEC/06's
500-user `/query` profile would have handed Tier B 2.26x Tier A's in-flight
retrievals purely for being slower.

An open loop does not equalise in-flight concurrency either — that stays
`arrival rate x service time` and so stays proportional to each tier's latency.
What it equalises is the **offered** load, which becomes exogenous and
recorded instead of being an output of the result. The amendment names that as
Change 4 and asks the seat to accept it explicitly; this file does not decide
it.

## Why it drives one node and not the graph

`graph.nodes` keeps `_last_stop`, `_cache_state` and `_last_usage` at module
level, with a stated precondition of one request at a time per process. Driving
the whole graph from many threads would violate it silently and mis-attribute
stop reasons, cache state and token counts across requests. `retrieval_agent`
touches none of them: it calls the router and returns.

It is invoked THROUGH `instrument.observed` rather than directly, because
SPEC/06 defines the measured interval as the one carried on the per-node
retrieval span. Measuring a different call than the clause names would be the
substitution the clause exists to prevent.

## What counts as an error, and what does not

SPEC/06 excludes Bedrock throttles from the retrieval error rate: they are an
LLM-call property shared by both tiers and caused by neither search backend.
But every retrieval EMBEDS, `shared.util.retry` absorbs a throttle into 2/4/8
seconds of sleep *inside the measured interval*, and until M06 nothing counted
them. `retry_stats()` is that count, and a step that recorded any Titan
throttle is reported and is **not** eligible to be the dispositive step.
"""
from __future__ import annotations

import json
import threading
import time

from shared import util


class _InFlight:
    """Concurrency actually achieved, sampled by the calls themselves.

    Reported rather than assumed. The amendment requires it: a profile states
    the load it DELIVERED, never the load it asked for, and the 500-user figure
    SPEC/06 previously named would have delivered eleven.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self._area = 0.0            # integral of concurrency over time
        self._last = time.perf_counter()

    def _accrue(self) -> None:
        now = time.perf_counter()
        self._area += self.current * (now - self._last)
        self._last = now

    def enter(self) -> None:
        with self._lock:
            self._accrue()
            self.current += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self._lock:
            self._accrue()
            self.current -= 1

    def mean(self, elapsed: float) -> float:
        with self._lock:
            self._accrue()
            return round(self._area / elapsed, 2) if elapsed > 0 else 0.0


def _percentile(values: list[float], q: float) -> float | None:
    """NEAREST-RANK, the method `milestones/M04/answer-parity-3966b47.json` used.

    Stated and matched deliberately: the disposition compares against that
    artifact's discipline, and two percentile methods over the same samples can
    differ by more than the effect being measured on a small n.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))
    return round(ordered[rank - 1], 1)


def _one_call(question: str, inflight: _InFlight, out: list, lock) -> None:
    from graph import instrument, nodes

    node = instrument.observed("retrieval_agent", nodes.retrieval_agent)
    inflight.enter()
    t0 = time.perf_counter()
    try:
        result = node({"query": question})
        sample = {
            "ms": result.get("retrieval_ms"),
            "tier": result.get("retrieval_tier"),
            "fallback": result.get("retrieval_fallback"),
            "chunks": len(result.get("retrieved") or []),
            "error": None,
        }
    except Exception as e:                        # noqa: BLE001
        sample = {"ms": round((time.perf_counter() - t0) * 1000, 1),
                  "tier": None, "fallback": None, "chunks": 0,
                  "error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        inflight.leave()
    with lock:
        out.append(sample)


def run_step(*, rate: float, seconds: float, questions: list[str],
             label: str = "") -> dict:
    """Dispatch `rate` calls per second for `seconds`, then wait for stragglers.

    Returns everything the report needs and nothing it has to infer.
    """
    util.reset_retry_stats()
    inflight = _InFlight()
    samples: list[dict] = []
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    interval = 1.0 / rate
    start = time.perf_counter()
    dispatched = 0
    # THE SCHEDULE IS ABSOLUTE, not cumulative. `next_at += interval` after a
    # slow iteration would let the driver fall permanently behind and quietly
    # deliver a lower rate than the one recorded — coordinated omission, which
    # is the exact defect the achieved-rate check exists to catch. Deriving
    # each deadline from `start` means a late dispatch is caught up, not
    # absorbed.
    while True:
        target = dispatched * interval
        now = time.perf_counter() - start
        if target >= seconds:
            break
        if target > now:
            time.sleep(target - now)
        t = threading.Thread(
            target=_one_call,
            args=(questions[dispatched % len(questions)], inflight, samples, lock),
            daemon=True)
        t.start()
        threads.append(t)
        dispatched += 1

    # LET THE WINDOW RUN ITS FULL LENGTH BEFORE MEASURING THE RATE.
    #
    # The loop above exits after dispatching the last call, which happens at
    # `(n-1)/rate`, not at `seconds`. Dividing `n` by that gap gives
    # `rate * n/(n-1)` — biased HIGH, and by 14% at n=8. A driver reporting it
    # had exceeded its own target rate is not a small cosmetic error: the
    # amended clause gates the dispositive step on "achieved within 5% of
    # driven", so the bias made a perfectly-behaved step ineligible and would
    # have thrown away the very steps the measurement depends on.
    #
    # The honest denominator is the window the driver INTENDED to hold, so it
    # is held. At a 60-second step this is a rounding detail; the definition is
    # what matters, and it is now right at every duration.
    remaining = seconds - (time.perf_counter() - start)
    if remaining > 0:
        time.sleep(remaining)
    dispatch_elapsed = time.perf_counter() - start
    for t in threads:
        t.join(timeout=120)
    elapsed = time.perf_counter() - start

    latencies = [s["ms"] for s in samples if s["ms"] is not None and not s["error"]]
    errors = [s for s in samples if s["error"]]
    tiers = sorted({s["tier"] for s in samples if s["tier"]})
    retries = util.retry_stats()

    achieved = dispatched / dispatch_elapsed if dispatch_elapsed > 0 else 0.0
    # Written out rather than inlined as a conditional expression twice. The
    # inline form `a and b if rate else False` parses as `(a and b) if rate
    # else False`, which is what was meant — but a reader has to work that out,
    # and the two uses had to agree.
    within = (abs(achieved - rate) / rate <= 0.05) if rate else False
    eligible = within and retries["total"] == 0
    return {
        "label": label,
        "driven_rate": rate,
        "achieved_rate": round(achieved, 2),
        # The amendment's "completed" condition: within 5% of the driven rate.
        # Computed here rather than by the reader, so the artifact carries the
        # verdict and not just the inputs.
        "rate_within_5pct": within,
        "seconds": seconds,
        "dispatched": dispatched,
        "returned": len(samples),
        "n": len(latencies),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "min_ms": round(min(latencies), 1) if latencies else None,
        "max_ms": round(max(latencies), 1) if latencies else None,
        "percentile_method": "nearest-rank, as milestones/M04/"
                             "answer-parity-3966b47.json",
        "inflight_mean": inflight.mean(elapsed),
        "inflight_peak": inflight.peak,
        "tiers_observed": tiers,
        "fallbacks": [s["fallback"] for s in samples if s["fallback"]],
        # SPEC/06's error rate numerator: search-backend failures only. Titan
        # throttles are Bedrock throttles and are excluded from it, counted
        # separately below, and disqualify the step from being dispositive.
        "errors": len(errors),
        "error_sample": [e["error"] for e in errors[:5]],
        "error_rate": round(len(errors) / len(samples), 6) if samples else None,
        "bedrock_retries": retries,
        "dispositive_eligible": eligible,
        "elapsed_s": round(elapsed, 2),
    }


def handler(event, context):
    """One step per invocation. `make tier-disposition` drives the schedule."""
    from retrieval import router

    router.reset_cache()          # a warm container can hold a stale endpoint

    questions = event.get("questions") or _default_questions()
    result = run_step(rate=float(event["rate"]),
                      seconds=float(event.get("seconds", 60)),
                      questions=questions,
                      label=str(event.get("label") or ""))
    result["resolved_tier"] = router.active_tier()
    result["questions"] = len(questions)
    print(json.dumps({"retrieval_load": {
        k: v for k, v in result.items() if k != "error_sample"}}, default=str))
    return result


def _default_questions() -> list[str]:
    """A fixed, varied set so the driver is not measuring one cached vector.

    Deliberately NOT the golden questions: those are the SME seat's ground
    truth and this measures latency, not correctness. Deliberately more than
    one, because a single repeated query would let either tier's own internal
    caching answer without doing the work being timed.
    """
    return [
        "What changed for the healthy claim on food labels?",
        "When does the Red No. 3 revocation take effect?",
        "What is the compliance date for the healthy rule?",
        "Which CFR sections did the 2025 delay rule amend?",
        "What are the GRAS notification requirements?",
        "Are there recordkeeping obligations for ready-to-eat foods?",
        "What did the stay change about the color additive order?",
        "Which documents supersede 21 CFR 101.65?",
        "What is the effective date of the nutrient content claim rule?",
    ]
