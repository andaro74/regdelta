"""What SPEC/06's observability actually deploys, asserted against the template.

Three classes of claim are checked here, and only the first is obvious.

**It exists.** The dashboard, five alarms, two metric filters and the nightly
rule are in the synthesized template rather than in a docstring.

**It fails loudly.** `NightlyCheckFailed` treats missing data as BREACHING,
because "the nightly check did not run" is one of the failures it exists to
catch and `notBreaching` would report a dead monitor as a healthy system. The
other four are `notBreaching` for a stated and different reason, and the
asymmetry is asserted so it cannot be flattened by someone tidying.

**It is not over-granted.** The nightly Lambda runs unattended on a schedule.
It may READ CloudWatch — it computes staleness from `EvalPassRate` — and it
must not be able to publish metrics or write to the registry. A role that can
publish metrics can forge the numbers the dashboard is trusted for, which is a
different and quieter failure than deleting something.
"""
import contextlib
import sys
import tempfile
from pathlib import Path

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))
sys.path.insert(0, str(ROOT / "src"))

ACCOUNT, REGION = "111122223333", "us-west-2"


@contextlib.contextmanager
def stub_layer():
    from core import core_stack

    original = core_stack.LAYER_SRC
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "python").mkdir()
        core_stack.LAYER_SRC = Path(tmp)
        try:
            yield
        finally:
            core_stack.LAYER_SRC = original


@pytest.fixture(scope="module")
def template():
    import aws_cdk as cdk
    from core.core_stack import RegDeltaCoreStack

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core",
                          env=cdk.Environment(account=ACCOUNT, region=REGION))
    return app.synth().get_stack_by_name("regdelta-core").template


def _of_type(template, type_name):
    return {k: v for k, v in template["Resources"].items()
            if v["Type"] == type_name}


def _fn_by_handler(template, handler):
    return next(v for v in template["Resources"].values()
                if v["Type"] == "AWS::Lambda::Function"
                and v["Properties"].get("Handler") == handler)


def _role_of(fn):
    return fn["Properties"]["Role"]["Fn::GetAtt"][0]


def _statements_for(template, role_id):
    out = []
    for res in template["Resources"].values():
        if res["Type"] != "AWS::IAM::Policy":
            continue
        if role_id in [r.get("Ref") for r in res["Properties"].get("Roles", [])]:
            out.extend(res["Properties"]["PolicyDocument"]["Statement"])
    return out


def _actions(stmt):
    a = stmt.get("Action")
    return a if isinstance(a, list) else [a]


# ------------------------------------------------------------------ presence
def test_the_dashboard_exists_and_is_named_so_a_link_can_be_written(template):
    """`DashboardUrl` is a CfnOutput pointing at a fixed name.

    A generated name would make the output correct and the milestone
    screenshot's URL unreproducible.
    """
    dashboards = _of_type(template, "AWS::CloudWatch::Dashboard")
    assert len(dashboards) == 1
    assert next(iter(dashboards.values()))["Properties"]["DashboardName"] == "regdelta"
    assert "DashboardUrl" in template["Outputs"]


def test_the_query_function_has_active_tracing(template):
    """Without it there is no X-Ray daemon, so every subsegment goes nowhere.

    `shared/observability.py` reports that honestly as `off` — which is worse
    than useless if nobody notices the whole span half of SPEC/06 is inert.
    """
    fn = _fn_by_handler(template, "api.api.handler")
    assert fn["Properties"].get("TracingConfig", {}).get("Mode") == "Active"


def test_the_nightly_check_is_scheduled_after_the_janitor(template):
    """01:00 janitor, 02:00 check. At the same hour they race and `HotTierUp`
    reports the state the janitor was in the middle of changing."""
    rules = _of_type(template, "AWS::Events::Rule")
    exprs = {r["Properties"]["ScheduleExpression"] for r in rules.values()}
    assert "cron(0 1 * * ? *)" in exprs, "the janitor rule moved"
    assert "cron(0 2 * * ? *)" in exprs, "the nightly check is not at 02:00"


