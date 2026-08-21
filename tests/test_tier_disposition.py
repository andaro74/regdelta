"""The disposition orchestrator: what it refuses, and what it concludes.

`loadtest/retrieval_load.py` is the thing that decides whether Tier B survives
M06. Its verdict is reached from an artifact, and every gate it applies is
recomputed from the recorded steps rather than read off the driver's summary —
so these tests build artifacts by hand and check the conclusion.

Offline and free. Nothing here invokes a Lambda, reads SSM, or touches AWS:
`dispose()` is pure by construction, which is the reason it is a separate
function from `run_half()`.

WHY THE ARTIFACTS ARE HAND-BUILT AND NOT RECORDED. A specimen written by the
rule's own author cannot validate the rule — so these do not attempt to. They
establish that the DECISION LOGIC maps a given artifact to a given verdict,
which is checkable in isolation. What the driver actually records is
`tests/test_retrieval_load_driver.py`'s subject, and the two meet in
`test_the_two_percentile_implementations_agree` and
`test_a_real_driver_step_satisfies_the_orchestrators_condition` below, which
are the only places a mismatch between them could hide.
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "loadtest"))
sys.path.insert(0, str(ROOT / "evals"))


def _load_orchestrator():
    """BY FILE PATH, not by name, and the reason is a real collision.

    The orchestrator is `loadtest/retrieval_load.py` and the driver is
    `src/ops/retrieval_load.py` — the same basename. A bare
    `import retrieval_load` resolves to whichever directory is earlier on
    `sys.path` at the moment the first test imports it, which is a function of
    test ordering. Loading this one explicitly makes the two unmistakable.
    """
    spec = importlib.util.spec_from_file_location(
        "loadtest_orchestrator", ROOT / "loadtest" / "retrieval_load.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orch = _load_orchestrator()


# --------------------------------------------------------------- the builders
def step(rate: int, tier: str, *, p95: float, n: int = 100,
         errors: int = 0, achieved: float | None = None,
         observed: list[str] | None = None, fallbacks: int = 0,
         throttles: int = 0, eligible_claim: bool = True,
         expected: str | None = None,
         latencies: list[float] | None = None,
         unaccounted: int = 0) -> dict:
    """One recorded step, in the shape the driver returns.

    `p95` is delivered by making every sample that value — the orchestrator's
    percentile over a constant list is that constant, so the tests can state
    the number they mean instead of arranging a distribution to produce it.

    THE THREE POPULATIONS ARE KEPT COHERENT, because their differences are what
    two of the gates are about: `dispatched` calls were issued, `returned` of
    them came back at all, and `returned - errors` of those carried a latency.
    A builder that let them drift would produce artifacts the driver cannot
    emit, and the assertions over them would be about nothing.

    `unaccounted` is the gap the security review found: calls that never
    returned, invisible in both `n` and the error rate.

    `eligible_claim` is the DRIVER'S `dispositive_eligible`, and it defaults to
    True independently of everything else on purpose: several tests below set
    it True on a step that must be refused, which is the only way to show the
    orchestrator is not reading it.
    """
    samples = [p95] * (n - errors) if latencies is None else list(latencies)
    return {
        "label": f"{tier}/{rate}ps",
        "driven_rate": rate,
        "achieved_rate": rate if achieved is None else achieved,
        "seconds": 60,
        "expected_tier": tier if expected is None else expected,
        "tiers_observed": [tier] if observed is None else observed,
        "fallbacks": fallbacks,
        "dispatched": n + unaccounted,
        "returned": n,
        "unaccounted": unaccounted,
        "errors": errors,
        "latencies_ms": samples,
        "sample_completeness": (round(len(samples) / (n + unaccounted), 6)
                                if n + unaccounted else None),
        "bedrock_retries": {"total": throttles},
        "span_status": {"sent": n},
        "inflight_mean": 1.0,
        "inflight_peak": 2,
        "accounted_for_every_call": unaccounted == 0,
        "dispositive_eligible": eligible_claim,
    }


def half(tier: str, *, p95: float, errors: int = 0, n: int = 100,
         corpus_sha: str = "abc123def456", vantage: str = "lambda:fn:us-west-2:2048MB",
         rates=orch.SCHEDULE, attempts: int = 1, **step_kw) -> dict:
    runs = [{"run": i, "warmup": i < orch.WARMUP_RUNS,
             "steps": [step(r, tier, p95=p95, n=n, errors=errors, **step_kw)
                       for r in rates]}
            for i in range(orch.RUNS_PER_TIER)]
    one = {
        "at": "2026-08-21T00:00:00+00:00",
        "vantage": vantage,
        "corpus": {"documents_sha": corpus_sha, "documents": 52},
        "config": {"RERANK": False, "RETRIEVAL_LEXICAL_LANE": False,
                   "NAIVE_TOP_K": 8, "EMBED_MODEL": "amazon.titan-embed-text-v2:0"},
        "budget": {},
        "runs": runs,
    }
    return {"attempts": [one] * attempts}


def artifact(**tiers) -> dict:
    return {"sha": "deadbee", "tiers": tiers}


# -------------------------------------------------------------- the verdicts
def test_one_half_is_incomplete_and_not_a_pass():
    """Exit 2, distinct from 1, so a half-finished measurement cannot be read
    as a passing one — and distinct from 4, so it cannot be read as the failed
    measurement that triggers the one permitted re-run."""
    out = orch.dispose(artifact(s3vectors=half("s3vectors", p95=300.0)))
    assert out["verdict"] == "incomplete"
    assert orch.exit_code(out) == 2


def test_tier_b_keeps_its_place_when_its_p95_is_lower():
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=400.0),
        aoss=half("aoss", p95=300.0)))
    assert out["verdict"] == "keep"
    assert out["latency_disjunct"]["holds"] is True
    assert orch.exit_code(out) == 0


def test_tier_b_keeps_its_place_on_an_exact_tie_of_p95():
    """"At or below Tier A's" — the clause's words. The `ties retire` sentence
    is about a difference inside the run-to-run spread, not about this
    boundary, and reading it the other way would retire on `<=`."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=350.0),
        aoss=half("aoss", p95=350.0)))
    assert out["verdict"] == "keep"


