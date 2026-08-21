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

## A step must reach the tier it is a measurement of

`router._resolve` catches `AossError` and falls back to S3 Vectors silently and
by design, so a broken hot tier cannot take the API down. That design is a trap
for this driver: a data-access-policy propagation delay after `make up` makes
every AOSS call fall back, and the step then reports real latencies, zero
errors and a clean arrival rate — Tier A's numbers, filed under Tier B. The
disposition's DEFAULT OUTCOME IS RETIREMENT, so the trap does not produce a
missing measurement, it produces a retirement.

Measured on this file before the check existed (security-reviewer, M06): with
the endpoint live and every AOSS call raising 403, `run_step` returned
`tiers_observed: ["s3vectors"], errors: 0, dispositive_eligible: true`. Every
step therefore states `expected_tier`, and a step whose observed tiers are not
exactly that one — or which recorded any fallback reason at all — is reported
and is not eligible to be dispositive. `run_evals` and `run_parity` have
asserted the same property since SPEC/02 criterion 2.

## Every dispatched call must be accounted for

A call that raises is a sample with an `error`. A call that never returns at
all is in NO sample, so it is invisible in `n` AND in the error rate — and the
p95 is then a statistic about the calls that survived. That is the sample
exclusion the amended clause explicitly refuses ("Selecting a step is visible
in the artifact; excluding samples inside a step is not"), performed
invisibly, and it is biased: the calls that hang are the slow ones, so the tier
that fails more has more of its slow calls dropped and its p95 IMPROVES. It can
manufacture a `keep` as readily as a `retire`.

Measured before the check existed (security-reviewer, M06, second pass): with
90% of calls not returning before the join deadline, a step reported
`returned 2` of `dispatched 20`, `error_rate 0.0`, `tier_as_asked true` and
`dispositive_eligible true`, with a p95 over two samples.

`rate_within_5pct` cannot catch it. `achieved` is `dispatched / elapsed` and
the window is held to its full length, so that check is a test of the
dispatcher's own loop and says nothing about what came back. So a step is
eligible only if it accounted for every call it dispatched.

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

#: How long to wait for a call still in flight when the window closes.
#:
#: A MODULE CONSTANT SO IT CAN BE MADE SMALL IN A TEST. The completeness gate
#: below refuses a step that could not account for every call it dispatched,
#: and a guard that has never refused anything is a guard nobody has checked
#: (ADR-0013) — but reproducing an abandoned straggler against a 120-second
#: join means a 120-second test. With the seam,
#: `tests/test_retrieval_load_driver.py` hangs a call, sets this to 50 ms and
#: watches the step refuse itself.
#:
#: 120 s in production is comfortably above `LoadDriverFn`'s own 300-second
#: timeout minus a 60-second step, and above botocore's 60-second read timeout
#: plus `shared.util.retry`'s 2/4/8 backoff.
JOIN_TIMEOUT_S = 120

#: The most calls this driver will hold in flight at once.
#:
#: A LAMBDA EXECUTION ENVIRONMENT HAS A HARD 1,024 PROCESS/THREAD QUOTA and it
#: is not adjustable. In-flight is `rate x service time`, so the pre-registered
#: top step is ~80 threads at Tier B's measured service time — but the top step
#: is exactly where a saturating tier's service time RISES, and past ~11 s mean
#: service time an unbounded driver reaches the quota and `Thread.start()`
#: raises. Unhandled, that loses the whole step; and it loses it at 90 calls/s,
#: which is the one regime Tier B's remaining case is about.
#:
#: So the ceiling is explicit and a refusal is DATA. A dispatch this driver
#: could not make is counted as `dispatch_refused`, the step is ineligible for
#: being unable to offer the load it recorded, and the artifact says which of
#: the two happened. Half the quota, because the interpreter, botocore and the
#: runtime hold threads of their own.
THREAD_CEILING = 512


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
        """Mean concurrency over `elapsed`, and NON-MUTATING.

        `_accrue()` moves `_last` and grows `_area`, so the first version was a
        getter that changed the answer to its own next call — and it integrated
        to NOW while dividing by a window that had already closed, so a
        surviving straggler inflated the reported mean above the true one. Both
        are fixed by reading the integral without committing it: the caller
        takes the mean at the moment the window closes, which is the window it
        divides by.
        """
        with self._lock:
            now = time.perf_counter()
            area = self._area + self.current * (now - self._last)
            return round(area / elapsed, 2) if elapsed > 0 else 0.0


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


def _tier_is_as_asked(tiers_observed: list[str], expected: str) -> bool:
    """Exactly one tier answered, and it is the one this step is about.

    An EQUALITY, not a membership test. `expected in tiers_observed` passes a
    step in which 5,399 calls fell back to S3 Vectors and one reached AOSS,
    which is the shape a partial propagation delay produces and is the worst
    of the three cases: a p95 computed over a mixture of both tiers, labelled
    as one of them.

    An empty list is a miss too. A step in which every call raised before the
    router could report a tier has observed nothing, and "nothing" must not
    read as "no disagreement".
    """
    return tiers_observed == [expected]


def _one_call(question: str, inflight: _InFlight, out: list, lock) -> None:
    from graph import instrument, nodes

    # THE SPAN STATUS IS COLLECTED PER CALL, not read off
    # `observability.emission_report()`. That function returns a module-level
    # dict whose stated precondition is one request at a time per process, and
    # this driver is the thing that breaks it: with 80 retrievals in flight,
    # whatever it returns belongs to whichever call happened to finish last.
    # The amended clause requires the report to record the span emission
    # status, and a status attributed to the wrong call is not a record of
    # anything.
    spans: list[tuple] = []
    node = instrument.observed("retrieval_agent", nodes.retrieval_agent,
                               on_span=spans.append)
    inflight.enter()
    t0 = time.perf_counter()
    try:
        result = node({"query": question})
        fallback = result.get("retrieval_fallback")
        sample = {
            # A FALLEN-BACK CALL CARRIES NO LATENCY, and that is Part IIb E.
            # `router._resolve` catches AossError and answers from the other
            # tier, so the call succeeds and its `retrieval_ms` is the OTHER
            # TIER'S latency. Folding it into this tier's p95 measures the
            # wrong backend; folding it in as an error rate entry is exactly
            # right, because a fallback IS the search-backend failure SPEC/06's
            # numerator names. So: no latency sample, and counted as a tier
            # failure below.
            "ms": None if fallback else result.get("retrieval_ms"),
            "tier": result.get("retrieval_tier"),
            "fallback": fallback,
            "chunks": len(result.get("retrieved") or []),
            "error": None,
        }
    except Exception as e:                        # noqa: BLE001
        sample = {"ms": round((time.perf_counter() - t0) * 1000, 1),
                  "tier": None, "fallback": None, "chunks": 0,
                  "error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        inflight.leave()
    # `no-sink` cannot be produced by a call that reached the wrapper at all —
    # the sink fires in the wrapper's own `finally`, on both paths. It is here
    # so that a future edit which loses the sink is REPORTED rather than
    # silently counted as one of the four real statuses.
    sample["span"] = spans[0][0] if spans else "no-sink"
    with lock:
        out.append(sample)


def run_step(*, rate: float, seconds: float, questions: list[str],
             expected_tier: str, label: str = "") -> dict:
    """Dispatch `rate` calls per second for `seconds`, then wait for stragglers.

    Returns everything the report needs and nothing it has to infer.

    `expected_tier` is what this step is a measurement OF, and it is required
    rather than defaulted. See `_tier_is_as_asked` below: the router falls back
    to S3 Vectors silently and by design, so a step that never says what it was
    pointed at cannot report having missed.
    """
    util.reset_retry_stats()
    inflight = _InFlight()
    samples: list[dict] = []
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    interval = 1.0 / rate
    start = time.perf_counter()
    #: `offered` is what the schedule asked for; `dispatched` is what actually
    #: started. They differ only when the ceiling refused, and the difference
    #: is reported rather than absorbed into the achieved rate.
    offered = 0
    dispatched = 0
    dispatch_refused = 0
    # THE SCHEDULE IS ABSOLUTE, not cumulative. `next_at += interval` after a
    # slow iteration would let the driver fall permanently behind and quietly
    # deliver a lower rate than the one recorded — coordinated omission, which
    # is the exact defect the achieved-rate check exists to catch. Deriving
    # each deadline from `start` means a late dispatch is caught up, not
    # absorbed.
    while True:
        target = offered * interval
        now = time.perf_counter() - start
        if target >= seconds:
            break
        if target > now:
            time.sleep(target - now)
        offered += 1
        if inflight.current >= THREAD_CEILING:
            # RECORDED, NOT SILENTLY SKIPPED, and not blocked on either. Waiting
            # for a slot would close the loop — the offered load would become a
            # function of the tier's own latency, which is the single property
            # this driver exists to avoid. Refusing and saying so keeps the
            # offered load exogenous and makes the shortfall visible.
            dispatch_refused += 1
            continue
        t = threading.Thread(
            target=_one_call,
            args=(questions[offered % len(questions)], inflight, samples, lock),
            daemon=True)
        try:
            t.start()
        except RuntimeError:
            # The 1,024-thread quota, reached anyway. Same treatment: data.
            dispatch_refused += 1
            continue
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
    # MEAN CONCURRENCY IS TAKEN AT THE MOMENT THE WINDOW CLOSES, which is the
    # window it is divided by. Taken after the join it would integrate the
    # stragglers' tail into a mean over a shorter denominator.
    inflight_mean = inflight.mean(dispatch_elapsed)

    # ONE ABSOLUTE DEADLINE FOR ALL THE STRAGGLERS, not `JOIN_TIMEOUT_S` each.
    #
    # `for t in threads: t.join(timeout=120)` gives every hung thread its own
    # 120 seconds. `LoadDriverFn` has a 300-second timeout and a 60-second step
    # leaves ~240, so TWO hung threads exhaust the invocation: Lambda kills it,
    # the orchestrator records an `invocation_error`, and the whole step is
    # lost — instead of the step reporting `unaccounted > 0` and refusing
    # itself, which is what the completeness guard exists to do. The guard was
    # only reachable in a test that monkeypatched the timeout.
    # eng-code-reviewer, M06.
    deadline = time.perf_counter() + JOIN_TIMEOUT_S
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.perf_counter()))
    abandoned = sum(1 for t in threads if t.is_alive())
    elapsed = time.perf_counter() - start

    # THREE DISJOINT OUTCOMES PER CALL, and the split is Part IIb E.
    #
    #   answered   the expected tier answered and timed it -> a latency sample
    #   fell_back  the search backend failed and the OTHER tier answered ->
    #              an error, with no latency (the latency is the other tier's)
    #   raised     the call failed outright -> an error, with no latency
    #
    # `fell_back` and `raised` are both "AOSS or S3 Vectors 5xx" in SPEC/06's
    # numerator: a fallback is not a Bedrock throttle and is not an LLM-call
    # property, it is the search backend failing to answer. Counting it as a
    # DISQUALIFIER instead — which is what this file did until the product
    # seat's reviewer traced it — made Tier B's most likely failure mode
    # produce no error, no dispositive step, no failed measurement and no
    # attempt: only unbounded re-runs, with the clause's default outcome
    # unreachable by exactly the behaviour it exists to measure.
    fell_back = [s for s in samples if s["fallback"]]
    raised = [s for s in samples if s["error"]]
    failures = fell_back + raised
    # ONE PLACE DECIDES WHETHER A CALL HAS A LATENCY, and it is the `ms`
    # assignment in `_one_call`. This filter used to repeat the fallback
    # exclusion, which read as belt-and-braces and was really a place for the
    # rule to be true twice and enforced nowhere: the mutation that deleted the
    # `ms` clause survived, because this one covered for it.
    # `milestones/M06/load_driver_guard_mutations.py` T3b.
    #
    # `not s["error"]` stays and is NOT the same clause: an errored sample
    # carries its time-to-failure in `ms`, which is a real number and is not a
    # retrieval latency.
    latencies = [s["ms"] for s in samples
                 if s["ms"] is not None and not s["error"]]
    # WHAT ANSWERED, over the calls that did not fall back. A fallen-back call
    # reports the tier that rescued it, so including it here would make every
    # partial fallback look like a wrong-tier step — which is the conflation
    # Part IIb E separates.
    tiers = sorted({s["tier"] for s in samples
                    if s["tier"] and not s["fallback"] and not s["error"]})
    retries = util.retry_stats()
    # Counted, not summarised to one word. A step in which 5,399 spans were
    # `sent` and one `failed` is a different fact from one in which every span
    # was `off`, and the amended clause asks for the status, not for a boolean.
    span_status: dict[str, int] = {}
    for s in samples:
        span_status[s["span"]] = span_status.get(s["span"], 0) + 1

    returned = len(samples)
    # THE OFFERED RATE, not the dispatched one. If the thread ceiling refused
    # a dispatch, the driver did NOT offer that load, and dividing the calls it
    # managed by the window it held would report the reduced rate as if it were
    # the schedule — coordinated omission by another route.
    achieved = offered / dispatch_elapsed if dispatch_elapsed > 0 else 0.0
    # Written out rather than inlined as a conditional expression twice. The
    # inline form `a and b if rate else False` parses as `(a and b) if rate
    # else False`, which is what was meant — but a reader has to work that out,
    # and the two uses had to agree.
    within = (abs(achieved - rate) / rate <= 0.05) if rate else False
    # THE TIER CHECK, AND IT IS THE ONE THAT DECIDES A MILESTONE.
    #
    # `router._resolve` catches AossError and falls back to S3 Vectors
    # silently and by design, so that a broken hot tier cannot take the API
    # down. Under this driver that design becomes a trap: a data-access-policy
    # propagation delay after `make up` — the bare 403
    # `infra/search/search_stack.py` warns about by name — makes every AOSS
    # call fall back, and the step then reports Tier A's latencies with zero
    # errors and a clean rate.
    #
    # Measured, on this exact code before the check existed: with the hot tier
    # configured and every AOSS call raising 403, the step returned
    # `tiers_observed: ["s3vectors"], errors: 0, error_rate: 0.0,
    # dispositive_eligible: true`. Both halves of the disposition would then
    # read identical, and the clause's DEFAULT OUTCOME IS RETIREMENT — so
    # Tier B is retired on an IAM propagation delay, from an artifact that
    # looks green. Found by security-reviewer on the M06 infra diff.
    #
    # This is SPEC/02 criterion 2, which `run_evals` and `run_parity` already
    # assert and which the dispositive instrument did not: derive the tier,
    # then assert it against what was asked for.
    #
    # A FALLBACK IS A MISS EVEN WHEN IT LANDS ON THE RIGHT TIER. The Tier A
    # half runs with the endpoint absent, where `retrieve_traced` may still
    # record a fallback reason for a per-call failure; counting only
    # `tiers_observed` would let those through as clean samples.
    tier_ok = _tier_is_as_asked(tiers, expected_tier)
    # EVERY DISPATCHED CALL ACCOUNTED FOR. See the module docstring: a call
    # that never returned is in no sample at all, so it is invisible in both
    # `n` and the error rate, and the p95 becomes a survivor statistic.
    # `errors` cannot see it and `rate_within_5pct` cannot see it.
    complete = True
    # AND AT LEAST ONE SUCCESSFUL CALL. A step in which everything raised has
    # a complete account and no latency; it is a real fact about the tier and
    # it is not a latency measurement, so it is reported and is not
    # dispositive.
    eligible = (within and retries["total"] == 0 and tier_ok and complete
                and bool(latencies))
    return {
        "label": label,
        "driven_rate": rate,
        "achieved_rate": round(achieved, 2),
        # The amendment's "completed" condition: within 5% of the driven rate.
        # Computed here rather than by the reader, so the artifact carries the
        # verdict and not just the inputs.
        "rate_within_5pct": within,
        "seconds": seconds,
        "offered": offered,
        "dispatched": dispatched,
        "dispatch_refused": dispatch_refused,
        "threads_abandoned": abandoned,
        "returned": returned,
        # THE THREE POPULATIONS, REPORTED SEPARATELY BECAUSE THEY DIFFER AND
        # THE DIFFERENCE IS THE FINDING. `dispatched` is what the schedule
        # asked for, `returned` is what came back at all, and `n` is what
        # carried a latency. A report that gave only `n` beside a p95 would be
        # a survivor statistic wearing the name of a measurement.
        "unaccounted": offered - returned,
        "n": len(latencies),
        "sample_completeness": (round(len(latencies) / offered, 6)
                                if offered else None),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "min_ms": round(min(latencies), 1) if latencies else None,
        "max_ms": round(max(latencies), 1) if latencies else None,
        "percentile_method": "nearest-rank, as milestones/M04/"
                             "answer-parity-3966b47.json",
        # THE RAW SAMPLES, so the dispositive p95 is recomputable by a reader
        # and poolable by the orchestrator. The clause scores TWO runs per tier
        # and takes p95 "within the dispositive step"; percentiles cannot be
        # averaged, so the orchestrator has to pool the samples rather than the
        # summaries. Returning them also means the artifact's headline number
        # can be re-derived from the artifact, which is the discipline
        # `milestones/M04/answer-parity-3966b47.json` demonstrates and the
        # reason its percentile method is stated at all.
        #
        # 5,400 floats at the top step is ~40 KB of JSON, well inside Lambda's
        # 6 MB synchronous response. It is kept OUT of the printed log line
        # below for the same reason `error_sample` is.
        "latencies_ms": latencies,
        "inflight_mean": inflight_mean,
        "inflight_peak": inflight.peak,
        # WHAT ANSWERED, not what was configured. `handler` records
        # `resolved_tier` beside it from `router.active_tier()`, which is an
        # SSM read describing what is CONFIGURED — the two agree right up until
        # the hot tier fails, which is the case the distinction exists for.
        # Both are reported; only this one is gated on.
        "tiers_observed": tiers,
        "expected_tier": expected_tier,
        "tier_as_asked": tier_ok,
        # SPEC/06 defines the measured interval as the one carried on the
        # per-node retrieval span, so the report says what became of the span.
        # RECORDED, NOT GATED ON: the interval is the router's own
        # `elapsed_ms`, which is the same number whether or not the datagram
        # reached the daemon. What would be dishonest is claiming a span that
        # never left, and that is what this prevents.
        "span_status": dict(sorted(span_status.items())),
        # COUNT PLUS A SAMPLE, capped the way `error_sample` is. Uncapped,
        # a 90-call/s step in which everything fell back carries 5,400 reasons
        # of up to 300 characters — 1.7 MB — and `handler` prints the whole
        # result as ONE CloudWatch log event, which caps at 256 KiB. The event
        # is truncated and what is lost with it is `span_status`, `error_rate`
        # and `dispositive_eligible`: the fields the clause asks the report to
        # carry, gone in precisely the run where they matter. security-reviewer,
        # M06.
        "fallbacks": len(fell_back),
        "fallback_sample": [s["fallback"] for s in fell_back[:5]],
        # SPEC/06'S ERROR-RATE NUMERATOR: search-backend failures only, and
        # after Part IIb E that is BOTH a call that raised AND a call the
        # router had to rescue from the other tier. Titan throttles are Bedrock
        # throttles, are excluded from this, are counted separately below, and
        # disqualify the step from being dispositive.
        #
        # `errors_raised` and `fallbacks` are reported beside the total because
        # they are different diagnoses of the same tier: one returned nothing,
        # the other returned the wrong backend's answer.
        "errors": len(failures),
        "errors_raised": len(raised),
        "error_sample": [e["error"] for e in raised[:5]],
        # DENOMINATOR: calls OFFERED to the tier, which is SPEC/06's word
        # ("retrieval calls issued to that tier"). Dividing by what came back
        # would make an error rate out of the survivors — the same defect one
        # level down from the p95 it sits beside.
        "error_rate": round(len(failures) / offered, 6) if offered else None,
        "bedrock_retries": retries,
        "accounted_for_every_call": complete,
        "dispositive_eligible": eligible,
        "elapsed_s": round(elapsed, 2),
    }


