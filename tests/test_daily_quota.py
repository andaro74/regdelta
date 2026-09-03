"""The daily ceiling on Bedrock-backed answers (`api/daily_quota.py`).

These tests exist because the module's whole value is in its FAILURE
behaviour, and every interesting failure is one an integration test would never
reach: a full day's traffic, a conditional write losing a race, DynamoDB
unreachable. Each is driven here through a fake table rather than moto, because
what is being asserted is the SHAPE OF THE REQUEST — that the increment and the
check are one conditional write — and a fake that records the call is a stricter
witness of that than a library that would faithfully emulate either design.
"""
from __future__ import annotations

import calendar
import time
from decimal import Decimal

import pytest
from botocore.exceptions import ClientError

from api import daily_quota as quota

#: The two condition forms this fake understands, mapped to their meaning.
#: A LOOKUP RATHER THAN A REIMPLEMENTATION: the first version of this fake
#: hardcoded `current >= cap`, so every count assertion below was checking the
#: FAKE's arithmetic and would have passed unchanged against a module whose
#: condition said `#n <= :cap` and admitted 81. Evaluating the string the module
#: actually sends is what makes these tests witness the module.
#: eng-code-reviewer L1.
_CONDITIONS = {
    "attribute_not_exists(#n) OR #n < :cap": lambda cur, cap: cur is None or cur < cap,
    "attribute_not_exists(#n) OR #n <= :cap": lambda cur, cap: cur is None or cur <= cap,
}


class FakeTable:
    """A conditional-update DynamoDB table, only as far as `consume` uses it.

    Evaluates `ConditionExpression` and returns `Decimal`, because both are
    where a fake most easily stops resembling DynamoDB.
    """

    def __init__(self):
        self.items: dict[tuple, dict] = {}
        self.calls: list[dict] = []
        self.raise_with: Exception | None = None

    def update_item(self, **kw):
        self.calls.append(kw)
        if self.raise_with is not None:
            raise self.raise_with
        key = (kw["Key"]["pk"], kw["Key"]["sk"])
        item = self.items.setdefault(key, {})
        vals = kw["ExpressionAttributeValues"]
        expr = kw.get("ConditionExpression")
        if expr not in _CONDITIONS:
            raise AssertionError(
                f"fake cannot evaluate {expr!r}; teach it the new form rather "
                "than letting an unevaluated condition pass silently")
        current = item.get("count")
        if not _CONDITIONS[expr](current, vals[":cap"]):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException",
                           "Message": "the conditional request failed"}},
                "UpdateItem")
        item["count"] = (current or 0) + vals[":one"]
        item["ttl"] = vals[":ttl"]
        # Decimal, as the real client returns. `consume()` casts with `int()`;
        # an int here would leave that cast unwitnessed. eng-code-reviewer L2.
        return {"Attributes": {"count": Decimal(item["count"])}}