def test_tier_b_retires_when_it_is_slower_and_no_less_reliable():
    """The expected outcome on M04's numbers, and a successful disposition:
    exit 0, because the milestone cannot close without disposing of the clause
    either way and this disposes of it."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=354.1),
        aoss=half("aoss", p95=889.3)))
    assert out["verdict"] == "retire"
    assert out["latency_disjunct"]["holds"] is False
    assert out["error_rate_disjunct"]["holds"] is False
    assert orch.exit_code(out) == 0
    assert "regdelta-search" in out["verdict_reason"]


def test_the_error_rate_disjunct_needs_a_full_five_points():
    """Five percentage points LOWER, not merely lower. Four does not keep it."""
    four = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, errors=6, n=100),
        aoss=half("aoss", p95=900.0, errors=2, n=100)))
    assert four["error_rate_disjunct"]["holds"] is False
    assert four["verdict"] == "retire"

    five = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, errors=7, n=100),
        aoss=half("aoss", p95=900.0, errors=2, n=100)))
    assert five["error_rate_disjunct"]["holds"] is True
    assert five["verdict"] == "keep", (
        "a slower Tier B that is five points more reliable keeps its place; "
        "the clause is a disjunction and both arms must be reachable")


# ------------------------------------------------------- the dispositive step
def test_the_dispositive_step_is_the_highest_rate_both_tiers_completed():
    a = half("s3vectors", p95=300.0)
    b = half("aoss", p95=300.0)
    # Tier B could not hold the top two steps.
    for run in b["attempts"][0]["runs"]:
        for s in run["steps"]:
            if s["driven_rate"] in (75, 90):
                s["achieved_rate"] = s["driven_rate"] * 0.5
    out = orch.dispose(artifact(s3vectors=a, aoss=b))
    assert out["dispositive_rate"] == 50
    assert out["by_rate"]["90"]["both_eligible"] is False
    assert out["by_rate"]["50"]["both_eligible"] is True


def test_the_orchestrator_recomputes_eligibility_and_does_not_read_the_claim():
    """THE POINT OF THE WHOLE FILE.

    Every step below carries `dispositive_eligible: true` — the driver's own
    word — while recording a Titan throttle, which the amended clause makes
    disqualifying. If the orchestrator read the claim it would find a
    dispositive step and render a verdict. It must find none.

    The driver and this orchestrator share an author, so "the driver already
    checked" is exactly the assurance that is worth nothing here.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, throttles=3, eligible_claim=True),
        aoss=half("aoss", p95=300.0, throttles=3, eligible_claim=True)))
    assert out["dispositive_rate"] is None
    assert out["verdict"] == "failed-measurement"


