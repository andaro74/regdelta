"""The $20 ceiling refuses, and refuses for the right reason.

The human seat set this ceiling at M06 open. A ceiling nobody has watched
refuse anything is a number in a file, so every branch that can say no is
exercised here, and `milestones/M06/budget_guard_mutations.py` breaks each one
in turn to check the test would notice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "loadtest"))

import budget

from shared import config

OPUS = "us.anthropic.claude-opus-4-6-v1"
SONNET = "us.anthropic.claude-sonnet-4-6"
TITAN = "amazon.titan-embed-text-v2:0"

#: The measured per-query shape, from CloudWatch over the 60 golden calls of
#: the M05 window. Used rather than round numbers so a failure here is a
#: failure about this system.
#:
#: ROUNDED TO WHOLE TOKENS from the reported means (5,246.3 / 635.5 / 241.5 /
#: 30.0), which is why the figures below are $0.0476370 per query rather than
#: the $0.0476232 quoted from the means in
#: milestones/M06/spec06-disposition-amendment.md. Both are stated rather than
#: reconciled away: the fourth decimal is not the point, and a test that
#: silently used one number while citing the other would be the kind of quiet
#: mismatch this suite exists to catch.
VERDICT = {"input": 5246, "output": 636}
SUPERVISOR = {"input": 242, "output": 30}
PER_QUERY_USD = (5246 * 5.50 + 636 * 27.50 + 242 * 3.30 + 30 * 16.50) / 1e6


def _query_plan(label: str, n: int) -> budget.Plan:
    return budget.Plan(label, [
        budget.Call(OPUS, n, **VERDICT),
        budget.Call(SONNET, n, **SUPERVISOR),
    ])


# ------------------------------------------------------------------ pricing
def test_one_query_costs_what_the_account_measured():
    """$0.047623, re-derivable from the rates and the token counts."""
    one = _query_plan("one", 1).usd()
    assert one == pytest.approx(PER_QUERY_USD, rel=1e-9)
    assert 0.047 < one < 0.048


def test_cache_reads_and_writes_are_priced_at_their_own_multipliers():
    """Folding them into `input` under-reports a cached run — our direction."""
    plain = budget.cost_usd(OPUS, input=1000)
    assert budget.cost_usd(OPUS, cache_read=1000) == pytest.approx(plain * 0.10)
    assert budget.cost_usd(OPUS, cache_write=1000) == pytest.approx(plain * 1.25)


def test_an_unpriced_model_raises_rather_than_costing_zero():
    with pytest.raises(budget.UnpricedModelError):
        budget.cost_usd("us.anthropic.claude-invented-9", input=1_000_000)
    with pytest.raises(budget.UnpricedModelError):
        budget.check_plan(budget.Plan(
            "typo", [budget.Call("us.anthropic.claude-invented-9", 10, input=5)]))


# ------------------------------------------------------------- plan refusals
def test_a_plan_inside_the_ceiling_is_reported_not_refused():
    report = budget.check_plan(_query_plan("small", 100), ceiling=20.0)
    assert report["estimated_usd"] == pytest.approx(100 * PER_QUERY_USD, abs=1e-3)
    assert report["ceiling_usd"] == 20.0
    assert "ESTIMATE" in report["basis"]


def test_a_plan_over_the_dollar_ceiling_is_refused_before_spending():
    with pytest.raises(budget.BudgetExceededError, match="Nothing has been spent"):
        budget.check_plan(_query_plan("too big", 500), ceiling=20.0)


def test_the_default_ceiling_is_the_twenty_dollars_the_seat_approved():
    assert config.LOADTEST_BUDGET_USD == 20.00
    # 420 queries is $20.00; 421 is over. The default must bite with no
    # `ceiling=` argument, because that is how every real caller will use it.
    with pytest.raises(budget.BudgetExceededError):
        budget.check_plan(_query_plan("default", 500))


def test_a_plan_over_a_non_adjustable_daily_cap_is_refused_even_when_cheap():
    """The refusal money cannot buy, and the one M06 was written around.

    440 queries is $20.95 — over the dollar ceiling too — so the quota refusal
    is exercised at a ceiling deliberately raised out of the way. Otherwise
    this test would pass on the dollar branch and claim to have checked the
    quota branch, which is this repo's most-repeated instrument defect.
    """
    with pytest.raises(budget.QuotaExceededError, match="NON-ADJUSTABLE"):
        budget.check_plan(_query_plan("quota", 500), ceiling=10_000.0)


def test_the_quota_refusal_counts_what_today_already_spent():
    """A plan that fits a fresh day need not fit this one."""
    plan = _query_plan("late in the day", 100)
    budget.check_plan(plan, ceiling=10_000.0)          # fresh day: fine
    with pytest.raises(budget.QuotaExceededError, match="already used today"):
        budget.check_plan(plan, ceiling=10_000.0,
                          spent_today={OPUS: 2_400_000})


def test_the_report_says_whether_it_knew_what_today_had_spent():
    """A pass with no `spent_today` is optimistic and must not read otherwise."""
    assert budget.check_plan(_query_plan("a", 10))["spent_today_supplied"] is False
    assert budget.check_plan(_query_plan("b", 10),
                             spent_today={OPUS: 0})["spent_today_supplied"] is True


def test_cache_tokens_count_against_the_daily_cap():
    """Billed differently, quota-counted the same. Getting this backwards
    under-counts a cached run against a cap that cannot be raised."""
    c = budget.Call(OPUS, 1, input=100, output=10, cache_read=1000, cache_write=50)
    assert c.tokens() == 1160
    assert c.usd() < budget.cost_usd(OPUS, input=1150, output=10)


# ------------------------------------------------------------------- meter
def test_the_meter_refuses_the_next_call_before_it_crosses():
    """Reserve-then-spend. Detecting an overshoot is a log line, not a ceiling."""
    meter = budget.Meter(ceiling=0.10, label="tiny")
    for _ in range(2):
        meter.reserve(OPUS, **VERDICT)
        meter.record(OPUS, **VERDICT)
    assert meter.spent() == pytest.approx(2 * 0.046331, abs=1e-4)

    with pytest.raises(budget.BudgetExceededError):
        meter.reserve(OPUS, **VERDICT)
    # And it stopped BELOW the ceiling, which is the whole point.
    assert meter.spent() < 0.10
    assert meter.aborted and "would cross" in meter.aborted


def test_the_meter_reports_measured_spend_per_model():
    meter = budget.Meter(ceiling=20.0)
    meter.record(OPUS, **VERDICT)
    meter.record(SONNET, **SUPERVISOR)
    meter.record(TITAN, input=10)
    report = meter.report()
    assert set(report["by_model"]) == {OPUS, SONNET, TITAN}
    assert report["by_model"][OPUS]["calls"] == 1
    # abs=1e-6 because `Meter.report()` rounds to six decimals — a tenth of a
    # microdollar — deliberately, so an artifact carries a money figure rather
    # than a float artefact. The tolerance matches the rounding rather than
    # being loosened until it passed.
    assert report["actual_usd"] == pytest.approx(
        PER_QUERY_USD + budget.cost_usd(TITAN, input=10), abs=1e-6)
    assert report["aborted"] is None
    assert "MEASURED" in report["basis"]


def test_the_titan_only_disposition_plan_is_nowhere_near_the_ceiling():
    """The measurement the seat approved: 90,000 retrievals, embeddings only.

    Anchors the claim made to the human seat — that the Tier B disposition is
    cents — to something that fails if the rates or the arithmetic move.
    """
    plan = budget.Plan("tier-disposition", [budget.Call(TITAN, 90_000, input=10)])
    report = budget.check_plan(plan)
    assert report["estimated_usd"] < 0.05
    assert plan.tokens_by_model() == {TITAN: 900_000}


def test_the_500_user_profile_is_refused_on_quota_not_on_price():
    """SPEC/06's clause as written, priced. Both refusals fire; quota is the
    one that cannot be bought, and this pins which is which."""
    six_runs = _query_plan("spec06 500-user x6", 55_202)
    with pytest.raises(budget.BudgetExceededError):
        budget.check_plan(six_runs)
    with pytest.raises(budget.QuotaExceededError, match=r"125\.\dx"):
        budget.check_plan(six_runs, ceiling=1_000_000.0)