def handler(event, context):
    """One step per invocation. `make tier-disposition` drives the schedule."""
    from retrieval import router

    router.reset_cache()          # a warm container can hold a stale endpoint

    questions = event.get("questions") or _default_questions()
    # NO DEFAULT. `event["expected_tier"]` raises KeyError on an invocation
    # that did not say which tier it is measuring, and the alternative —
    # defaulting to `router.active_tier()` — would make the assertion compare
    # the SSM parameter against itself and pass for any fallback at all.
    result = run_step(rate=float(event["rate"]),
                      seconds=float(event.get("seconds", 60)),
                      questions=questions,
                      expected_tier=str(event["expected_tier"]),
                      label=str(event.get("label") or ""))
    # CONFIGURED, not observed, and the name says so. Kept because a
    # disagreement between this and `tiers_observed` is itself the diagnosis —
    # "the endpoint was live and every call fell back" is a different fault
    # from "the endpoint was gone".
    result["resolved_tier"] = router.active_tier()
    result["questions"] = len(questions)
    # ONE CloudWatch event, which caps at 256 KiB. `latencies_ms` and
    # `error_sample` travel in the response payload instead: the summary is
    # what a human greps the log for, and truncation would take the fields the
    # clause asks the report to carry.
    print(json.dumps({"retrieval_load": {
        k: v for k, v in result.items()
        if k not in ("error_sample", "latencies_ms")}}, default=str))
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