def test_a_step_that_did_not_reach_its_tier_cannot_be_dispositive():
    """The security-review finding, at the orchestrator layer as well as the
    driver's. Belt and braces deliberately: this is the one false pass that
    retires Tier B on an IAM propagation delay."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0),
        aoss=half("aoss", p95=300.0, observed=["s3vectors"],
                  eligible_claim=True)))
    assert out["verdict"] == "gate-failed"
    assert any("not evidence about" in f for f in out["failures"])
    assert orch.exit_code(out) == 1


def test_a_step_with_a_fallback_cannot_be_dispositive():
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0),
        aoss=half("aoss", p95=300.0, fallbacks=4, eligible_claim=True)))
    assert out["dispositive_rate"] is None
    assert out["verdict"] == "failed-measurement"


def test_warmup_runs_are_excluded_from_the_dispositive_statistic():
    """"Three times per tier, the first discarded as warmup." The warmup run
    below is 10x slower; if it were pooled the p95 would move and Tier B would
    retire on a measurement the clause says to throw away."""
    b = half("aoss", p95=300.0)
    for s in b["attempts"][0]["runs"][0]["steps"]:      # the warmup run
        s["latencies_ms"] = [3000.0] * len(s["latencies_ms"])
    out = orch.dispose(artifact(s3vectors=half("s3vectors", p95=400.0), aoss=b))
    assert out["dispositive"]["aoss"]["p95_ms"] == 300.0
    assert out["verdict"] == "keep"


def test_the_dispositive_n_is_pooled_across_the_scored_runs():
    """Stated, because the amendment is ambiguous and its own worked example
    takes the other reading. `n` is defined as "retrieval calls counted across
    the scored runs"; two scored runs at 100 samples each is 200, and the
    per-run counts are reported beside it so the other reading costs a reader
    nothing."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, n=100),
        aoss=half("aoss", p95=300.0, n=100)))
    assert out["n_dispositive"] == {"s3vectors": 200, "aoss": 200}
    assert out["dispositive"]["aoss"]["n_per_run"] == [100, 100]


# ------------------------------------------------------------------ the gates
def test_two_corpora_are_not_a_comparison():
    """The poller moves the corpus unattended — 4 documents on 2026-07-30, 52
    on 2026-08-19 — and the halves are minutes-to-hours apart across a
    `make up`. A document landing between them would read as a tier
    difference."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, corpus_sha="aaaaaaaaaaaa"),
        aoss=half("aoss", p95=300.0, corpus_sha="bbbbbbbbbbbb")))
    assert out["corpus_agree"] is False
    assert out["verdict"] == "gate-failed"
    assert orch.exit_code(out) == 1


def test_a_missing_corpus_fingerprint_is_a_refusal_not_an_agreement():
    """`corpus.fingerprint()` returns `{"available": false}` with
    REGISTRY_TABLE unset, and two of those are equal. Equality of two absences
    must not read as agreement — that is how the gate silently stops gating."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, corpus_sha=None),
        aoss=half("aoss", p95=300.0, corpus_sha=None)))
    assert out["corpus_agree"] is False
    assert out["verdict"] == "gate-failed"


def test_two_vantages_are_not_a_comparison():
    """"From one vantage recorded and identical across both halves." Both
    halves are driven from the same deployed function, so a disagreement means
    one half was taken against a different deploy."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, vantage="lambda:a:us-west-2:2048MB"),
        aoss=half("aoss", p95=300.0, vantage="lambda:b:us-west-2:2048MB")))
    assert out["verdict"] == "gate-failed"
    assert any("vantage" in f for f in out["failures"])


def test_two_retrieval_configs_are_not_a_comparison():
    b = half("aoss", p95=300.0)
    b["attempts"][0]["config"]["RETRIEVAL_LEXICAL_LANE"] = True
    out = orch.dispose(artifact(s3vectors=half("s3vectors", p95=300.0), aoss=b))
    assert out["config_agree"] is False
    assert out["verdict"] == "gate-failed"


def test_a_gate_failure_beats_a_verdict():
    """A comparison over two different corpora still produces a number, and a
    number is worse than none: it reads as a disposition. The gate wins."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=900.0, corpus_sha="aaaaaaaaaaaa"),
        aoss=half("aoss", p95=100.0, corpus_sha="bbbbbbbbbbbb")))
    assert out["verdict"] == "gate-failed", "this would otherwise be a `keep`"
    assert "latency_disjunct" not in out


