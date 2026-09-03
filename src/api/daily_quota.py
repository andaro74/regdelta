"""A hard per-day ceiling on the Bedrock-backed runs `/query` and `/resume` start.

## Why this exists

`POST /query` is unauthenticated (SPEC/04 declares that out of scope) and every
uncached call spends Opus. The controls that existed before this module bound
the RATE and not the DAY:

  * API Gateway throttling is a capacity limit. At the 20 rps / 40 burst this
    stack shipped with it permitted 1,728,000 requests a day; it is now 1/5,
    which is a real bound on the REFUSAL path but still says nothing about how
    many of those requests are allowed to reach a model.
  * Lambda reserved concurrency limits how many run AT ONCE, which changes how
    fast the money goes, not how much of it there is to spend.

What actually bounded a day was an AWS quota nobody chose:
`config.BEDROCK_DAILY_TOKEN_CAP`, whose Opus 4.6 entry is 2,592,000
tokens/day and reports `Adjustable: false`.
At 5,881.8 Opus tokens per uncached `/query` that is 440 queries, ~$21, and an
account-wide non-renewable allowance gone until 00:00 UTC.

WHAT THIS MODULE BOUNDS IS THE BILL, AND ONLY THE BILL. An earlier draft of this
docstring claimed it also protected `make evals` from a stranger, on the grounds
that 80 queries leave 82% of the Opus allowance unspent. That is arithmetically
true and operationally backwards, because `make evals` drives the DEPLOYED API
and so draws on this same counter: the surviving Opus is not reachable through
the endpoint. The honest table is

    to deny `make evals`     requests     defender's spend
    before                        440               ~$21
    after                          80              $3.80

— the cost to the attacker fell 5.5x while the cost to the defender fell 82%.
That trade was made deliberately and is worth it, but it is a trade, not a
free win, and nobody should read this file as saying the gate got safer.

TWO ESCAPES EXIST for the operator, and they are the reason the trade is
acceptable. `make agent-evals` and `make baseline` run the graph in-process and
never reach this counter at all (see below), so the graph is always reachable.
And the day can be reset outright with the operator's own credentials:

    aws dynamodb delete-item --table-name "$STATE_TABLE" --region us-west-2 \
      --key '{"pk":{"S":"QUOTA#<YYYY-MM-DD>"},"sk":{"S":"QUERY"}}'

Deliberately an IAM-gated console action rather than a bypass header: a header
would be one more unauthenticated way to spend money, which is the thing this
file exists to stop. security-reviewer F2.

## What is counted, and what is not

CACHE HITS ARE NOT COUNTED. `/query` consults `response_cache` first and returns
a stored answer without entering the graph, so a hit spends nothing and must not
consume anyone's allowance. Counting requests instead of misses would let one
caller replaying a single cached question lock out every other visitor — a
denial of service built out of the control meant to prevent one.

The counter is therefore incremented at exactly the two points where a model
call becomes inevitable: after the cache misses in `/query`, and after the
resume token verifies in `/resume`. A refused resume never counts; refusing to
answer and charging for it are different things.

ONE COUNTER FOR THE WHOLE ACCOUNT, not per caller. Per-IP would be the intuitive
shape and is the wrong one here: the thing being protected is a shared,
non-renewable Bedrock allowance, and an attacker with many addresses would
exhaust it while every per-IP bucket still read as healthy. A single global
ceiling bounds the bill under every distribution of callers. The cost is that a
flood denies the demo to legitimate visitors for the rest of the day — accepted,
because the alternative is denying `make evals` to the operator instead.

WHAT THIS COUNTER DOES NOT SEE, stated so nobody reads it as total spend.
`evals/serve_local.py` is a stdlib shim that calls `graph.build_graph` directly
rather than importing this app, so `make agent-evals` and `make baseline` never
reach `consume()` — they spend from the same account-wide Opus allowance while
this number stays still. `make evals` and `make smoke` DO count, because they
drive the deployed API.

That asymmetry is useful rather than accidental: it leaves the operator a path
to the graph that a flood cannot take away. But it means this ceiling bounds
what STRANGERS can spend, not what the account can spend, and the two must not
be confused when reading the count off the table.

## Fail CLOSED, unlike the cache

`response_cache` treats every failure as a miss, on the stated grounds that "a
cache that can break a request is worse than no cache: it converts a
performance optimisation into an availability dependency". That reasoning is
correct there and does not transfer. A cache is an optimisation; a quota is a
CONTROL, and a control whose failure mode is "stop controlling" is not one. If
this module cannot reach DynamoDB it cannot know whether the ceiling has been
reached, and the safe reading of "unknown", on an unauthenticated endpoint that
spends money, is to refuse.

The refusal is a 503 and not a 429, because the two say different things: 429 is
"you have had your share today", 503 is "I could not find out". Collapsing them
would hide a broken quota behind a message that looks like it working — which is
exactly how the M05-to-M06 cache outage stayed invisible for a month.
"""
from __future__ import annotations

import calendar
import logging
import time

# MODULE SCOPE, not inside `consume()`. In the function it sat OUTSIDE the
# `try`, so an ImportError escaped as a 500 rather than the honest 503 this
# module exists to return — `api.py` catches only the two exceptions below.
# botocore is a hard dependency of everything else in `src/api/`, so there is
# no cold-start argument for deferring it. eng-code-reviewer L6.
from botocore.exceptions import ClientError

