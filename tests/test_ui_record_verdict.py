"""SPEC/08 Done-when 3 — the recorder's behaviour, driven rather than grepped.

`tests/test_ui_surface_pins.py` checks that `record_verdict.py` still MENTIONS
`git_dirty`, `_peek_trail` and `_archive`. That is a name check, and
`eng-code-reviewer` H4 showed what it misses: `"pass": bool(spec["ok"]) and …`
could be changed to `"pass": True` with every check in the repository green.
A recorder that can only file victories is exactly what Done-when 3 forbids,
and nothing was driving the function that decides.

Done-when 3 also says the supersession is "checkable by recording two runs at
one sha and reading the trail". That sentence described a check nobody had
written. This file writes it.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "ui-tests"))

import record_verdict as rv  # noqa: E402 — needs the sys.path above

APP = "https://d2rdgeiujg622n.cloudfront.net"


def _observed(**over):
    body = {"scenario": "s", "appUrl": APP, "tier": "s3vectors", "tierNote": "",
            "cache": "miss", "configuredTier": "s3vectors",
            "retrieval": "355 ms", "roundTrip": "14.47 s"}
    body.update(over)
    return {"name": "observed", "contentType": "application/json",
            "body": base64.b64encode(json.dumps(body).encode()).decode()}


def _spec(title, status, *, ok, attachments=(), errors=()):
    return {"title": title, "file": f"{title}.spec.ts", "ok": ok,
            "tests": [{"results": [{"status": status, "duration": 1000,
                                    "attachments": list(attachments),
                                    "errors": [{"message": e} for e in errors]}]}]}


def _report(specs, *, stats=None, errors=()):
    counted = stats if stats is not None else {
        "expected": sum(1 for s in specs if s["ok"]),
        "unexpected": sum(1 for s in specs if not s["ok"]),
        "flaky": 0, "skipped": 0, "duration": 79900.0}
    return {"suites": [{"title": "f", "specs": specs}], "stats": counted,
            "errors": [{"message": e} for e in errors]}


# ------------------------------------------------------------------- parse()
def test_a_failing_spec_is_counted_as_a_failure():
    """The whole point. A red run must record red."""
    report = _report([
        _spec("healthy-claim", "passed", ok=True, attachments=[_observed()]),
        _spec("needs-review", "failed", ok=False, attachments=[_observed()],
              errors=["Error: a paused run rendered a deadline"]),
    ])
    parsed = rv.parse(report)
    assert parsed["passed"] == 1
    assert parsed["total"] == 2
    assert parsed["specs"][1]["pass"] is False
    assert "a paused run rendered a deadline" in parsed["specs"][1]["errors"][0]


def test_a_timed_out_spec_is_not_a_pass():
    """M08's own failure mode: the spec died mid-assertion, `ok` false."""
    report = _report([_spec("needs-review", "timedOut", ok=False,
                            attachments=[_observed()])])
    parsed = rv.parse(report)
    assert parsed["passed"] == 0
    assert parsed["specs"][0]["status"] == "timedOut"


def test_a_spec_that_never_ran_is_counted_in_the_total():
    """An absent result is not a pass, and it is not an absent spec either."""
    report = _report([{"title": "needs-review", "file": "x", "ok": False, "tests": []}],
                     stats={"expected": 0, "unexpected": 0, "flaky": 0,
                            "skipped": 1, "duration": 1.0})
    parsed = rv.parse(report)
    assert parsed["total"] == 1
    assert parsed["passed"] == 0
    assert parsed["specs"][0]["status"] == "did not run"


def test_the_runners_own_tally_is_carried_so_a_half_loaded_suite_cannot_read_green():
    """`eng-code-reviewer` H4.

    A spec FILE that fails to transpile never appears in `suites` — it appears
    in the report's top-level `errors`. Counting only what was walked, a
    two-spec suite whose second file did not load reads 1/1 PASS.
    """
    report = _report([_spec("healthy-claim", "passed", ok=True,
                            attachments=[_observed()])],
                     stats={"expected": 1, "unexpected": 0, "flaky": 0,
                            "skipped": 0, "duration": 1.0},
                     errors=["needs-review.spec.ts: SyntaxError"])
    parsed = rv.parse(report)
    assert parsed["total"] == 1 and parsed["passed"] == 1
    # The card would read 1/1. What stops it is that the report's own errors
    # travel with the parse and main() refuses on them.
    assert parsed["report_errors"], "a top-level load error is not carried"
    assert "SyntaxError" in parsed["report_errors"][0]