def test_too_few_scored_runs_is_a_gate_failure():
    b = half("aoss", p95=300.0)
    b["attempts"][0]["runs"] = b["attempts"][0]["runs"][:2]   # 1 warmup, 1 scored
    out = orch.dispose(artifact(s3vectors=half("s3vectors", p95=300.0), aoss=b))
    assert out["verdict"] == "gate-failed"
    assert any("scored run" in f for f in out["failures"])


# --------------------------------------------------- the floor, and its bound
def test_a_run_that_qualified_nowhere_is_a_failed_measurement_not_a_retirement():
    """Amendment Change 6. Unbounded this is a route to M06 ending with Tier B
    alive and the bar never met; bounded at one re-run it is what stops a dead
    profile being used against Tier B."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, achieved=1.0),
        aoss=half("aoss", p95=300.0, achieved=1.0)))
    assert out["verdict"] == "failed-measurement"
    assert out["failed_measurement"] is True
    assert orch.exit_code(out) == 4


def test_a_second_failed_measurement_disposes_by_the_default_outcome():
    """"A second failure is recorded in the report and the clause is disposed
    of by the default outcome" — because "M06 cannot close without disposing of
    this clause either way" outranks a third attempt.

    Exit 5, not 0: the clause asks the target to exit non-zero when no step
    qualifies, and this retirement was not measured.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, achieved=1.0, attempts=2),
        aoss=half("aoss", p95=300.0, achieved=1.0, attempts=2)))
    assert out["verdict"] == "retire"
    assert out["failed_measurement"] is True
    assert "DEFAULT OUTCOME" in out["verdict_reason"]
    assert orch.exit_code(out) == 5


def test_only_the_latest_attempt_is_judged():
    """A re-run replaces the measurement, not the record. The artifact keeps
    every attempt — Change 6 asks for the second failure to be recorded — and
    the judgement is over the latest."""
    b = half("aoss", p95=300.0, attempts=1)
    stale = {**b["attempts"][0]}
    b["attempts"] = [stale, b["attempts"][0]]
    out = orch.dispose(artifact(s3vectors=half("s3vectors", p95=400.0), aoss=b))
    assert out["attempts_per_tier"]["aoss"] == 2
    assert out["verdict"] == "keep"


# ------------------------------------------------------ the two implementations
def test_the_two_percentile_implementations_agree():
    """The driver computes a per-step p95 and the orchestrator recomputes the
    dispositive one over pooled samples. Two implementations of "nearest-rank"
    that disagree would put two different numbers in one artifact, and the M04
    artifact's whole discipline is that the method is stated because it
    matters."""
    from ops import retrieval_load as driver

    rng = random.Random(20260821)
    for size in (1, 2, 7, 27, 100, 601):
        values = [round(rng.uniform(50, 2000), 1) for _ in range(size)]
        for q in (0.50, 0.95):
            assert orch._percentile(values, q) == driver._percentile(values, q), \
                (size, q)
    assert orch._percentile([], 0.95) is driver._percentile([], 0.95) is None