# -------------------------------------------------------------------- alarms
def _alarms(template):
    return {k: v["Properties"]
            for k, v in _of_type(template, "AWS::CloudWatch::Alarm").items()}


def test_all_five_spec06_alarms_are_present(template):
    got = {p["MetricName"] for p in _alarms(template).values() if "MetricName" in p}
    assert {"NightlyCheckFailed", "JanitorCouldNotAct", "HotTierUp",
            "EvalPassRate", "EvalStalenessHours"} <= got


def test_the_nightly_alarm_treats_missing_data_as_breaching(template):
    """A monitor that goes quiet when it dies is not a monitor.

    The other four are deliberately notBreaching and the next test pins that,
    so this asymmetry cannot be "tidied" into consistency.
    """
    alarm = next(p for p in _alarms(template).values()
                 if p.get("MetricName") == "NightlyCheckFailed")
    assert alarm["TreatMissingData"] == "breaching"


@pytest.mark.parametrize("metric", ["JanitorCouldNotAct", "HotTierUp",
                                    "EvalPassRate"])
def test_the_sparse_alarms_do_not_fire_on_a_quiet_day(template, metric):
    """These three are fed by events that legitimately do not happen daily.

    `JanitorCouldNotAct` comes from a log filter that emits nothing on a night
    the janitor had nothing to report; `EvalPassRate` is published only when a
    golden run records one. Breaching-on-missing would fire every healthy day.

    `EvalStalenessHours` WAS IN THIS LIST and has been taken out — see the test
    below. It is not sparse: the nightly emits it on every run.
    """
    alarm = next(p for p in _alarms(template).values()
                 if p.get("MetricName") == metric)
    assert alarm["TreatMissingData"] == "notBreaching"


def test_the_staleness_alarm_breaches_on_missing_data(template):
    """THE HOLE, and it was the whole watch.

    `EvalStalenessHours` used to be treated as sparse, alongside metrics that
    genuinely do not appear every day. It is not sparse — the nightly emits it
    on every run — and treating it as such produced the exact failure it
    exists to catch: with no `EvalPassRate` ever published, `nightly` omitted
    the metric entirely, the alarm sat in INSUFFICIENT_DATA, and
    INSUFFICIENT_DATA was notBreaching. Nobody had measured anything, and
    nothing said so. eng-code-reviewer, M06.

    Two changes close it and both are needed: the nightly emits a sentinel
    rather than nothing (`src/ops/nightly.py:NEVER_RECORDED_HOURS`), which
    covers "no run has ever recorded a pass rate"; and this, which covers the
    nightly not running at all.
    """
    alarm = next(p for p in _alarms(template).values()
                 if p.get("MetricName") == "EvalStalenessHours")
    assert alarm["TreatMissingData"] == "breaching"


def test_the_regression_alarm_sits_below_the_ruled_false_fail(template):
    """0.85 = 17/20: the M05 baseline of 18/20 less the one ruled false fail.

    Set above 0.85 and the alarm fires on q03, which the SME seat has already
    ruled is a false fail (milestones/M05/q03-ruling.md) — an alarm that pages
    on a known, decided non-defect gets muted, and then it is not an alarm.
    """
    alarm = next(p for p in _alarms(template).values()
                 if p.get("MetricName") == "EvalPassRate")
    assert alarm["Threshold"] == 0.85
    assert alarm["ComparisonOperator"] == "LessThanThreshold"


def test_every_alarm_explains_itself(template):
    """The description is read at 03:00 by someone who did not write it."""
    for name, p in _alarms(template).items():
        desc = p.get("AlarmDescription", "")
        assert len(desc) > 80, f"{name} has no usable description"


