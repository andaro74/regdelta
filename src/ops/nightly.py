"""Nightly health + graph-logic check (SPEC/06 Observability).

SPEC/06 asks for a "Nightly eval Lambda: full set if hot tier up, else reduced
graph-logic set; pass-rate metric + regression alarm."

## Why this runs no golden questions, and what it runs instead

**The full set nightly is not affordable and would not fit.** Twenty questions
is $0.95 and 117,636 Opus tokens — **4.5% of a daily cap that reports
`Adjustable: false`** — every night, before anyone does any work. The human
seat's M06 instruction was to keep the nightly job free; a $29/month unattended
job that also consumes a non-renewable daily allowance is the opposite of the
cost control this milestone exists to install.

**The "reduced graph-logic set" is taken literally**: the parts of the graph
whose answers are DETERMINISTIC and therefore checkable with no model call.
CLAUDE.md's rule — "Timeline questions are answered from the DynamoDB amendment
graph, not vector similarity" — is exactly such a part, and it is the part with
the most infrastructure under it. `graph.amendment_graph.load()` reads the
registry table, walks supersession edges and resolves stay intervals; if the
poller corrupts an item, if a GSI goes missing, or if a date stops resolving,
this notices tonight rather than at the next milestone.

## The pass-rate metric comes from the runs that actually measure it

A pass rate is a property of a golden run, and golden runs are deliberate acts
that cost money. `evals/run_evals.py --record` publishes `EvalPassRate` when it
records a scorecard — at the moment a real measurement exists. This function
publishes `EvalStalenessHours` instead: how long since that last happened.

Those two carry different alarms and the split is the honest one. A regression
alarm on `EvalPassRate` fires when a run measured a regression. A staleness
alarm fires when nobody has measured anything for too long — which is the
failure a nightly job that never runs the set would otherwise hide.

## Everything here is free

DynamoDB reads on-demand, one SSM read, and `PutMetricData`. No Bedrock, no
S3 Vectors query, no AOSS query. A nightly job that costs money is a nightly
job someone eventually turns off.
"""
from __future__ import annotations

import json
import os
import time

import boto3

from shared import config, observability

#: How stale a recorded pass rate may get before the alarm should care. Seven
#: days is one milestone's working rhythm in this project; a fortnight of
#: silence means the golden set has stopped gating anything.
STALENESS_ALARM_HOURS = float(os.environ.get("EVAL_STALENESS_ALARM_HOURS", "168"))


def _cloudwatch():
    return boto3.client("cloudwatch", region_name=config.REGION)


def _tier() -> dict:
    """Which retrieval tier is live, and therefore whether OCU is billing.

    `router.active_tier()` reads the SSM parameter through the same memo the
    request path uses. A hot tier still up at 01:00 is not an error — the
    janitor runs at the same hour and may not have finished — but it is the
    single most expensive fact this function can report, so it is reported as a
    metric rather than only as prose.
    """
    from retrieval import router

    router.reset_cache()          # a Lambda container can outlive a make down
    try:
        tier = router.active_tier()
        return {"tier": tier, "hot_tier_up": tier == "aoss", "error": None}
    except Exception as e:                        # noqa: BLE001
        # Reported as unknown rather than as s3vectors. Defaulting to the
        # always-on tier on a failed lookup is what made a mangled SSM path
        # invisible for a whole milestone (see the Makefile's retrieval-evals
        # comment); the same substitution here would report "no OCU billing"
        # about a lookup that never happened.
        return {"tier": "unknown", "hot_tier_up": None,
                "error": f"{type(e).__name__}: {e}"[:200]}


def _corpus() -> dict:
    """Document count and fingerprint, from `shared.corpus`.

    THE SHARED DEFINITION, NOT A SECOND ONE. Written first as its own scan and
    its own hash, which produced `8e9b3176dcb2` where every recorded scorecard
    says `35a293e17117` for the same 52 documents — one separator apart. A
    nightly job emitting an incomparable fingerprint would have read as "the
    corpus changed" every night forever.
    """
    from shared.corpus import fingerprint

    return fingerprint()


