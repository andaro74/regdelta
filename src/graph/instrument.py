"""Graph-side instrumentation: what each node's span carries (SPEC/06).

`shared/observability.py` owns the mechanism — EMF lines and X-Ray subsegments.
This file owns the *policy*: which of the graph's state keys become metrics,
which become searchable properties, and which are never written to a log at all.

## Every state key gets an explicit disposition, and that is the point

The obvious implementation is a short allowlist of interesting fields. This
project has been bitten by exactly that shape four times — `dropped_citations`,
`retrieval_ms` and `stop_reason` were each lost inside `api._shape`'s allowlist,
and `stop_reason` was then lost a second time in the state schema — and the
symptom is always the same: the field reads as "nothing to report" when the
truth is "nobody asked".

So `DISPOSITION` below names **every** key in `RegDeltaState`, including the
ones deliberately not carried, and
`tests/test_node_span_disposition.py` fails if the two ever disagree. A new
field cannot be silently unobserved; it has to be given a disposition, even if
that disposition is `SECRET`.

## Three dispositions

`METRIC`    a CloudWatch metric, with its unit and (optionally) its dimension
`ANNOTATE`  low-cardinality, indexed in X-Ray, filterable; also an EMF property
`DETAIL`    an EMF property and X-Ray metadata; searchable, not a metric
`SECRET`    **never leaves the process**, with a reason recorded beside it

## SECRET is a data-handling rule, not tidiness

`query`, `company_profile`, `applicability` and `answer` are the asker's words,
the asker's business, and the analysis derived from them. `shared/config.py`
already forces three LangSmith variables to false as a *data-egress control*,
on the stated grounds that "the company profile a user submits (revenue tier,
product lines) plus the regulatory analysis derived from it" is "the worst
possible thing to leak by accident". A CloudWatch log group is a different
destination from a SaaS tracer, but it is the same data, it is retained, and it
is readable by anything holding `logs:FilterLogEvents`. Writing it there by
default would reverse that decision by implication.

Counts and lengths of those fields ARE NOT carried, and this paragraph used to
say they were. A tree-wide grep at M06 found no answer-length, query-length or
applicability-size metric anywhere, so the claim was false for every SECRET
key — which means "the answer was empty" is precisely the fact the dashboard
cannot see. That is the allowlist symptom this docstring catalogues above,
committed by the file describing it. eng-code-reviewer, M06.

The argument for carrying them stands and is why this is worth doing: "the
answer was empty" and "eight chunks were retrieved" are facts about the system
rather than about the asker. `retrieved`'s count IS carried, because
`retrieved` is not SECRET. The rest is one dimension-free measure per node, and
it is deliberately not being added in the week the Tier B disposition is
measured — a new metric on the request path is a change to the thing being
measured.
"""
from __future__ import annotations

from shared import config, observability

#: Dispositions. Values are (kind, extra) where extra depends on kind:
#:   METRIC   -> (metric name, unit, dimension key or None, transform)
#:   ANNOTATE -> transform
#:   DETAIL   -> transform
#:   SECRET   -> the reason, which is required rather than optional
METRIC, ANNOTATE, DETAIL, SECRET = "METRIC", "ANNOTATE", "DETAIL", "SECRET"

#: State keys carrying a Converse `usage` block. DERIVED FROM THE SCHEMA by
#: tests/test_node_span_disposition.py rather than trusted here: a third
#: model-calling node whose usage key is missing from this tuple would cost
#: nothing on the dashboard and nobody would see a gap.
USAGE_KEYS = ("supervisor_usage", "verdict_usage")


def _count(value) -> int:
    return len(value or [])


