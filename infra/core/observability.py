"""Dashboard, alarms and the nightly check (SPEC/06 Observability).

Kept out of `core_stack.py`, which is already 900 lines of decisions that need
their reasons beside them. Everything here is a pure addition to the core
stack: nothing in this file is referenced by `regdelta-search`, so
`cdk destroy regdelta-search` stays safe.

## What this costs, because a cost-control milestone must price its own tools

- **Dashboards**: the first three in an account are free; this is one.
- **Alarms**: $0.10/month each, five of them — $0.50/month.
- **Metric filters**: free. The metrics they produce are custom metrics at
  $0.30/month each after the first ten.
- **Custom metrics via EMF**: the log lines are already being written, so the
  marginal cost is the metric storage, not the ingestion.
- **X-Ray**: first 100,000 traces recorded per month are free; this project
  records dozens per milestone.
- **The nightly check**: one Lambda invocation, a DynamoDB scan, one SSM read
  and one CloudWatch read. Rounds to zero and is *designed* to — `src/ops/nightly.py`
  states why it runs no golden question.

Order of magnitude: **under a dollar a month**, against a stack whose idle
target is $2. That is stated here rather than assumed, because the failure this
milestone exists to prevent is unattended spend, and observability is
unattended by definition.

## The janitor alarm distinguishes "could not act" from "acted"

`delete-requested` carries `billing_stopped: false` legitimately — the janitor
asked CloudFormation to delete and cannot watch it finish (ADR-0013, and the
handler's own docstring). Alarming on that would fire every time the hot tier
was simply left up overnight, which is a fact worth SEEING and not worth
paging about.

What must alarm is the janitor being **unable to do its job**:
`unhandled-state`, `unhandled-error`, and a `retry_of_failed` — the last
meaning a previous night's delete did not work and a collection has now been
billing for at least a day. That is the failure mode the janitor exists to
prevent, wearing the janitor's own success message, which is exactly what M05
found and fixed in the handler.
"""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_sns as sns,
)
from constructs import Construct

NAMESPACE = "RegDelta"

#: What one OCU-hour costs, measured rather than quoted: M05 recorded 34.7
#: minutes of a two-OCU collection at $0.14, which is $0.242/hr for the pair.
#: Used only to render a dollar figure on the dashboard.
OCU_USD_PER_HOUR = 0.242


def _metric(name: str, *, statistic: str = "Sum",
            dimensions: dict | None = None, period_minutes: int = 5,
            label: str | None = None) -> cw.Metric:
    return cw.Metric(
        namespace=NAMESPACE, metric_name=name, statistic=statistic,
        dimensions_map=dimensions or {}, period=Duration.minutes(period_minutes),
        label=label)


def enable_xray(fn: _lambda.Function) -> None:
    """Turn on ACTIVE tracing and grant exactly the two daemon write actions.

    SPEC/06's "span per graph node". `shared/observability.py` writes the
    subsegments to the daemon socket; the daemon only exists when tracing is
    ACTIVE, and without this the module's own `emission_report()` — and the
    load driver's per-call span status — report "off" forever, honestly and
    uselessly.

    NOT `_lambda.Tracing.ACTIVE`, and the difference is the reason this is a
    function rather than a property. CDK's own switch attaches
    `AWSXRayDaemonWriteAccess`, which grants FOUR actions
    (`GetSamplingRules` and `GetSamplingTargets` besides these two). The
    wildcard exemption `tests/test_query_fn_iam.py` pins is two actions wide
    and has to be argued for to grow; picking up two more as a side effect of
    a convenience flag is exactly the one-action-at-a-time widening that test
    exists to stop.

    X-Ray's write actions do not accept a resource ARN — unlike the `aoss:*`
    control-plane grant M05 had to correct, this one really is resource-less,
    and the AWS-managed policy is written the same way. Stated because "these
    actions do not take a resource" was an untrue claim once already in this
    repo, and recorded as documented-not-measured in that test.

    A FUNCTION SO THE SECOND CALLER CANNOT DRIFT. `LoadDriverFn` needs the
    identical pair: SPEC/06's disposition is defined on the span, so a driver
    whose spans never leave measures the right interval and can prove nothing
    about it.
    """
    fn.node.default_child.add_property_override("TracingConfig.Mode", "Active")
    fn.add_to_role_policy(iam.PolicyStatement(
        actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
        resources=["*"]))


