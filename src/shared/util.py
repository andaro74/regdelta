"""Small shared helpers."""
import time


def retry(fn, attempts: int = 4, base_delay: float = 2.0):
    """Retry transient Bedrock/API throttles with exponential backoff so a
    blip doesn't burn the SQS receive count and DLQ a good document."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            retryable = "Throttling" in name or "Throttling" in str(e) \
                or "ServiceUnavailable" in name or "TooManyRequests" in str(e)
            if not retryable or i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))
