"""Per-node instrumentation (SPEC/06 Observability).

SPEC/06 asks for "X-Ray (or Langfuse) span per graph node: retrieval ms,
tokens, cache hit/miss, tier, confidence" and a CloudWatch dashboard reading
"p50/p95, cache hit rate, Bedrock cost/query, HITL rate".

## Three choices, each with the alternative and why it lost

**Langfuse is not available to this project**, and the reason is already
written down: `shared/config.py` forces `LANGSMITH_TRACING`,
`LANGCHAIN_TRACING_V2` and `LANGSMITH_OTEL_ENABLED` to false as a *data-egress
control*, because those uploaders send prompts, inputs and outputs — here, a
user's company profile and the regulatory analysis derived from it — to a
third-party SaaS endpoint. `tests/test_no_telemetry_egress.py` guards it.
Adding a different SaaS tracer would be that decision reversed by implication.
So: X-Ray.

**EMF, not `cloudwatch:PutMetricData`.** Metrics are emitted as Embedded Metric
Format lines on stdout, which the Lambda log driver extracts. The alternative
is an API call per request, which (a) adds latency to the path being measured,
(b) needs an IAM grant on the internet-facing query role, and (c) can be
THROTTLED — and a metric that silently fails to publish because CloudWatch
throttled it is an instrument reporting on its own availability rather than on
the system. ADR-0013. EMF has none of those: the line is already being written.

**The X-Ray subsegment is emitted over the daemon's UDP socket, with no SDK.**
`aws-xray-sdk` would be a new runtime dependency in the deployed function, and
CLAUDE.md says to ask first. This repo already hand-builds the one other
protocol it needs rather than take a client for it — `retrieval/aoss_client.py`
signs SigV4 on top of botocore instead of pulling `opensearch-py` — and the
daemon protocol is a UDP datagram carrying a two-line JSON document, which is
smaller than the SigV4 signing this repo already owns.

**That trade is on file, not hidden.** If the seat prefers the SDK, this module
is the only file that changes. What the SDK would add that this does not:
automatic patching of boto3 calls into subsegments, sampling-rule polling, and
streaming of oversized segments. None of the three is needed for one subsegment
per graph node, and the first would double-count the Bedrock time this module
already records.

## The instrument reports on itself (ADR-0013)

An emitter that fails silently is the failure mode this repo is named for. A
UDP send cannot be acknowledged, so "the datagram was sent" is the strongest
honest claim available — and that is exactly what `emission_report()` returns.
It distinguishes:

    "off"        no daemon address in the environment; nothing was attempted
    "unsampled"  X-Ray declined to sample this trace; nothing was attempted
    "sent"       a datagram left this process
    "failed"     the send raised, with the exception recorded

It does NOT say "the span is in X-Ray", because this process cannot know that.
The live check that closes that gap is a `GetTraceSummaries` call after a real
request, and it belongs in the milestone evidence rather than here.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager

#: CloudWatch namespace for every metric in this file. One namespace, because
#: the dashboard is one dashboard and cross-namespace math is not expressible
#: in a metric expression.
NAMESPACE = "RegDelta"

#: X-Ray's UDP header. The daemon expects two lines: this, then the segment.
_XRAY_HEADER = b'{"format":"json","version":1}\n'

#: What this process last did about a span, per ADR-0013. Module-level for the
#: same reason `nodes._last_stop` is, and with the same stated precondition:
#: one request at a time per process. Lambda serves one request per execution
#: environment and `evals/serve_local.py` is single-threaded, so nothing today
#: can mis-attribute one request's emission state to another.
#:
#: THE LOAD DRIVER IS THE FIRST THING IN THIS REPO THAT BREAKS THAT
#: PRECONDITION — it runs many retrievals concurrently in one process — which
#: is why it reads `span_result` off the context manager's own yielded object
#: rather than off this dict. The dict is for the request path.
_last_emit: dict = {"status": "off", "detail": None}


def emission_report() -> dict:
    """What this process last did about a span. Never a claim about X-Ray."""
    return dict(_last_emit)


# --------------------------------------------------------------------- EMF
def metric_line(metrics: dict[str, tuple[float, str]],
                dimensions: dict[str, str],
                properties: dict | None = None) -> dict:
    """One CloudWatch Embedded Metric Format document.

    `metrics` maps name -> (value, unit). `dimensions` are what the metric is
    sliced by and are the expensive half: every distinct combination is a
    separate CloudWatch metric, billed and stored. `properties` are searchable
    in Logs Insights and cost nothing.

    THE SPLIT IS LOAD-BEARING AND IS WHY THIS FUNCTION EXISTS RATHER THAN A
    DICT LITERAL AT EACH CALL SITE. `trace_id` and `thread_id` are unbounded —
    one value per request — and putting either in `dimensions` would mint a new
    CloudWatch metric per request. That is the classic EMF cost incident, and
    it is invisible until the bill arrives, because the dashboard looks fine.
    So high-cardinality fields go in `properties` and this function does not
    offer a way to promote them.
    """
    return {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                # One dimension SET, listing every dimension key. A metric is
                # emitted only for this exact combination.
                "Dimensions": [sorted(dimensions)] if dimensions else [[]],
                "Metrics": [{"Name": name, "Unit": unit}
                            for name, (_, unit) in sorted(metrics.items())],
            }],
        },
        **dimensions,
        **{name: value for name, (value, _) in metrics.items()},
        **(properties or {}),
    }


def emit(metrics: dict[str, tuple[float, str]],
         dimensions: dict[str, str],
         properties: dict | None = None,
         *, _print=print) -> dict:
    """Write one EMF line to stdout and return it.

    Returned as well as printed so a test can assert the document rather than
    capture stdout and re-parse it — the same reason `janitor.handler._log`
    returns what it printed.
    """
    doc = metric_line(metrics, dimensions, properties)
    _print(json.dumps(doc, sort_keys=True, default=str))
    return doc


# ------------------------------------------------------------------- X-Ray
def _trace_context() -> tuple[str | None, str | None, bool]:
    """(trace id, parent id, sampled) from Lambda's `_X_AMZN_TRACE_ID`.

    The header looks like `Root=1-5759e988-...;Parent=53995c3f42cd8ad8;Sampled=1`.
    Absent means we are not running under an X-Ray-traced invocation — a local
    shim, a unit test, the load driver — and the honest answer is "no context",
    not a fabricated one. A subsegment with an invented trace id would attach
    to nothing and read as a lost span.
    """
    header = os.environ.get("_X_AMZN_TRACE_ID", "")
    parts = dict(p.split("=", 1) for p in header.split(";") if "=" in p)
    return parts.get("Root"), parts.get("Parent"), parts.get("Sampled") == "1"


def _daemon_address() -> tuple[str, int] | None:
    """Where the X-Ray daemon is listening, per `AWS_XRAY_DAEMON_ADDRESS`.

    Lambda sets it when the function has active tracing. Unset means tracing is
    off for this function, which is a deployment fact and not an error.
    """
    raw = os.environ.get("AWS_XRAY_DAEMON_ADDRESS", "")
    if ":" not in raw:
        return None
    host, _, port = raw.rpartition(":")
    try:
        return host, int(port)
    except ValueError:
        return None


def _subsegment(name: str, start: float, end: float,
                annotations: dict, metadata: dict) -> dict | None:
    """The document, or None when there is no trace to attach it to."""
    trace_id, parent_id, sampled = _trace_context()
    if not (trace_id and parent_id and sampled):
        return None
    return {
        "name": name,
        # 16 hex chars, X-Ray's segment id format. `os.urandom` rather than
        # `random`: this is an identifier that must not collide across
        # concurrent workers in the load driver, and `random` is seeded per
        # process, not per thread.
        "id": os.urandom(8).hex(),
        "trace_id": trace_id,
        "parent_id": parent_id,
        "type": "subsegment",
        "start_time": start,
        "end_time": end,
        # Annotations are INDEXED and filterable, and X-Ray caps them at 50 per
        # trace with alphanumeric-plus-underscore keys and scalar values. The
        # low-cardinality facts go here so a trace can be found by them.
        "annotations": {k: v for k, v in annotations.items() if v is not None},
        # Metadata is not indexed and takes anything JSON-serialisable.
        "metadata": {"regdelta": metadata},
    }


def send_subsegment(doc: dict | None, *, _socket=None) -> tuple[str, str | None]:
    """Datagram to the daemon. Returns (status, detail) — never raises.

    Never raises because an instrument that can fail a request is worse than no
    instrument: it converts observability into an availability dependency, the
    same argument `api/response_cache.get` makes about the cache. But the
    failure is RECORDED rather than swallowed, which is the difference between
    failing open and lying.
    """
    if doc is None:
        return "unsampled", None
    address = _daemon_address()
    if address is None:
        return "off", None
    sock = _socket or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(_XRAY_HEADER + json.dumps(doc, default=str).encode("utf-8"),
                    address)
        return "sent", None
    except OSError as e:
        return "failed", f"{type(e).__name__}: {e}"[:200]
    finally:
        if _socket is None:
            sock.close()


class Span:
    """One node's measurement, mutable while the node runs.

    The node writes its own facts onto this object; the context manager below
    times it and emits. Yielded rather than returned so that a node which
    raises still produces a span carrying `error: true` — a node that fails is
    the one you most want a span for, and a decorator that emits on the return
    path only would lose exactly those.
    """

    __slots__ = (
        "annotations",
        "error",
        "metadata",
        "metrics",
        "name",
        "span_result",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.annotations: dict = {}
        self.metadata: dict = {}
        self.metrics: dict[str, tuple[float, str]] = {}
        self.error: str | None = None
        self.span_result: tuple[str, str | None] = ("off", None)

    def annotate(self, **facts) -> None:
        """Low-cardinality, indexed, filterable in X-Ray."""
        self.annotations.update(facts)

    def detail(self, **facts) -> None:
        """Anything JSON-serialisable; not indexed, not a dimension."""
        self.metadata.update(facts)

    def measure(self, name: str, value: float, unit: str = "None") -> None:
        """A CloudWatch metric emitted alongside this node's latency."""
        self.metrics[name] = (value, unit)


