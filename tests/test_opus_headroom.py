"""The Opus headroom guard: what it refuses, and that it can be reached.

The human seat's instruction at the M06 window was that Opus must not reach
throttle. `L-ED2BADF9` is 2,592,000 tokens a day and reports
`Adjustable: false`, so crossing it is not a billing event — it is `make evals`
not working until 00:00 UTC.

ADR-0013: run everything the guard can refuse. Every branch below is exercised,
including the one that matters most — a CloudWatch read that fails must refuse
rather than report an empty meter.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

import check_opus_headroom as guard  # noqa: E402

from shared import config  # noqa: E402

CAP = config.BEDROCK_DAILY_TOKEN_CAP[config.MODEL_VERDICT]
NOW = dt.datetime(2026, 8, 21, 15, 0, tzinfo=dt.timezone.utc)


class _CW:
    """A CloudWatch stub that returns `per_call` for every statistic asked for.

    Records the calls so the dimension-spelling assertion below is about what
    was actually requested rather than about what this file assumes.
    """

    def __init__(self, per_call: float = 0.0, raises: Exception | None = None):
        self.per_call, self.raises, self.calls = per_call, raises, []

    def get_metric_statistics(self, **kw):
        if self.raises:
            raise self.raises
        self.calls.append(kw)
        return {"Datapoints": [{"Sum": self.per_call}]}


def test_a_fresh_day_fits_the_full_golden_set():
    """The positive half first. A guard that can only refuse is
    indistinguishable from one that is broken — and twenty questions on an
    empty day is the ordinary case."""
    report = guard.check(20, now=NOW, client=_CW(0.0))
    assert report["used_today"] == 0
    assert report["fits"] is True
    assert report["planned"] == round(20 * guard.OPUS_TOKENS_PER_QUERY)


def test_a_day_already_near_the_cap_refuses_the_smoke_subset():
    """Five questions is $0.24 and nobody would think twice about it. On a day
    that has already spent 95% of a cap that cannot be bought back, it is the
    call that takes `make evals` off the air until midnight."""
    # Four statistics are summed (2 metrics x 2 model-id spellings).
    per_call = CAP * 0.95 / 4
    report = guard.check(5, now=NOW, client=_CW(per_call))
    assert report["used_today"] == pytest.approx(CAP * 0.95, rel=1e-3)
    assert report["fits"] is False


def test_the_reserve_is_what_refuses_a_run_that_would_technically_fit():
    """The boundary the reserve exists for: a run with room under the cap but
    not enough left afterwards to diagnose anything.

    Without a reserve this passes and leaves the account with no Opus at all.
    """
    # Leave exactly one query's worth of headroom beyond the planned run.
    used = CAP - int(6 * guard.OPUS_TOKENS_PER_QUERY)
    report = guard.check(5, now=NOW, client=_CW(used / 4))

    assert report["remaining_after"] > 0, "it fits under the cap"
    assert report["remaining_after"] < report["reserve"]
    assert report["fits"] is False, "and it is still refused, on the reserve"


def test_the_reserve_is_stated_in_queries_not_only_in_tokens():
    """A reserve nobody can size is a number chosen for comfort."""
    report = guard.check(1, now=NOW, client=_CW(0.0))
    assert report["reserve"] == int(CAP * guard.RESERVE_FRACTION)
    assert "uncached" in report["reserve_basis"]


def test_an_unreadable_meter_refuses_rather_than_reporting_zero(monkeypatch):
    """THE ONE THAT MATTERS. An unreadable meter and an empty one look
    identical to a caller that swallows the error, and 'probably fine' is how a
    non-adjustable cap gets crossed."""
    monkeypatch.setattr(guard, "spent_today",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            RuntimeError("AccessDenied")))
    monkeypatch.setattr(sys, "argv",
                        ["check_opus_headroom.py", "--questions", "5"])
    assert guard.main() == 2, "exit 2 — the meter could not be read"


def test_both_model_id_spellings_are_summed():
    """`config.MODEL_VERDICT` is a cross-region INFERENCE PROFILE; CloudWatch's
    `ModelId` dimension carries the foundation model the call routed to.
    Reading only one spelling silently reports zero — which this guard would
    then read as a fresh day."""
    cw = _CW(1000.0)
    guard.check(1, now=NOW, client=cw)

    asked = {c["Dimensions"][0]["Value"] for c in cw.calls}
    assert config.MODEL_VERDICT in asked
    assert config.MODEL_VERDICT.removeprefix("us.") in asked
    assert {c["MetricName"] for c in cw.calls} == {
        "InputTokenCount", "OutputTokenCount"}


def test_the_window_starts_at_midnight_utc():
    """The cap is a DAILY cap on UTC days. A rolling 24-hour window would
    refuse runs the cap permits and permit runs it refuses."""
    cw = _CW(0.0)
    guard.check(1, now=NOW, client=cw)
    starts = {c["StartTime"] for c in cw.calls}
    assert starts == {NOW.replace(hour=0, minute=0, second=0, microsecond=0)}


def test_the_per_query_figure_is_the_measured_one():
    """5,881.8 is 5,246.3 input + 635.5 output, CloudWatch, 60 invocations.
    Pinned because every refusal here is derived from it."""
    assert pytest.approx(5246.3 + 635.5) == guard.OPUS_TOKENS_PER_QUERY


def test_the_cap_this_guards_is_the_non_adjustable_one():
    report = guard.check(1, now=NOW, client=_CW(0.0))
    assert report["daily_cap"] == 2_592_000
    assert report["cap_adjustable"] is False