def test_a_real_driver_step_satisfies_the_orchestrators_condition(monkeypatch):
    """THE SEAM, driven end to end offline.

    The hand-built steps above are this file's author's idea of what the driver
    returns. This one is what the driver ACTUALLY returns, put straight through
    the orchestrator's condition — so a field renamed on one side and not the
    other fails here rather than at 90 calls per second in the region.
    """
    import threading

    from ops import retrieval_load as driver

    def observed(_name, _fn, on_span=None):
        def run(_state, *a, **kw):
            if on_span is not None:
                on_span(("sent", None))
            return {"retrieval_ms": 5.0, "retrieval_tier": "aoss",
                    "retrieval_fallback": None, "retrieved": [1]}
        return run

    import graph.instrument as real
    monkeypatch.setattr(real, "observed", observed)
    monkeypatch.setattr(threading, "Thread", threading.Thread)  # explicit no-op

    real_step = driver.run_step(rate=20, seconds=0.4, questions=["q"],
                                expected_tier="aoss", label="seam")
    assert real_step["dispositive_eligible"] is True
    assert orch._step_ok(real_step, "aoss") is True, real_step
    assert orch._step_ok(real_step, "s3vectors") is False


# ----------------------------------------------------------------- the pricing
def test_the_price_is_under_the_seats_ceiling_and_names_all_three_components():
    from shared import config

    priced = orch.price()
    assert priced["total_usd"] < config.LOADTEST_BUDGET_USD
    assert priced["lambda_usd"] > 0 and priced["aoss_ocu_usd"] > 0
    assert priced["bedrock"]["estimated_usd"] > 0
    assert priced["total_usd"] == pytest.approx(
        priced["infra_usd"] + priced["bedrock"]["estimated_usd"], abs=1e-4)


def test_the_ceiling_is_on_the_whole_run_not_on_its_bedrock_half(monkeypatch):
    """`budget.check_plan` can only see Bedrock — a `Call` needs a model — so
    the infrastructure cost is subtracted from the ceiling handed to it.
    Without that, a ceiling of twenty cents would approve a run costing
    twenty-three."""
    import budget

    from shared import config

    monkeypatch.setattr(config, "LOADTEST_BUDGET_USD", 0.20)
    with pytest.raises(budget.BudgetExceededError):
        orch.price()


def test_a_schedule_over_the_titan_request_ceiling_is_refused(monkeypatch):
    """Not a dollar ceiling and not a token cap: 6,000 on-demand embed requests
    per minute, `Adjustable: false`. The pre-registered top step is 5,400/min,
    inside it by 10% — a schedule that was not must be refused before anything
    is invoked, not discovered as throttles that disqualify the top step and
    burn the one permitted re-run."""
    import budget

    monkeypatch.setattr(orch, "SCHEDULE", (10, 25, 50, 75, 200))
    with pytest.raises(budget.QuotaExceededError, match="NON-ADJUSTABLE"):
        orch.price()


def test_the_schedule_is_the_one_the_clause_pre_registered():
    """"Changing it after any M06 number exists reopens the clause." Pinned
    here so the change is visible in a diff rather than in a flag."""
    assert orch.SCHEDULE == (10, 25, 50, 75, 90)
    assert orch.STEP_SECONDS == 60
    assert orch.RUNS_PER_TIER == 3
    assert orch.WARMUP_RUNS == 1
    assert orch.CALLS_PER_RUN == 15_000


def test_every_exit_code_is_reachable_and_distinct():
    """Six codes, and `make tier-disposition` propagates them. A code nobody
    can produce is documentation, and two verdicts sharing a code make a failed
    measurement indistinguishable from a gate refusal."""
    seen = {
        orch.exit_code({"verdict": "keep"}),
        orch.exit_code({"verdict": "retire"}),
        orch.exit_code({"verdict": "incomplete"}),
        orch.exit_code({"verdict": "gate-failed"}),
        orch.exit_code({"verdict": "failed-measurement"}),
        orch.exit_code({"verdict": "retire", "failed_measurement": True}),
    }
    assert seen == {0, 1, 2, 4, 5}
    assert orch.exit_code({"verdict": "retire"}) == 0
    assert orch.exit_code({"verdict": "retire", "failed_measurement": True}) == 5