DISPOSITION: dict[str, tuple] = {
    # --- request. The asker's own words and business.
    "query": (SECRET, "the asker's question, verbatim"),
    "company_profile": (SECRET, "products and label claims the asker stated"),

    # --- supervisor
    "intent": (ANNOTATE, str),
    "profile_sufficient": (ANNOTATE, bool),

    # --- retrieval
    "retrieved": (METRIC, ("ChunksRetrieved", "Count", None, _count)),
    #: The only dimension on RetrievalLatency, and the reason this file exists
    #: in a milestone about disposing of Tier B: SPEC/06's bar is p95 of this
    #: interval PER TIER, so the tier has to be a dimension and not a property.
    "retrieval_tier": (ANNOTATE, str),
    "retrieval_fallback": (DETAIL, lambda v: (str(v)[:300] if v else None)),
    "retrieval_ms": (METRIC, ("RetrievalLatency", "Milliseconds",
                              "retrieval_tier", float)),

    # --- timeline / crossref
    "timeline_facts": (METRIC, ("TimelineFacts", "Count", None, _count)),
    "timeline_degraded": (ANNOTATE, bool),
    "crossrefs": (DETAIL, _count),
    "crossref_chunks": (DETAIL, _count),

    # --- synthesis
    "applicability": (SECRET, "the asker's products and claims, restated"),
    "answer": (SECRET, "the regulatory analysis written for this asker"),
    "verdict_rows": (METRIC, ("VerdictRows", "Count", None, _count)),
    #: SPEC/06 names confidence on the span. Unit "None" because it is a ratio,
    #: not a count — CloudWatch will happily average a Count and produce a
    #: number that looks fine and means nothing.
    "confidence": (METRIC, ("Confidence", "None", None, float)),
    "citations": (METRIC, ("Citations", "Count", None, _count)),
    "dropped_citations": (METRIC, ("DroppedCitations", "Count", None, _count)),
    "stop_reason": (ANNOTATE, lambda v: str(v) if v is not None else None),
    "truncated": (ANNOTATE, lambda v: bool(v) if v is not None else None),
    "supervisor_usage": (DETAIL, dict),
    "verdict_usage": (DETAIL, dict),

    # --- gate
    "status": (ANNOTATE, str),
    "review_reason": (SECRET,
                      "generated prose that can restate the question; the API "
                      "returns it to the one caller entitled to it, which is "
                      "not the same as retaining it in a log group"),
    "hitl_passes": (DETAIL, int),
}


def _tokens_and_cost(usage: dict) -> tuple[dict, dict]:
    """Token metrics and their dollar cost, dimensioned by model.

    SPEC/06's dashboard wants "Bedrock cost/query". Emitting the dollars here
    rather than computing them in a dashboard expression means the arithmetic
    lives beside the rates it uses (`config.BEDROCK_RATES_USD_PER_MTOK`, which
    records how they were measured), and a dashboard cannot drift from it.

    AN UNPRICED MODEL IS NOT FREE. If the model has no rate — a swap that left
    the table behind — this emits the token counts, omits the cost, and records
    `rate_missing`. Costing it at zero is the failure that matters: every total
    downstream stays plausible and is wrong in the direction that flatters us.
    It does not raise, because this runs on the request path and an
    instrument must not be able to fail a request.
    """
    model = usage.get("model")
    counts = {
        "BedrockInputTokens": usage.get("input"),
        "BedrockOutputTokens": usage.get("output"),
        "BedrockCacheReadTokens": usage.get("cache_read"),
        "BedrockCacheWriteTokens": usage.get("cache_write"),
    }
    metrics = {name: (float(v), "Count")
               for name, v in counts.items() if v is not None}
    if not metrics or not model:
        return metrics, {}

    rates = config.BEDROCK_RATES_USD_PER_MTOK.get(model)
    if rates is None:
        return metrics, {"rate_missing": model}

    # Cache READS are billed below the input rate and cache WRITES above it,
    # and `usage.inputTokens` on Converse already excludes both. Priced at the
    # documented multipliers rather than folded into `input`, which is what a
    # naive sum would do and would under-report a cached run.
    cost = (
        (usage.get("input") or 0) * rates["input"]
        + (usage.get("output") or 0) * rates["output"]
        + (usage.get("cache_read") or 0) * rates["input"] * 0.10
        + (usage.get("cache_write") or 0) * rates["input"] * 1.25
    ) / 1_000_000
    metrics["BedrockCostUsd"] = (round(cost, 8), "None")
    return metrics, {"cost_model": model}