log = logging.getLogger("regdelta.quota")

#: Grace on the item's TTL. The counter is only meaningful on its own UTC day,
#: but DynamoDB deletes expired items on its own schedule (up to 48h), so a
#: tight TTL would buy nothing and a loose one costs a few bytes.
_TTL_GRACE_SECONDS = 2 * 24 * 3600


class QuotaExceededError(Exception):
    """The day's ceiling has been reached. Maps to 429."""


class QuotaUnavailableError(Exception):
    """The ceiling could not be checked. Maps to 503 — see the module docstring."""


def enabled() -> bool:
    """On exactly when there is a table to count in.

    THIS IS THE ONE FAIL-OPEN IN A FAIL-CLOSED MODULE, and saying so is the
    point of this docstring. An absent STATE_TABLE leaves the endpoint uncapped
    rather than refusing, which is the opposite of what the module docstring
    argues for everywhere else — and absence of an environment variable is
    exactly the shape a misconfiguration takes.

    It is deliberate and it is narrow. The alternative is worse: refusing when
    STATE_TABLE is unset would break `fastapi.testclient` in every unit test and
    any offline use of the app object, neither of which can spend money, in
    order to guard a state the stack cannot produce — `core_stack.py` sets
    STATE_TABLE on QueryFn unconditionally.

    "Cannot produce" is a claim about a template, so it is PINNED IN A TEMPLATE
    TEST rather than asserted here: `test_api_hosting` requires QueryFn's
    environment to carry both STATE_TABLE and QUERY_DAILY_LIMIT. Without that
    test this docstring is the only thing standing between a refactor and a
    silently uncapped endpoint. security-reviewer F6, eng-code-reviewer M2.
    """
    from shared import config

    return bool(config.STATE_TABLE)


def limit() -> int:
    from shared import config

    return config.QUERY_DAILY_LIMIT


def day(now: float | None = None) -> str:
    """The UTC day this request counts against.

    UTC rather than local time, because the Bedrock quota it shadows resets in
    UTC. A counter rolling over at a different hour than the allowance it
    protects would permit a burst spanning both.
    """
    return time.strftime(
        "%Y-%m-%d", time.gmtime(now if now is not None else time.time()))


def _ttl_for(day_key: str) -> int:
    midnight = calendar.timegm(time.strptime(day_key, "%Y-%m-%d"))
    return midnight + 86400 + _TTL_GRACE_SECONDS


def _table():
    import boto3

    from shared import config

    return boto3.resource("dynamodb", region_name=config.REGION).Table(
        config.STATE_TABLE)


def consume(now: float | None = None) -> int | None:
    """Claim one unit of today's allowance, or refuse. Returns the new count.

    None means the quota is switched off (no STATE_TABLE).

    ONE CONDITIONAL WRITE, never read-then-write. Two concurrent requests that
    each read 199 and each write 200 would both be admitted — and under exactly
    the conditions the ceiling exists for, which is many callers at once. The
    condition is evaluated by DynamoDB against the item it is updating, so the
    check and the increment cannot interleave.

    `ADD` creates the attribute when it is absent, which is what lets the first
    request of a new UTC day work with no initialisation and no midnight cron.
    """
    if not enabled():
        return None

    cap = limit()
    if cap <= 0:
        # A configured zero is a deliberate closure, not an error. It is
        # reported as exhausted rather than unavailable because the ceiling IS
        # known — it is nought.
        log.warning("daily quota is %s: refusing every query", cap)
        raise QuotaExceededError(f"daily limit is {cap}")

    day_key = day(now)
    try:
        result = _table().update_item(
            Key={"pk": f"QUOTA#{day_key}", "sk": "QUERY"},
            UpdateExpression="SET #ttl = :ttl ADD #n :one",
            ConditionExpression="attribute_not_exists(#n) OR #n < :cap",
            ExpressionAttributeNames={"#n": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1, ":cap": cap, ":ttl": _ttl_for(day_key)},
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log.warning("daily quota exhausted day=%s cap=%s", day_key, cap)
            raise QuotaExceededError(f"{cap} queries already served on {day_key}") from e
        log.error("daily quota could not be checked, refusing: %s", e)
        raise QuotaUnavailableError(str(e)) from e
    except Exception as e:
        # Throttling, credentials, an AccessDenied on a prefix somebody forgot
        # to grant. NOT swallowed: this is precisely the failure the M05-to-M06
        # cache outage taught this repo to make loud rather than silent.
        log.error("daily quota could not be checked, refusing: %s", e)
        raise QuotaUnavailableError(str(e)) from e

    # NO DEFAULT. `.get("count", 0)` would report "zero consumed" for a
    # successful write whose response lacked the attribute — the wrong direction
    # for a fail-closed module, even though the value is currently only used as
    # a metric. A response that cannot say how many were consumed has not
    # verified the ceiling. eng-code-reviewer L7.
    counted = result.get("Attributes", {}).get("count")
    if counted is None:
        log.error("quota write returned no count, refusing: %r", result)
        raise QuotaUnavailableError("update returned no count")
    return int(counted)


def seconds_until_reset(now: float | None = None) -> int:
    """For `Retry-After`. Seconds to the next UTC midnight, never below 1."""
    t = now if now is not None else time.time()
    midnight = calendar.timegm(time.strptime(day(t), "%Y-%m-%d"))
    return max(1, int(midnight + 86400 - t))