def test_a_gate_failure_beats_the_failed_measurement_floor():
    """The ordering, pinned, because getting it backwards is expensive.

    A half that measured the wrong tier makes every step ineligible, so with
    the floor evaluated first this presents as "no qualifying step" — which
    spends one of the two attempts Change 6 allows, and on a repeat retires
    Tier B by the default outcome. On an IAM propagation delay. The gate has to
    win, and this artifact trips both.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, corpus_sha="aaaaaaaaaaaa",
                       achieved=1.0),
        aoss=half("aoss", p95=300.0, corpus_sha="bbbbbbbbbbbb", achieved=1.0)))
    assert out["verdict"] == "gate-failed"
    assert out.get("failed_measurement") is None
    assert orch.exit_code(out) == 1


# --------------------------------------------- what the mutation harness found
# `milestones/M06/disposition_guard_mutations.py` ran twenty mutations against
# this file and three SURVIVED. Every one of the three was a gap in the
# assertions rather than in the code — except G2, which was a gap in both.
# Recorded as its own section because the three are the ones a reader should
# distrust first if any of this is ever wrong again.


def test_a_small_tier_b_disadvantage_still_retires():
    """HARNESS V1. Every other verdict test compares 354 ms against 889 ms or
    two identical numbers, so a 10% grace on the keep condition changed no
    outcome and survived.

    The clause has no grace: "at or below Tier A's", and "a difference inside
    the recorded run-to-run spread is not an advantage; ties retire". Tier B
    2.9% slower is Tier B retired.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=350.0),
        aoss=half("aoss", p95=360.0)))
    assert out["latency_disjunct"]["holds"] is False
    assert out["verdict"] == "retire"


def test_the_dispositive_number_is_the_95th_percentile_not_the_median():
    """HARNESS S3. Every latency list above is CONSTANT, so p50 and p95 are the
    same number and swapping them changed nothing.

    A skewed sample is the whole point of a concurrency profile: the median
    hides the tail. Here both tiers have the same median and Tier B has a far
    worse tail, which must retire it.
    """
    # Ninety and ten per run, POOLED ACROSS TWO SCORED RUNS: 180 and 20 of
    # 200, so nearest-rank puts the 95th percentile at index 190 — inside the
    # tail rather than on its boundary. The first draft used 95/5 and landed
    # the rank on the last fast sample, which read as a p50/p95 agreement and
    # would have let the mutation survive a second time.
    fast_tail = [100.0] * 90 + [110.0] * 10
    slow_tail = [100.0] * 90 + [900.0] * 10
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=0, latencies=fast_tail, n=100),
        aoss=half("aoss", p95=0, latencies=slow_tail, n=100)))

    assert out["dispositive"]["s3vectors"]["p50_ms"] == \
        out["dispositive"]["aoss"]["p50_ms"] == 100.0, "the medians agree"
    assert out["dispositive"]["s3vectors"]["p95_ms"] == 110.0
    assert out["dispositive"]["aoss"]["p95_ms"] == 900.0
    assert out["verdict"] == "retire"


def test_a_step_in_which_everything_failed_is_not_a_measurement():
    """HARNESS G2, and the one survivor that was a hole in the CODE.

    A step where every call raised observes no tier at all, and the half-level
    check reads an empty observed-set as "no disagreement" — correctly, since
    there is nothing to disagree with. So `_step_ok`'s own tier clause was the
    only thing refusing it, and with that clause removed the step reached the
    dispositive slot carrying no samples: `p95_ms` None on both sides, neither
    disjunct holding, and Tier B retired on a run that measured nothing.

    `_step_ok` now also refuses a step with no successful call, which is the
    property stated directly rather than as a side effect of the tier check.
    """
    dead = dict(observed=[], n=100, errors=100, eligible_claim=True)
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=0, **dead),
        aoss=half("aoss", p95=0, **dead)))

    assert out["verdict"] == "failed-measurement", (
        "a run in which every call failed is a failed measurement, not a "
        "retirement")
    assert out["dispositive_rate"] is None
    assert orch.exit_code(out) == 4


def test_the_step_condition_refuses_an_empty_sample_on_its_own():
    """The same property at the predicate, so it does not depend on which
    other clause happens to catch it first."""
    good = step(90, "aoss", p95=300.0, n=10)
    assert orch._step_ok(good, "aoss") is True
    assert orch._step_ok({**good, "latencies_ms": []}, "aoss") is False