@contextmanager
def node_span(name: str, *, dimensions: dict[str, str] | None = None,
              properties: dict | None = None, _emit=None, _send=None):
    """Time a graph node, emit its metrics, and attach an X-Ray subsegment.

    THE TWO SEAMS DEFAULT TO None AND RESOLVE AT CALL TIME. Written first as
    `_emit=emit`, which binds the function OBJECT when this module is imported,
    so replacing `observability.emit` afterwards had no effect on the span's own
    final emission — only on the direct calls in `graph/instrument.py`. A test
    that swapped the module attribute therefore captured some documents and
    missed others, and reported the miss as "a raising node emitted nothing"
    when the span had been emitted correctly the whole time. An instrument
    whose output cannot be captured is one whose claims cannot be checked,
    which is ADR-0013 pointed at the observability layer itself.

    The EMF line is emitted in a `finally`, so a node that raises is still
    measured and still counted. `NodeLatency` is dimensioned by node name only:
    adding the tier or the status here would multiply the metric count by their
    cardinality for a number nobody slices that way, and the tier-sliced
    latency that IS wanted is emitted separately by the retrieval node.
    """
    span = Span(name)
    start = time.time()
    t0 = time.perf_counter()
    try:
        yield span
    except Exception as e:
        span.error = f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        end = time.time()
        span.annotate(node=name, error=span.error is not None)

        metrics = {"NodeLatency": (elapsed_ms, "Milliseconds"), **span.metrics}
        dims = {"node": name, **(dimensions or {})}
        (_emit or emit)(metrics, dims,
              {**(properties or {}), **span.metadata,
               "node": name,
               "elapsed_ms": elapsed_ms,
               **({"error": span.error} if span.error else {})})

        span.span_result = (_send or send_subsegment)(_subsegment(
            name, start, end, span.annotations,
            {**span.metadata, "elapsed_ms": elapsed_ms,
             **({"error": span.error} if span.error else {})}))
        _last_emit["status"], _last_emit["detail"] = span.span_result