@pytest.fixture
def table(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(quota, "_table", lambda: fake)
    monkeypatch.setattr(quota, "enabled", lambda: True)
    return fake


@pytest.fixture
def cap(monkeypatch):
    def _set(n):
        monkeypatch.setattr(quota, "limit", lambda: n)
    return _set


# ------------------------------------------------------------------ the count
def test_consume_returns_a_rising_count(table, cap):
    cap(3)
    assert [quota.consume() for _ in range(3)] == [1, 2, 3]


def test_the_query_after_the_cap_is_refused(table, cap):
    cap(2)
    quota.consume()
    quota.consume()
    with pytest.raises(quota.QuotaExceededError):
        quota.consume()


def test_refusal_does_not_increment(table, cap):
    """The ceiling is a ceiling, not a high-water mark that keeps climbing.

    If a refused call still incremented, `count` would run away past the cap
    and the item would misreport the day for anyone reading it.
    """
    cap(1)
    quota.consume()
    for _ in range(5):
        with pytest.raises(quota.QuotaExceededError):
            quota.consume()
    assert table.items[("QUOTA#" + quota.day(), "QUERY")]["count"] == 1


# ------------------------------------------------- the shape of the request
def test_the_check_and_the_increment_are_one_conditional_write(table, cap):
    """THE POINT OF THE MODULE, asserted on the request rather than the result.

    A read-then-write implementation passes every count assertion above and is
    wrong: two callers at 199 both read 199, both write 200, and the ceiling
    admits 201. Only a condition evaluated by DynamoDB against the item it is
    updating is safe, so that is what is pinned here.
    """
    cap(5)
    quota.consume()
    call = table.calls[-1]
    assert "ConditionExpression" in call, "no condition: the check can interleave"
    assert "ADD #n :one" in call["UpdateExpression"]
    # STRICT `<`, asserted as its own property. `#n <= :cap` is the plausible
    # typo, is one character away, and admits cap+1.
    assert "< :cap" in call["ConditionExpression"]
    assert "<= :cap" not in call["ConditionExpression"]
    assert call["ExpressionAttributeValues"][":cap"] == quota.limit()


def test_the_count_is_returned_as_an_int_not_a_decimal(table, cap):
    """DynamoDB returns Decimal; the metric path and any future caller want int."""
    cap(2)
    result = quota.consume()
    assert result == 1 and isinstance(result, int)


def test_the_first_call_of_a_day_needs_no_initialisation(table, cap):
    """`ADD` creates the attribute, so there is no midnight cron to forget."""
    cap(2)
    assert table.items == {}
    assert quota.consume() == 1


def test_the_partition_key_carries_the_granted_prefix(table, cap):
    """`QUOTA#` is what `test_query_fn_iam` grants; a rename breaks the policy."""
    cap(1)
    quota.consume()
    (pk, sk), = table.items
    assert pk.startswith("QUOTA#") and sk == "QUERY"


# ------------------------------------------------------------------- the day
def test_a_new_utc_day_gets_a_fresh_allowance(table, cap):
    cap(1)
    day1 = calendar.timegm(time.strptime("2026-09-02", "%Y-%m-%d")) + 3600
    day2 = day1 + 86400
    quota.consume(now=day1)
    with pytest.raises(quota.QuotaExceededError):
        quota.consume(now=day1)
    assert quota.consume(now=day2) == 1


def test_the_day_boundary_is_utc_not_local():
    """The Bedrock allowance it shadows resets in UTC; a different rollover hour
    would admit a burst spanning both windows."""
    just_before = calendar.timegm(time.strptime("2026-09-03", "%Y-%m-%d")) - 1
    assert quota.day(just_before) == "2026-09-02"
    assert quota.day(just_before + 1) == "2026-09-03"


def test_ttl_outlives_the_day_it_counts(table, cap):
    cap(1)
    quota.consume()
    item, = table.items.values()
    midnight = calendar.timegm(time.strptime(quota.day(), "%Y-%m-%d"))
    assert item["ttl"] > midnight + 86400


def test_retry_after_points_at_the_next_utc_midnight():
    t = calendar.timegm(time.strptime("2026-09-02", "%Y-%m-%d")) + 86400 - 90
    assert quota.seconds_until_reset(now=t) == 90


def test_retry_after_is_never_zero():
    """A `Retry-After: 0` invites the immediate retry the ceiling exists to stop.

    The case that actually reaches the clamp is a FRACTIONAL `now` in the last
    second of the day: raw `int(0.5)` is 0. An integral `now` at the boundary
    rolls the day over instead and returns 86400, which leaves `max(1, ...)`
    unexercised — which is what this test used to do. eng-code-reviewer L3.
    """
    t = calendar.timegm(time.strptime("2026-09-03", "%Y-%m-%d")) - 0.5
    assert quota.seconds_until_reset(now=t) == 1


# ------------------------------------------------------------- failing closed
def test_an_unreachable_table_refuses_rather_than_admitting(table, cap):
    """THE DIVERGENCE FROM `response_cache`, and the reason this module exists.

    The cache treats any failure as a miss because a broken optimisation must
    not break a request. A quota is not an optimisation: if it cannot verify the
    ceiling, admitting the request spends money it was installed to bound. So
    this is the one place in the API where a dependency failure REFUSES.
    """
    cap(10)
    table.raise_with = RuntimeError("dynamodb unreachable")
    with pytest.raises(quota.QuotaUnavailableError):
        quota.consume()


def test_access_denied_refuses_and_is_not_mistaken_for_exhaustion(table, cap):
    """The M05-to-M06 failure, in the shape it would take here.

    An ungranted `QUOTA#` prefix arrives as AccessDeniedException. It must not
    be reported as QuotaExceededError: 429 reads as "working, come back tomorrow" and
    would hide a broken control exactly the way the cache's swallowed
    AccessDenied hid a dead cache for a month.
    """
    cap(10)
    table.raise_with = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "UpdateItem")
    with pytest.raises(quota.QuotaUnavailableError):
        quota.consume()


def test_a_zero_limit_closes_the_endpoint_without_touching_dynamodb(table, cap):
    """The declarative form of `put-function-concurrency 0`."""
    cap(0)
    with pytest.raises(quota.QuotaExceededError):
        quota.consume()
    assert table.calls == [], "a closed endpoint should not write"


def test_quota_is_off_when_there_is_no_state_table(monkeypatch):
    """Mirrors `response_cache.enabled()`; the local shim must still run."""
    monkeypatch.setattr(quota, "enabled", lambda: False)
    assert quota.consume() is None


def test_a_write_that_returns_no_count_refuses(table, cap):
    """Fail-closed all the way to the response parse.

    `.get("count", 0)` would have read a countless success as "zero consumed" —
    the wrong direction for this module, and invisible today because no caller
    reads the value. eng-code-reviewer L7.
    """
    cap(5)
    table.update_item = lambda **kw: {"Attributes": {}}
    with pytest.raises(quota.QuotaUnavailableError):
        quota.consume()