def test_a_step_that_lost_calls_is_not_a_measurement():
    """HIGH 3, at the orchestrator. security-reviewer, M06, second pass.

    A call that never returned is in no sample, so it is invisible in `n` AND
    in the error rate: the step reports `error_rate 0.0`, `tier_as_asked true`
    and a p95 over whatever came back. Measured on the driver before the check
    existed: 2 of 20 calls returned and the step called itself eligible.

    The bias is not conservative. The calls that hang are the slow ones, so the
    tier that fails more has more of its slow calls dropped and its p95
    IMPROVES — it can manufacture a `keep` as readily as a `retire`. And it is
    exactly the sample exclusion the amended clause refuses in writing
    ("Selecting a step is visible in the artifact; excluding samples inside a
    step is not"), performed invisibly.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, n=100),
        aoss=half("aoss", p95=100.0, n=10, unaccounted=90,
                  eligible_claim=True)))
    assert out["verdict"] == "failed-measurement", (
        "a step that cannot account for 90 of the 100 calls it dispatched is "
        "not a faster tier")
    assert orch.exit_code(out) == 4


def test_the_step_condition_refuses_an_unaccounted_call_on_its_own():
    good = step(90, "aoss", p95=300.0, n=10)
    assert orch._step_ok(good, "aoss") is True
    assert orch._step_ok(step(90, "aoss", p95=300.0, n=10, unaccounted=1),
                         "aoss") is False
    # And a step from an older harness that carries neither field is refused
    # rather than assumed complete.
    assert orch._step_ok({k: v for k, v in good.items()
                          if k not in ("dispatched", "returned")},
                         "aoss") is False


def test_survivor_bias_cannot_win_the_latency_disjunct():
    """The other half of HIGH 3, and the INTERPRETATION named for the seat.

    Here every call is accounted for, so the completeness gate passes: Tier B
    simply fails 60% of its calls and the 40% that succeed are fast. Its p95
    over the survivors beats Tier A's — on the strength of having broken.

    The clause's keep condition is a disjunction, so without this the latency
    arm hands Tier B a keep. The comparability reading closes it using the
    clause's own five-percentage-point materiality: populations that far apart
    are not the same population, and the error-rate disjunct — which here
    points the other way — settles it.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=400.0, n=100, errors=1),
        aoss=half("aoss", p95=100.0, n=100, errors=60)))

    assert out["dispositive"]["aoss"]["p95_ms"] == 100.0
    assert out["dispositive"]["s3vectors"]["p95_ms"] == 400.0, (
        "Tier B's surviving samples really are faster; that is the trap")
    assert out["latency_disjunct"]["populations_comparable"] is False
    assert out["latency_disjunct"]["holds"] is False
    assert out["verdict"] == "retire"


def test_comparable_populations_still_get_the_latency_comparison():
    """The other side of the same gate — it must be reachable. Error rates
    within the clause's materiality leave the p95 comparison exactly as the
    clause writes it."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=400.0, n=100, errors=3),
        aoss=half("aoss", p95=300.0, n=100, errors=5)))
    assert out["latency_disjunct"]["populations_comparable"] is True
    assert out["latency_disjunct"]["holds"] is True
    assert out["verdict"] == "keep"


def test_the_report_carries_all_three_populations_at_the_dispositive_step():
    """`n` beside a p95 with no dispatch count is a survivor statistic wearing
    the name of a measurement. A reader must be able to see the gap."""
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0, n=100, errors=4),
        aoss=half("aoss", p95=300.0, n=100, errors=4)))
    entry = out["dispositive"]["aoss"]
    assert entry["calls_dispatched"] == 200
    assert entry["calls_returned"] == 200
    assert entry["unaccounted"] == 0
    assert entry["n"] == 192, "eight errored calls carry no latency"


def test_a_fallen_back_step_is_reported_as_ineligible_not_merely_gated():
    """HARNESS G2, which survived because the half-level gate reaches the
    verdict first.

    That gate is about the HALF; `by_rate` is about each step, and a reader
    consults it to see where the run went wrong. A step that answered from the
    other tier must not be labelled `eligible: true` in the artifact merely
    because a different gate already refused the run.
    """
    out = orch.dispose(artifact(
        s3vectors=half("s3vectors", p95=300.0),
        aoss=half("aoss", p95=300.0, observed=["s3vectors"],
                  eligible_claim=True)))
    assert out["verdict"] == "gate-failed"
    for rate in ("10", "90"):
        entry = out["by_rate"][rate]["aoss"]
        assert entry["eligible"] is False
        assert entry["ineligible_reasons"], (
            "the step that answered from the wrong tier is not named")
