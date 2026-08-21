"""Small shared helpers."""
import threading
import time

#: HOW MANY TIMES THIS PROCESS HAS BACKED OFF, and on what.
#:
#: `retry` below sleeps 2s, then 4s, then 8s. Those seconds land INSIDE
#: whatever the caller was timing — for the retrieval path that is
#: `router.retrieve_traced`, i.e. the exact interval SPEC/06's Tier B
#: disposition is decided on. A single Titan throttle can therefore add up to
#: 14 seconds to one sample, and nothing said so: the call succeeded, the
#: latency was enormous, and the cause was invisible.
#:
#: SPEC/06's clause already excludes Bedrock throttles from the retrieval error
#: rate, on the grounds that they are shared by both tiers and caused by
#: neither. That exclusion is unenforceable without a count. This is the count.
#:
#: Locked because `loadtest/retrieval_load.py` is the first thing in this repo
#: to call into the retrieval path from many threads at once. Everywhere else
#: it is one request per process and the lock is uncontended.
_stats_lock = threading.Lock()
_retries: dict = {"total": 0, "by_error": {}}


def retry_stats() -> dict:
    """A snapshot. A copy, so a caller cannot edit the reading it just took."""
    with _stats_lock:
        return {"total": _retries["total"],
                "by_error": dict(_retries["by_error"])}


def reset_retry_stats() -> None:
    with _stats_lock:
        _retries["total"] = 0
        _retries["by_error"] = {}


def retry(fn, attempts: int = 4, base_delay: float = 2.0):
    """Retry transient Bedrock/API throttles with exponential backoff so a
    blip doesn't burn the SQS receive count and DLQ a good document."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            name = type(e).__name__
            retryable = "Throttling" in name or "Throttling" in str(e) \
                or "ServiceUnavailable" in name or "TooManyRequests" in str(e)
            if not retryable or i == attempts - 1:
                raise
            # Recorded BEFORE the sleep, so a run killed mid-backoff still
            # reports the throttle it was waiting on.
            with _stats_lock:
                _retries["total"] += 1
                _retries["by_error"][name] = _retries["by_error"].get(name, 0) + 1
            time.sleep(base_delay * (2 ** i))
