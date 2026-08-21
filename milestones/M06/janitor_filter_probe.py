"""Do the SPEC/06 alarm patterns match the janitor's REAL log lines?

A metric filter that matches nothing produces a metric that is always zero, and
an alarm on an always-zero metric is green forever. That failure is invisible
from the template, from the console, and from any test that reads the pattern
string — the pattern is syntactically valid and semantically wrong, and nothing
says so.

So the patterns are run against the janitor's actual output, through
CloudWatch's own matcher (`logs:TestMetricFilter`), which is the same engine
that will evaluate them in production. Free, read-only, no log group needed.

THE SPECIMENS ARE NOT INVENTED. Every line below is a return value from
`infra/lambdas/janitor/handler.py` rendered through its own `_log()`, and two
of them are copied from the live M05 window recorded in
`milestones/M05/README.md`. A specimen written by the pattern's author to
match the pattern proves nothing — that is the 2026-08-15 lesson this repo
keeps re-learning — so these are derived from the handler instead.

Run: python milestones/M06/janitor_filter_probe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra" / "lambdas" / "janitor"))

STACK = "regdelta-search"

COULD_NOT_ACT = ('{ ($.janitor.status = "unhandled-state") '
                 '|| ($.janitor.status = "unhandled-error") '
                 '|| ($.janitor.retry_of_failed IS TRUE) }')
DELETE_REQUESTED = '{ $.janitor.status = "delete-requested" }'


def line(result: dict) -> str:
    """Exactly what `handler._log` prints, without importing the handler.

    The handler needs two environment variables at import time, and reproducing
    its one-line `json.dumps` is smaller than faking those. The shape is
    asserted against the handler's source below so this cannot drift.
    """
    return json.dumps({"janitor": result, "stack": STACK}, sort_keys=True)


#: (id, the janitor result, must COULD_NOT_ACT match, must DELETE_REQUESTED match)
SPECIMENS = [
    ("already-down (the only status that means billing stopped)",
     {"status": "already-down", "billing_stopped": True}, False, False),

    ("delete-requested — LIVE, M05 README, the real teardown",
     {"status": "delete-requested", "was": "UPDATE_ROLLBACK_COMPLETE",
      "billing_stopped": False, "retry_of_failed": False,
      "role_arn": "arn:aws:iam::581208540944:role/SearchStackDeletionRole"},
     False, True),

    ("delete-requested RETRYING a failed delete — a collection has billed a day",
     {"status": "delete-requested", "was": "DELETE_FAILED",
      "billing_stopped": False, "retry_of_failed": True,
      "role_arn": "arn:aws:iam::581208540944:role/SearchStackDeletionRole"},
     True, True),

    ("no-action, a delete already in flight",
     {"status": "no-action", "state": "DELETE_IN_PROGRESS",
      "billing_stopped": False,
      "detail": "a stack operation is already in flight"}, False, False),

    ("unhandled-state — the state set the janitor does not recognise",
     {"status": "unhandled-state", "state": "REVIEW_IN_PROGRESS",
      "billing_stopped": False,
      "detail": "not in the deletable or in-flight sets; the collection may "
                "still be billing"}, True, False),

    ("unhandled-error — could not READ the stack, so knows nothing",
     {"status": "unhandled-error", "billing_stopped": False,
      "error": "ClientError: AccessDenied",
      "detail": "could not read the stack, so nothing is known about whether "
                "it is billing"}, True, False),
]


def check_source_shape() -> None:
    """The wrapper key really is `janitor`, read off the handler's source.

    Without this, every specimen could be built around a key the handler does
    not use and the whole probe would agree with itself.
    """
    src = (ROOT / "infra" / "lambdas" / "janitor" / "handler.py").read_text(
        encoding="utf-8")
    assert 'json.dumps({"janitor": result, "stack": STACK}' in src, (
        "handler._log no longer prints {'janitor': ..., 'stack': ...}; these "
        "patterns are addressed at a shape that has moved")


def main() -> int:
    check_source_shape()
    logs = boto3.client("logs")
    messages = [line(s[1]) for s in SPECIMENS]

    results = {}
    for label, pattern in (("could_not_act", COULD_NOT_ACT),
                           ("delete_requested", DELETE_REQUESTED)):
        matched = logs.test_metric_filter(
            filterPattern=pattern,
            logEventMessages=messages)["matches"]
        results[label] = {m["eventNumber"] for m in matched}

    print(f"{'specimen':62s} {'could_not_act':>14s} {'delete_req':>11s}")
    failures = []
    for i, (name, _result, want_cna, want_dr) in enumerate(SPECIMENS, start=1):
        got_cna = i in results["could_not_act"]
        got_dr = i in results["delete_requested"]
        ok = (got_cna == want_cna) and (got_dr == want_dr)
        mark = "" if ok else "   <-- WRONG"
        print(f"{name[:60]:62s} {str(got_cna):>14s} {str(got_dr):>11s}{mark}")
        if not ok:
            failures.append({"specimen": name,
                             "could_not_act": {"want": want_cna, "got": got_cna},
                             "delete_requested": {"want": want_dr, "got": got_dr}})

    report = {
        "engine": "logs:TestMetricFilter — the same matcher CloudWatch will use",
        "patterns": {"could_not_act": COULD_NOT_ACT,
                     "delete_requested": DELETE_REQUESTED},
        "specimens": len(SPECIMENS),
        "failures": failures,
        "note": "specimens are the janitor's own return values, two copied "
                "from the live M05 teardown, not written to fit the patterns",
    }
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    print()
    if failures:
        print(f"{len(failures)} specimen(s) matched the wrong way — "
              f"the alarm would be green forever or noisy forever.")
        return 1
    print(f"all {len(SPECIMENS)} specimens match as intended.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