def add_observability(scope: Construct, *, query_fn: _lambda.Function,
                      janitor_fn: _lambda.Function,
                      nightly_fn: _lambda.Function,
                      alarm_topic: sns.Topic | None = None) -> cw.Dashboard:
    """Wire the dashboard, the alarms and the log-metric filters.

    `alarm_topic` is optional and there is no default subscription, deliberately:
    SPEC/04's SES identity for HITL notification is still a TODO and inventing
    an email destination here would be a delivery promise nobody has tested. An
    alarm with no action still changes state, still shows red on the dashboard,
    and still answers "was it firing at 03:00 last Tuesday" — which is what the
    evidence pack needs. The topic exists so subscribing is one line later.
    """
    # ------------------------------------------------------------------ X-Ray
    enable_xray(query_fn)

    # ------------------------------------------------- janitor metric filters
    could_not_act = logs.MetricFilter(
        scope, "JanitorCouldNotActFilter",
        log_group=janitor_fn.log_group,
        # Matched on the STRUCTURED FIELDS of the single line M05 added for
        # exactly this purpose, not on a substring of the message. A substring
        # filter over prose is a filter that breaks when someone improves the
        # wording.
        filter_pattern=logs.FilterPattern.any(
            logs.FilterPattern.string_value("$.janitor.status", "=", "unhandled-state"),
            logs.FilterPattern.string_value("$.janitor.status", "=", "unhandled-error"),
            logs.FilterPattern.boolean_value("$.janitor.retry_of_failed", True),
        ),
        metric_namespace=NAMESPACE, metric_name="JanitorCouldNotAct",
        metric_value="1", default_value=0)

    logs.MetricFilter(
        scope, "JanitorDeleteRequestedFilter",
        log_group=janitor_fn.log_group,
        filter_pattern=logs.FilterPattern.string_value(
            "$.janitor.status", "=", "delete-requested"),
        metric_namespace=NAMESPACE, metric_name="JanitorDeleteRequested",
        metric_value="1", default_value=0)

    # ------------------------------------------------------------- the nightly
    events.Rule(
        scope, "NightlyCheck",
        # 02:00 UTC — an hour AFTER the janitor, so `HotTierUp` reports the
        # state the janitor left rather than the state it was about to change.
        # At 01:00 the two would race and the metric would be noise.
        schedule=events.Schedule.cron(minute="0", hour="2"),
        targets=[targets.LambdaFunction(nightly_fn)],
    )

    # ------------------------------------------------------------------ alarms
    alarms = [
        cw.Alarm(
            scope, "NightlyCheckFailedAlarm",
            metric=_metric("NightlyCheckFailed", dimensions={"check": "nightly"},
                           period_minutes=1440),
            threshold=0, comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            # MISSING DATA IS BREACHING, and this is the load-bearing choice.
            # The failure being watched for includes "the nightly check did not
            # run at all", and NOT_BREACHING would report that as healthy —
            # a monitor that goes quiet when it dies. Same argument as the eval
            # gate's "if the exit code is empty, fail closed".
            treat_missing_data=cw.TreatMissingData.BREACHING,
            alarm_description=(
                "The nightly graph-logic check failed, or did not run. It "
                "exercises the amendment graph against the live registry with "
                "no model call; a failure means dates stopped resolving or the "
                "table is unreadable. It does NOT mean the golden set fails — "
                "no golden question is run by it."),
        ),
        cw.Alarm(
            scope, "JanitorCouldNotActAlarm",
            metric=could_not_act.metric(statistic="Sum",
                                        period=Duration.hours(24)),
            threshold=0, comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            # NOT breaching here, and the asymmetry with the alarm above is
            # deliberate. This metric is emitted by a LOG FILTER, which
            # produces no datapoint on a night when the janitor had nothing to
            # report — the healthy case. Treating that as breaching would fire
            # every night the system worked.
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "The janitor could not delete regdelta-search: an unhandled "
                "state, an unhandled error, or a retry of a delete that "
                "previously failed. A collection is billing ~$0.24/hr and the "
                "unattended path cannot stop it. This does NOT fire merely "
                "because the hot tier was left up — that is "
                "JanitorDeleteRequested, on the dashboard."),
        ),
        cw.Alarm(
            scope, "HotTierLeftUpAlarm",
            metric=_metric("HotTierUp", dimensions={"check": "nightly"},
                           statistic="Maximum", period_minutes=1440),
            threshold=0, comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "The AOSS hot tier was still up at 02:00 UTC, an hour after "
                "the janitor ran. ~$0.24/hr, ~$175/month if forgotten."),
        ),
        cw.Alarm(
            scope, "EvalRegressionAlarm",
            metric=_metric("EvalPassRate", statistic="Minimum",
                           period_minutes=1440),
            # SPEC/06's "regression alarm". The threshold is the M05 baseline
            # of 18/20 = 0.90 MINUS the one known false fail (q03), which is
            # 17/20 = 0.85: a run scoring below that has lost something beyond
            # the failure the seat has already ruled on. Written as a fraction
            # so the golden set can grow without moving the bar.
            threshold=0.85,
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=1,
            # A pass rate is published only when a run records one, so most
            # days have no datapoint and that is normal. Staleness is the
            # separate alarm below; conflating them would make this one fire
            # on every day nobody ran the set.
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "A recorded golden run scored below 0.85 — the M05 baseline of "
                "18/20 less the one ruled false fail (q03). Ground truth is "
                "@regdelta-sme's; run sme-eval-triage and STOP before touching "
                "evals/golden_questions.json."),
        ),
        cw.Alarm(
            scope, "EvalStalenessAlarm",
            metric=_metric("EvalStalenessHours", dimensions={"check": "nightly"},
                           statistic="Maximum", period_minutes=1440),
            threshold=168,      # one week
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "No golden run has recorded a pass rate for over a week, so "
                "the regression alarm above has had nothing to watch. A gate "
                "nobody runs is not a gate."),
        ),
    ]

    if alarm_topic is not None:
        for alarm in alarms:
            alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

    # --------------------------------------------------------------- dashboard
    dashboard = cw.Dashboard(
        scope, "RegDeltaDashboard", dashboard_name="regdelta",
        # DEFAULT_INTERVAL rather than a fixed window: a screenshot-ready
        # dashboard has to show something on the day it is opened, and this
        # project's traffic arrives in bursts around a milestone window.
        start="-P7D",
    )

    latency = _metric("QueryLatency", statistic="p50", label="p50")
    latency_p95 = _metric("QueryLatency", statistic="p95", label="p95")

    dashboard.add_widgets(
        cw.TextWidget(markdown=(
            "# RegDelta\n"
            "`/query` latency, cache, spend and tier health. **Retrieval "
            "latency by tier is the SPEC/06 Tier B disposition number** — "
            "reported here, decided by `loadtest/reports/"
            "tier-disposition-<sha>.json`, never by this widget.\n\n"
            "*A blank panel means no traffic in the window, not a healthy "
            "zero.*"), width=24, height=3),

        cw.GraphWidget(
            title="/query latency (p50 / p95, ms)",
            left=[latency, latency_p95], width=12, height=6),

        cw.GraphWidget(
            title="Retrieval latency by tier (p95, ms)",
            left=[
                _metric("RetrievalLatency", statistic="p95",
                        dimensions={"retrieval_tier": "s3vectors"},
                        label="Tier A — S3 Vectors"),
                _metric("RetrievalLatency", statistic="p95",
                        dimensions={"retrieval_tier": "aoss"},
                        label="Tier B — AOSS"),
            ], width=12, height=6),

        cw.GraphWidget(
            title="Cache hit rate",
            left=[cw.MathExpression(
                expression="100 * hits / MAX([hits + misses, 1])",
                using_metrics={
                    "hits": _metric("Queries", dimensions={"cache": "hit"}),
                    "misses": _metric("Queries", dimensions={"cache": "miss"}),
                },
                label="hit %", period=Duration.minutes(5))],
            left_y_axis=cw.YAxisProps(min=0, max=100), width=8, height=6),

        cw.GraphWidget(
            title="Bedrock cost per query (USD)",
            left=[cw.MathExpression(
                # SUM(cost) / SUM(queries). Not AVG of a per-request cost:
                # a cache hit costs nothing and is a query, so averaging the
                # cost metric alone would divide by the wrong denominator and
                # report the cost of a MISS as the cost of a query.
                expression="FILL(spend, 0) / MAX([queries, 1])",
                using_metrics={
                    "spend": _metric("BedrockCostUsd"),
                    "queries": _metric("Queries"),
                },
                label="$/query", period=Duration.minutes(5))],
            width=8, height=6),

        cw.GraphWidget(
            title="HITL rate (% of answered queries sent to review)",
            left=[cw.MathExpression(
                expression="100 * (FILL(pend, 0) + FILL(need, 0)) / MAX([all, 1])",
                using_metrics={
                    "pend": _metric("Queries", dimensions={"status": "pending_review"}),
                    "need": _metric("Queries", dimensions={"status": "needs_input"}),
                    "all": _metric("Queries"),
                },
                label="HITL %", period=Duration.minutes(5))],
            left_y_axis=cw.YAxisProps(min=0, max=100), width=8, height=6),

        cw.GraphWidget(
            title=f"Search-session cost (OCU-hours x ${OCU_USD_PER_HOUR}/hr)",
            left=[cw.MathExpression(
                # AWS/AOSS reports OCU as a gauge; averaged over the period and
                # scaled to hours gives OCU-hours for that period.
                expression=f"(FILL(search, 0) + FILL(index, 0)) * "
                           f"{OCU_USD_PER_HOUR} * PERIOD(search) / 3600",
                using_metrics={
                    "search": cw.Metric(namespace="AWS/AOSS",
                                        metric_name="SearchOCU",
                                        statistic="Average",
                                        period=Duration.minutes(5)),
                    "index": cw.Metric(namespace="AWS/AOSS",
                                       metric_name="IndexingOCU",
                                       statistic="Average",
                                       period=Duration.minutes(5)),
                },
                label="USD in period", period=Duration.minutes(5))],
            width=8, height=6),

        cw.GraphWidget(
            title="Lambda concurrency and throttles (query path)",
            left=[query_fn.metric_invocations(period=Duration.minutes(5)),
                  query_fn.metric_errors(period=Duration.minutes(5)),
                  query_fn.metric_throttles(period=Duration.minutes(5))],
            width=8, height=6),

        cw.GraphWidget(
            title="Lifecycle: hot tier up / janitor",
            left=[
                _metric("HotTierUp", dimensions={"check": "nightly"},
                        statistic="Maximum", period_minutes=1440,
                        label="hot tier up at 02:00"),
                could_not_act.metric(statistic="Sum", period=Duration.hours(24),
                                     label="janitor could not act"),
                _metric("JanitorDeleteRequested", period_minutes=1440,
                        label="janitor requested a delete"),
            ], width=8, height=6),

        cw.SingleValueWidget(
            title="Golden set — last recorded run",
            metrics=[_metric("EvalPassRate", statistic="Maximum",
                             period_minutes=10080, label="pass rate"),
                     _metric("EvalStalenessHours", dimensions={"check": "nightly"},
                             statistic="Maximum", period_minutes=1440,
                             label="hours since")],
            width=8, height=6),

        cw.AlarmStatusWidget(alarms=alarms, title="Alarms", width=24, height=3),
    )

    cdk.CfnOutput(scope, "DashboardUrl",
                  value=(f"https://{cdk.Stack.of(scope).region}.console.aws.amazon.com"
                         f"/cloudwatch/home?region={cdk.Stack.of(scope).region}"
                         f"#dashboards:name=regdelta"),
                  description="SPEC/06 dashboard")
    return dashboard