def observed(name: str, fn, on_span=None):
    """Wrap a graph node so that running it emits its span.

    The wrapper reads the node's RETURN VALUE rather than the merged state,
    which matters twice over. It sees keys before LangGraph can drop an
    undeclared one — so a span cannot silently lose a field the way
    `stop_reason` did — and it attributes each fact to the node that produced
    it rather than to whichever node happened to run last.

    `on_span` is an OPTIONAL sink for `Span.span_result` — the
    `(status, detail)` pair `shared.observability.send_subsegment` returns,
    one of `sent | unsampled | off | failed`. It exists for one caller:
    SPEC/06's amended disposition clause requires the report to record the
    span emission status, and an artifact that claims a span it did not emit
    is ADR-0013's defect exactly.

    IT IS NOT `observability.emission_report()`, and the difference is the
    load driver. That function reads a MODULE-LEVEL dict whose stated
    precondition is one request at a time per process (see its own comment);
    the driver runs many retrievals concurrently in one process and is the
    first thing in this repo to break it. A per-call sink attributes each
    status to the call that produced it. Graph nodes pass nothing and are
    unaffected.

    The graph is registered with no sink, so the request path pays one `if
    ... is not None` per node and nothing else.
    """
    def run(state, *args, **kwargs):
        # `return` MOVED OUT of the `with`, and the sink runs in a `finally`.
        #
        # Out of the `with`, because `span.span_result` is assigned in
        # `node_span`'s own `finally`, i.e. as the context manager exits: a
        # return from inside the block reads the initial `("off", None)` every
        # time — a sink reporting "off" while the datagram went out. The
        # emitted span is identical either way; __exit__ runs before the value
        # is returned in both forms.
        #
        # In a `finally`, because `node_span` emits for a node that RAISES
        # (that is its own docstring's argument — a failed node is the one you
        # most want a span for). A sink on the success path only would report
        # every errored call as having emitted nothing, which is the same
        # false claim in the other direction.
        span = None
        try:
            with observability.node_span(name) as span:
                result = fn(state, *args, **kwargs)
                _carry(span, result if isinstance(result, dict) else {})
        finally:
            # `span is not None` guards the window before `node_span` yields.
            # Nothing there can raise today; a NameError in a `finally` would
            # replace the node's real exception with a lie about this shim.
            if on_span is not None and span is not None:
                on_span(span.span_result)
        return result

    # THE SIGNATURE IS PART OF THE CONTRACT, not decoration. LangGraph inspects
    # each node's signature and passes `config=` only to nodes that accept it —
    # `hitl_gate` does, because it reads `resumable` out of `configurable`. The
    # first version of this wrapper was `def run(state)`, which type-errored on
    # every resume path in the suite. `*args, **kwargs` forwards whatever
    # LangGraph decides to send, and `__wrapped__` below makes
    # `inspect.signature` report the ORIGINAL signature so that decision is
    # made about the real node rather than about this shim.
    run.__name__ = getattr(fn, "__name__", name)
    run.__doc__ = fn.__doc__
    #: The unwrapped node, so `loadtest/retrieval_load.py` and the tests can
    #: reach the real function without going through the span, and so
    #: `tests/test_graph_wiring.py` can still identify what was registered.
    run.__wrapped__ = fn
    return run


def _carry(span, result: dict) -> None:
    dimensions: dict[str, str] = {}
    pending: list[tuple] = []

    for key, value in result.items():
        kind, extra = DISPOSITION.get(key, (None, None))
        if kind is None or kind is SECRET:
            # An unknown key is NOT quietly ignored: it is named, without its
            # value, so the log says "something is unobserved" rather than
            # nothing. tests/test_node_span_disposition.py is what stops this
            # branch from ever being reached in a green build.
            if kind is None:
                span.detail(**{f"undisposed__{key}": True})
            continue
        if kind is ANNOTATE:
            carried = extra(value) if value is not None else None
            if carried is not None:
                span.annotate(**{key: carried})
                dimensions[key] = str(carried)
        elif kind is DETAIL:
            carried = extra(value) if value is not None else None
            if carried is not None:
                span.detail(**{key: carried})
        elif kind is METRIC:
            metric_name, unit, dim_key, transform = extra
            if value is None:
                continue
            pending.append((metric_name, float(transform(value)), unit, dim_key))

    # Metrics are recorded AFTER every annotation, because a metric's dimension
    # is another key's annotated value and dict order in the node's return is
    # not something this file should depend on.
    for metric_name, value, unit, dim_key in pending:
        if dim_key is None:
            span.measure(metric_name, value, unit)
        elif dim_key in dimensions:
            # A dimensioned metric goes out as its own EMF document: EMF ties
            # one dimension set to one document, so folding a tier-sliced
            # metric into the node-sliced one would silently re-dimension
            # NodeLatency by tier and multiply the metric count.
            observability.emit({metric_name: (value, unit)},
                               {dim_key: dimensions[dim_key]},
                               {"node": span.name})
        else:
            # The dimension's own key was absent from this node's return, so
            # the slice cannot be stated. Recorded as undimensioned rather than
            # dropped, and named so the gap is visible.
            span.measure(metric_name, value, unit)
            span.detail(**{f"{metric_name}__undimensioned": dim_key})

    for key in USAGE_KEYS:
        usage = result.get(key) or {}
        if not usage.get("model"):
            continue
        metrics, props = _tokens_and_cost(usage)
        if metrics:
            # Its own document, dimensioned by MODEL rather than by node: the
            # dashboard's "Bedrock cost/query" sums across nodes, and a
            # node-dimensioned cost cannot be summed without double-counting
            # the dimension set.
            observability.emit(metrics, {"model": usage["model"]},
                               {"node": span.name, "usage_key": key, **props})