def _graph_logic() -> dict:
    """The deterministic half of the graph, against the live table.

    For each demo document, `amendment_graph.load()` must return a timeline
    that resolves at least one DATED fact. This is the rule CLAUDE.md states —
    dates come from the graph, never from a retrieved paragraph — exercised
    end to end with no model in the loop.

    A document that raises and a document that resolves nothing are recorded
    SEPARATELY. They are different failures: the first is the graph broken, the
    second is the graph working over data that lost its dates, and an alarm
    that cannot tell them apart sends someone to read the wrong code.
    """
    from graph import amendment_graph as ag

    checked, errors, undated = [], [], []
    for doc in config.BACKFILL_FR_DOCS:
        try:
            timeline = ag.load(doc)
        except Exception as e:                    # noqa: BLE001
            errors.append({"doc": doc, "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        # READ OFF THE REAL DATACLASS. The first version of this line asked for
        # `timeline.dates` and filtered on `.stated` — neither exists.
        # `DocTimeline` carries `effective_dates` and `compliance_dates`, both
        # tuples of dicts, and `getattr(..., "dates", [])` would have returned
        # the empty default forever: every document would have been reported
        # `undated`, the alarm would have fired nightly, and the cause would
        # have looked like a corrupt registry rather than a typo in the
        # instrument. ADR-0013 — an instrument reads the field that describes
        # its own claim, and this one has now been checked against the class.
        dated = list(timeline.effective_dates) + list(timeline.compliance_dates)
        checked.append(doc)
        if not dated:
            undated.append(doc)
    return {"checked": checked, "errors": errors, "undated": undated,
            "ok": not errors and not undated}


def _eval_staleness() -> dict:
    """Hours since a golden run last recorded a pass rate.

    Reads the metric `evals/run_evals.py --record` publishes. `None` when the
    metric has never been published, which is DISTINCT from zero and from a
    large number: "no run has ever been recorded" is a different state from
    "the last one was long ago", and the alarm treats missing data as breaching
    for exactly that reason.
    """
    try:
        end = time.time()
        points = _cloudwatch().get_metric_statistics(
            Namespace=observability.NAMESPACE,
            MetricName="EvalPassRate",
            StartTime=_dt(end - 90 * 86400), EndTime=_dt(end),
            Period=86400, Statistics=["Maximum"])["Datapoints"]
        if not points:
            return {"hours": None, "reason": "no EvalPassRate ever published"}
        newest = max(p["Timestamp"] for p in points)
        return {"hours": round((end - newest.timestamp()) / 3600, 1),
                "last_at": newest.isoformat()}
    except Exception as e:                        # noqa: BLE001
        return {"hours": None, "reason": f"{type(e).__name__}: {e}"[:200]}


def _dt(epoch: float):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def handler(event, context):
    """One structured line, one set of metrics, one return value.

    The same shape as the janitor: EventBridge discards the return value, so
    the line is what a reader and an alarm actually get. Metrics go out through
    EMF like everything else, so this function needs no `cloudwatch:PutMetricData`
    grant for them — only `_eval_staleness` reads CloudWatch, and it reads.
    """
    tier = _tier()
    corpus = _corpus()
    logic = _graph_logic()
    staleness = _eval_staleness()

    failed = bool(logic["errors"] or logic["undated"]
                  or not corpus.get("available") or tier["error"])

    metrics = {
        "NightlyCheckFailed": (1.0 if failed else 0.0, "Count"),
        "GraphLogicErrors": (float(len(logic["errors"])), "Count"),
        "GraphLogicUndated": (float(len(logic["undated"])), "Count"),
        "GraphLogicChecked": (float(len(logic["checked"])), "Count"),
    }
    if tier["hot_tier_up"] is not None:
        # 1 means OCU is billing at 01:00 UTC, which is the fact this whole
        # lifecycle exists to prevent going unnoticed.
        metrics["HotTierUp"] = (1.0 if tier["hot_tier_up"] else 0.0, "Count")
    if corpus.get("available"):
        metrics["CorpusDocuments"] = (float(corpus["documents"]), "Count")
    if staleness.get("hours") is not None:
        metrics["EvalStalenessHours"] = (float(staleness["hours"]), "None")

    observability.emit(metrics, {"check": "nightly"},
                       {"tier": tier["tier"],
                        "corpus_sha": corpus.get("documents_sha"),
                        "graph_logic": logic,
                        "eval_staleness": staleness})

    result = {
        "status": "failed" if failed else "ok",
        "tier": tier["tier"],
        "corpus": corpus,
        "graph_logic": logic,
        "eval_staleness": staleness,
        "staleness_alarm_hours": STALENESS_ALARM_HOURS,
        # NOT a claim that the golden set passes. This function ran no golden
        # question and says so, because a nightly "ok" that reads as "the
        # answers are still right" is exactly the substitution ADR-0013 names.
        "checked": "graph logic and infrastructure only; no golden questions, "
                   "no model call, no retrieval query",
    }
    print(json.dumps({"nightly": result}, sort_keys=True, default=str))
    return result