def test_a_total_that_disagrees_with_the_runner_is_carried_too():
    report = _report([_spec("healthy-claim", "passed", ok=True,
                            attachments=[_observed()])],
                     stats={"expected": 1, "unexpected": 1, "flaky": 0,
                            "skipped": 0, "duration": 1.0})
    parsed = rv.parse(report)
    assert parsed["total"] == 1
    assert parsed["reported_total"] == 2


# ----------------------------------------------------------------- app_url
def test_the_url_comes_from_the_run_not_from_the_config():
    """`eng-code-reviewer` H3 / `security-reviewer` M3.

    `make ui-record` is a separate process with no APP_URL in it, so a recorder
    that re-derived the URL filed a loopback run against the deployed one.
    """
    specs = rv.parse(_report([
        _spec("a", "passed", ok=True,
              attachments=[_observed(appUrl="http://127.0.0.1:8000")]),
    ]))["specs"]
    assert rv.app_url_of(specs) == "http://127.0.0.1:8000"
    assert rv._layer(rv.app_url_of(specs)) == "L3-local"


def test_a_run_that_recorded_no_url_is_refused():
    specs = rv.parse(_report([_spec("a", "passed", ok=True)]))["specs"]
    with pytest.raises(SystemExit, match="no spec recorded the URL"):
        rv.app_url_of(specs)


def test_two_specs_that_visited_different_urls_are_refused():
    specs = rv.parse(_report([
        _spec("a", "passed", ok=True, attachments=[_observed(appUrl=APP)]),
        _spec("b", "passed", ok=True,
              attachments=[_observed(appUrl="http://127.0.0.1:8000")]),
    ]))["specs"]
    with pytest.raises(SystemExit, match="disagree about which URL"):
        rv.app_url_of(specs)


def test_only_the_deployed_url_earns_the_l3_label():
    assert rv._layer(APP) == "L3"
    for local in ("http://127.0.0.1:8000", "https://localhost:8000",
                  "http://d2rdgeiujg622n.cloudfront.net", "https://[::1]:9"):
        assert rv._layer(local) == "L3-local", local


# ------------------------------------------------------------------ errors
def test_the_operators_absolute_paths_are_stripped_from_the_card():
    """`security-reviewer` L5. The card is committed to a public repository."""
    trace = f"at {ROOT}/ui-tests/tests/needs-review.spec.ts:80:5"
    parsed = rv.parse(_report([_spec("a", "failed", ok=False,
                                     attachments=[_observed()], errors=[trace])]))
    recorded = parsed["specs"][0]["errors"][0]
    assert str(ROOT) not in recorded
    assert "ui-tests/tests/needs-review.spec.ts:80:5" in recorded


# ------------------------------------------------------------ supersession
def test_a_second_run_at_one_sha_archives_the_first(tmp_path, monkeypatch):
    """Done-when 3, in the form it is written: record twice, read the trail.

    SPEC/08's headline ruling is that the suite is not re-run until it goes
    green. A recorder that let run 2 overwrite run 1 would make re-running
    until green invisible, which is the behaviour the ruling exists to expose.
    """
    history = tmp_path / "history"
    history.mkdir()
    monkeypatch.setattr(rv.run_evals, "HISTORY", history)
    monkeypatch.setattr(rv, "HISTORY", history)

    path = history / "abc1234-playwright.json"
    for run, passed in ((1, 1), (2, 2)):
        trail = rv.run_evals._peek_trail(path)
        body = json.dumps({"sha": "abc1234", "at": f"2026-08-2{run}T00:00:00+00:00",
                           "passed": passed, "total": 2, "supersedes": trail})
        rv.run_evals._archive(path, trail)
        path.write_text(body, encoding="utf-8")

    live = json.loads(path.read_text(encoding="utf-8"))
    assert live["passed"] == 2, "the live card is the latest run"
    assert len(live["supersedes"]) == 1, "the losing run left no trace"
    assert live["supersedes"][0]["passed"] == 1
    archived = list((history / "superseded").glob("abc1234-playwright.run*.json"))
    assert len(archived) == 1, "run 1 was overwritten rather than archived"
    assert json.loads(archived[0].read_text(encoding="utf-8"))["passed"] == 1