# ------------------------------------------------------------ metric filters
def test_the_janitor_filters_read_structured_fields_not_prose(template):
    """A substring filter over a message breaks when the wording improves.

    The patterns are separately checked against the janitor's REAL output
    through CloudWatch's own matcher — milestones/M06/janitor_filter_probe.py,
    six specimens, two of them copied from the live M05 teardown. This test
    only pins that they address `$.janitor.*` rather than free text.
    """
    filters = _of_type(template, "AWS::Logs::MetricFilter")
    assert len(filters) == 2
    for f in filters.values():
        pattern = f["Properties"]["FilterPattern"]
        assert "$.janitor." in pattern, pattern
        assert f["Properties"]["MetricTransformations"][0]["MetricNamespace"] \
            == "RegDelta"
        # A filter with no default value emits NOTHING on a non-matching line,
        # which is right here — but the metric must still exist so the alarm
        # has something to attach to.
        assert f["Properties"]["MetricTransformations"][0]["MetricValue"] == "1"


def test_the_could_not_act_filter_does_not_match_an_ordinary_delete(template):
    """The distinction the whole alarm design rests on.

    `delete-requested` carries `billing_stopped: false` legitimately — the
    janitor cannot watch a delete finish (ADR-0013). Alarming on it would page
    every time the hot tier was left up overnight, which is worth SEEING and
    not worth paging about.
    """
    filters = _of_type(template, "AWS::Logs::MetricFilter")
    could_not_act = next(
        f["Properties"]["FilterPattern"] for f in filters.values()
        if f["Properties"]["MetricTransformations"][0]["MetricName"]
        == "JanitorCouldNotAct")
    assert "delete-requested" not in could_not_act
    assert "unhandled-state" in could_not_act
    assert "unhandled-error" in could_not_act
    assert "retry_of_failed" in could_not_act


# ------------------------------------------------------------------- scoping
def test_the_nightly_role_cannot_publish_metrics(template):
    """It reads CloudWatch; it must not be able to write to it.

    A scheduled, unattended role that can `PutMetricData` can forge the numbers
    the dashboard and the regression alarm are trusted for. That is a quieter
    failure than deleting something and it is the one worth closing here: the
    function emits everything it measures through EMF on stdout and needs no
    write at all.
    """
    fn = _fn_by_handler(template, "ops.nightly.handler")
    actions = {a for s in _statements_for(template, _role_of(fn))
               for a in _actions(s)}
    assert "cloudwatch:GetMetricStatistics" in actions
    assert not {a for a in actions if a.startswith("cloudwatch:Put")}
    assert "cloudwatch:*" not in actions


def test_the_nightly_role_cannot_write_the_registry(template):
    """It reads the corpus fingerprint and the amendment graph. Nothing else.

    The registry is SPEC/01's source of truth for every date this product
    states; an unattended nightly job with write access to it is a way for a
    monitoring bug to become a wrong compliance answer.
    """
    fn = _fn_by_handler(template, "ops.nightly.handler")
    actions = {a for s in _statements_for(template, _role_of(fn))
               for a in _actions(s)}
    writes = {a for a in actions
              if a.startswith("dynamodb:")
              and any(w in a for w in ("Put", "Update", "Delete", "Write"))}
    assert not writes, writes


def test_the_xray_grant_is_only_the_two_write_actions(template):
    """`xray:*` would include `GetTraceSummaries` and the sampling-rule API.

    The daemon needs exactly two actions. These genuinely do not accept a
    resource ARN — unlike the `aoss:*` control-plane grant M05 had to correct
    after that same claim turned out to be false there — so the wildcard
    resource is checked to be paired with a narrow action list.
    """
    fn = _fn_by_handler(template, "api.api.handler")
    xray = [s for s in _statements_for(template, _role_of(fn))
            if any(a.startswith("xray:") for a in _actions(s))]
    assert len(xray) == 1
    assert set(_actions(xray[0])) == {"xray:PutTraceSegments",
                                      "xray:PutTelemetryRecords"}


def test_the_alarm_topic_has_no_subscription(template):
    """Deliberate, and asserted so it is a decision rather than an oversight.

    SPEC/04's SES identity for notifications is still a TODO. Inventing an
    email destination here would be a delivery promise nobody has tested; an
    alarm with no action still changes state, still shows on the dashboard, and
    still answers "was it firing last Tuesday".
    """
    assert _of_type(template, "AWS::SNS::Topic")
    assert not _of_type(template, "AWS::SNS::Subscription")
