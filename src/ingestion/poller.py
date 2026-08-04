"""Daily poller (SPEC/01). TODO: query Federal Register API (FDA,
RULE/PRORULE/NOTICE since high-water mark) + eCFR versioner for tracked
sections; enqueue one SQS message per new doc; idempotent via registry."""


def handler(event, context):
    raise NotImplementedError("SPEC/01")
