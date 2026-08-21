"""Capture the dashboard as evidence rather than as a claim about a screenshot.

SPEC/06's Done-when says the dashboard is "screenshot-ready". A screenshot is a
picture a person took, and "I looked at it and it was fine" is not something a
later reader can check — which is the standard every other artifact in this
milestone is held to.

So this records two things a reader CAN check:

  * `dashboard-definition.json` — what CloudWatch says the dashboard is, from
    `GetDashboard`. Proves the widgets exist and what metrics they read.
  * `dashboard-<widget>.png` — rendered images from `GetMetricWidgetImage`, one
    per panel. These are the panels WITH THE DATA IN THEM at the moment of
    capture, which is the half a definition cannot show.

A console screenshot is still worth taking and this does not replace it. What
it replaces is the *claim* that one was taken and looked right.

## The panels this captures, and why those

The five fed by `/query` (latency, cache hit rate, cost per query, HITL rate,
Lambda concurrency) plus retrieval-latency-by-tier, which is the one the
disposition run feeds and the one SPEC/06's Tier B clause is actually about.

Run after the traffic and the disposition run, while the hot tier is up:

    eval "$(python evals/local_env.py)"
    python milestones/M06/dashboard_snapshot.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shared import config  # noqa: E402

HERE = Path(__file__).parent
DASHBOARD = "regdelta"

#: How far back each rendered widget looks. Three hours covers this session's
#: whole window — the disposition run, the traffic, and the deploy — without
#: dragging in a previous day that would make the panels look busier than the
#: evidence supports.
LOOKBACK_S = 3 * 3600


def _datapoints(cw, props: dict) -> dict:
    """How many datapoints this panel's math expressions actually return.

    RENDERING IS NOT DATA, and conflating them cost this milestone a round
    trip. Three ratio panels here carried an expression CloudWatch could not
    evaluate; fixing it made them render, and they rendered EMPTY, because the
    metrics they named — `Queries` identified by `cache` alone, `BedrockCostUsd`
    by nothing — are dimension combinations EMF never publishes. The first
    defect hid the second, and a capture script that only asked "did it render"
    would have filed the empty panels as evidence.

    Only expression panels are checked. A plain metric panel is its own claim:
    it names a metric and either the metric has data or the system was idle.
    """
    exprs = [row[0]["expression"] for row in props.get("metrics") or []
             if isinstance(row, list) and row and isinstance(row[0], dict)
             and "expression" in row[0]]
    if not exprs:
        return {"expressions": 0}
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(seconds=LOOKBACK_S)
    total = 0
    for n, expr in enumerate(exprs):
        try:
            r = cw.get_metric_data(
                MetricDataQueries=[{"Id": f"probe{n}", "Expression": expr,
                                    "Period": 300, "ReturnData": True}],
                StartTime=start, EndTime=end)
            total += sum(len(res["Values"]) for res in r["MetricDataResults"])
        except Exception:                          # noqa: BLE001
            # The render call reports the error with better wording; this is
            # only the data question, and a failure here is not a second
            # finding.
            pass
    return {"expressions": len(exprs), "datapoints": total}


def main() -> int:
    import boto3

    cw = boto3.client("cloudwatch", region_name=config.REGION)

    body = cw.get_dashboard(DashboardName=DASHBOARD)["DashboardBody"]
    definition = json.loads(body)
    (HERE / "dashboard-definition.json").write_text(
        json.dumps(definition, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    widgets = [w for w in definition.get("widgets") or []
               if w.get("type") == "metric"]
    print(f"dashboard {DASHBOARD!r}: {len(definition.get('widgets') or [])} "
          f"widgets, {len(widgets)} of them metric widgets")

    captured, failed = [], []
    for i, widget in enumerate(widgets):
        props = dict(widget.get("properties") or {})
        title = str(props.get("title") or f"widget-{i}")
        datapoints = _datapoints(cw, props)
        # The widget's own definition, rendered with an explicit window. Left
        # to itself `GetMetricWidgetImage` uses whatever `start`/`end` the
        # dashboard carries, which is a relative window a reader cannot pin.
        props.update({"start": f"-PT{LOOKBACK_S // 3600}H", "end": "P0D",
                      "width": 1000, "height": 300,
                      "region": config.REGION})
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())
        slug = "-".join(p for p in slug.split("-") if p)[:60]
        try:
            png = cw.get_metric_widget_image(
                MetricWidget=json.dumps(props), OutputFormat="png")["MetricWidgetImage"]
        except Exception as e:                     # noqa: BLE001
            failed.append({"title": title, "error": f"{type(e).__name__}: {e}"[:200]})
            print(f"  ✗ {title}: {type(e).__name__}")
            continue
        path = HERE / f"dashboard-{slug}.png"
        path.write_bytes(png)
        captured.append({"title": title, "file": path.name, "bytes": len(png),
                         **datapoints})
        note = ""
        if datapoints.get("expressions"):
            n = datapoints["datapoints"]
            note = f"  [{n} datapoint{'' if n == 1 else 's'}]" if n \
                else "  [RENDERS BUT EMPTY]"
        print(f"  ✓ {title} -> {path.name} ({len(png):,} bytes){note}")

    index = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "dashboard": DASHBOARD,
        "region": config.REGION,
        "console_url": f"https://{config.REGION}.console.aws.amazon.com/cloudwatch"
                       f"/home?region={config.REGION}#dashboards:name={DASHBOARD}",
        "lookback_hours": LOOKBACK_S // 3600,
        "widgets_total": len(definition.get("widgets") or []),
        "captured": captured,
        "failed": failed,
        "empty_expression_panels": [c["title"] for c in captured
                                    if c.get("expressions")
                                    and not c.get("datapoints")],
        "note": "PNGs are the panels WITH DATA at the moment of capture. The "
                "definition JSON beside them proves which metrics each panel "
                "reads. `datapoints` is the separate question of whether an "
                "expression panel is wired to a metric that exists — a panel "
                "can render perfectly and be empty, and at M06 three of them "
                "were. Neither replaces a console screenshot; together they "
                "replace the CLAIM that one was taken and looked right.",
    }
    (HERE / "dashboard-snapshot.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n{len(captured)}/{len(widgets)} panels captured "
          f"-> milestones/M06/dashboard-snapshot.json")

    if failed:
        print("some panels did not render; the evidence is incomplete",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
