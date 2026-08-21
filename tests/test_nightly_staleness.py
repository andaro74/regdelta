"""The nightly's staleness metric, and the state in which it used to go silent.

`EvalStalenessHours` is the only thing watching whether anyone still runs the
golden set. The regression alarm watches `EvalPassRate`, which is published
only when a run records one — so if nobody runs anything, the regression alarm
has nothing to watch and this metric is what says so.

THE HOLE: with no `EvalPassRate` ever published, `_eval_staleness` returned
`hours: None` and `handler` omitted the metric entirely. The alarm was
`NOT_BREACHING`, so INSUFFICIENT_DATA was not an alarm. Nobody had measured
anything, and nothing said so — in exactly the state the watch exists for.
`src/ops/nightly.py` asserted the opposite in a comment.
eng-code-reviewer, M06.

Offline: every AWS boundary is stubbed, no network, no cost.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ops import nightly


@pytest.fixture
def emitted(monkeypatch):
    """Capture what `handler` publishes, and stub everything it reads."""
    captured: list[tuple] = []
    monkeypatch.setattr(nightly.observability, "emit",
                        lambda m, d, p=None: captured.append((m, d, p)))
    monkeypatch.setattr(nightly, "_tier",
                        lambda: {"tier": "s3vectors", "hot_tier_up": False,
                                 "error": None})
    monkeypatch.setattr(nightly, "_corpus",
                        lambda: {"available": True, "documents": 52,
                                 "documents_sha": "abc123"})
    monkeypatch.setattr(nightly, "_graph_logic",
                        lambda: {"errors": [], "undated": [], "checked": ["a"]})
    return captured


def test_the_metric_is_emitted_when_a_pass_rate_has_never_been_recorded(
        monkeypatch, emitted):
    """THE FINDING. This is the state the alarm exists for, and it produced no
    datapoint at all."""
    monkeypatch.setattr(nightly, "_eval_staleness",
                        lambda: {"hours": None,
                                 "reason": "no EvalPassRate ever published"})
    nightly.handler({}, None)

    metrics = emitted[0][0]
    assert "EvalStalenessHours" in metrics, (
        "no datapoint means INSUFFICIENT_DATA, and the one state this watch is "
        "for produced silence")
    assert metrics["EvalStalenessHours"][0] == float(nightly.NEVER_RECORDED_HOURS)


def test_the_metric_is_emitted_when_the_cloudwatch_read_itself_failed(
        monkeypatch, emitted):
    """The other route to `hours: None`. An unreadable meter must not be
    reported as a fresh one — the same argument the Opus headroom guard makes
    about its own read."""
    monkeypatch.setattr(nightly, "_eval_staleness",
                        lambda: {"hours": None,
                                 "reason": "AccessDeniedException: denied"})
    nightly.handler({}, None)
    assert emitted[0][0]["EvalStalenessHours"][0] == float(
        nightly.NEVER_RECORDED_HOURS)


def test_the_sentinel_is_above_any_threshold_anyone_would_set(monkeypatch, emitted):
    """A sentinel below the alarm threshold is a sentinel that says 'healthy'.

    The alarm fires above `STALENESS_ALARM_HOURS`, which defaults to one week.
    """
    assert nightly.NEVER_RECORDED_HOURS > nightly.STALENESS_ALARM_HOURS * 10


def test_a_real_staleness_reading_is_passed_through_unchanged(monkeypatch, emitted):
    """The sentinel must not swallow the measurement. A run recorded three
    hours ago reports three hours, not a year."""
    monkeypatch.setattr(nightly, "_eval_staleness",
                        lambda: {"hours": 3.5, "last_at": "2026-08-21T00:00:00Z"})
    nightly.handler({}, None)
    assert emitted[0][0]["EvalStalenessHours"][0] == 3.5


def test_the_reason_survives_into_the_properties(monkeypatch, emitted):
    """The metric says "at least this stale"; only the log line can say WHY,
    and the two answers — never recorded, versus the read failed — need
    different actions."""
    monkeypatch.setattr(nightly, "_eval_staleness",
                        lambda: {"hours": None, "reason": "AccessDenied"})
    nightly.handler({}, None)
    assert emitted[0][2]["eval_staleness"]["reason"] == "AccessDenied"


def test_the_nightly_still_reports_ok_when_only_staleness_is_unknown(
        monkeypatch, emitted):
    """Not being able to read the staleness meter is not the graph being
    broken. `NightlyCheckFailed` is about the deterministic checks; conflating
    them would page for the wrong reason and get the alarm muted."""
    monkeypatch.setattr(nightly, "_eval_staleness",
                        lambda: {"hours": None, "reason": "AccessDenied"})
    result = nightly.handler({}, None)
    assert result["status"] == "ok"
    assert emitted[0][0]["NightlyCheckFailed"][0] == 0.0
