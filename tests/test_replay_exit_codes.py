"""What `replay_history.py` gates on, pinned — because CI now depends on it.

The distinction is the whole design and it is easy to get wrong. FRAGILE and
REGRESSED are defects a change either introduces or does not, so they fail the
run. ADMITTED — "the naive control's own answer satisfies this question" — is a
standing property of the question set, owned by the SME seat, true of six
questions today. Gating on it would fail every PR in the repo over an open
question its author did not cause and cannot fix.

The first version of this script returned 1 for all three. Adding it to CI in
that state would have turned the branch red on the very commit that added it,
which is how the distinction was found: by running it under CI conditions rather
than reasoning about it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "evals" / "replay_history.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          cwd=ROOT, capture_output=True, text=True)


def test_the_repo_as_it_stands_does_not_fail_ci():
    """The check CI actually runs. If this ever fails, either a real FRAGILE or
    REGRESSED finding appeared — which is the point — or the gating rule drifted."""
    r = _run()
    assert r.returncode == 0, (
        f"replay_history exited {r.returncode}; CI would be red.\n"
        f"{r.stdout[-1500:]}")


def test_admitted_findings_are_reported_but_do_not_gate():
    r = _run()
    if "ADMITTED" not in r.stdout:
        pytest.skip("no ADMITTED findings on file right now")
    assert r.returncode == 0
    assert "REPORTED, not gated" in r.stdout, \
        "an ADMITTED finding must say plainly that it is not gating"


def test_strict_gates_on_admitted():
    r = _run("--strict")
    if "ADMITTED" not in r.stdout:
        pytest.skip("no ADMITTED findings on file right now")
    assert r.returncode == 1, "--strict must fail when ADMITTED findings exist"


def test_it_runs_with_no_aws_environment_at_all():
    """CI has no credentials and no region. This script imports run_evals, which
    DOES carry boto3 and network code — so the import path must stay inert."""
    import os
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("AWS_") and k not in ("HOME", "USERPROFILE")}
    env.update({"PATH": os.environ["PATH"],
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "HOME": str(ROOT / "nonexistent"),
                "USERPROFILE": str(ROOT / "nonexistent")})
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"failed without AWS env:\n{r.stderr[-800:]}"
    assert "Traceback" not in r.stderr


def test_scoping_to_one_id_still_works():
    r = _run("--id", "q05")
    assert r.returncode == 0
    assert "q05" in r.stdout
    assert "q01" not in r.stdout.split("---")[0]


# --------------------------------------------------------------- direction
# FRAGILE became directional on 2026-08-18: pass -> fail gates, fail -> pass
# reports. Undirected, it flagged any disagreement over runs POOLED ACROSS
# COMMITS, so a question that was fixed read as a defect — and since history is
# append-only, permanently one. q14 turned CI red exactly that way.
#
# These drive the module over fixture cards rather than the repo's own history,
# because the repo's history is evidence about the repo and will keep changing;
# the RULE has to be pinned against cases that do not move.
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402

sys.path.insert(0, str(ROOT / "evals"))
import replay_history  # noqa: E402

QUESTION = {"id": "qX", "question": "does it?", "must_contain": ["101.13(h)"]}


def card(tmp_path, name, at, passed, *, mode="agent"):
    """One scorecard on disk, with the answer that makes it pass or fail."""
    answer = "cites 101.13(h)" if passed else "cites nothing useful"
    (tmp_path / f"{name}.json").write_text(json.dumps({
        "sha": name.split("-")[0], "at": at, "mode": mode,
        "questions": [{"id": "qX", "pass": passed,
                       "response": {"answer": answer, "citations": []}}],
    }), encoding="utf-8")


def replay(tmp_path, monkeypatch, golden=None, argv=()):
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps({"questions": [golden or QUESTION]}),
                           encoding="utf-8")
    monkeypatch.setattr(replay_history, "HISTORY", tmp_path)
    monkeypatch.setattr(replay_history, "GOLDEN", golden_path)
    monkeypatch.setattr(sys, "argv", ["replay_history.py", *argv])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = replay_history.main()
    return rc, buf.getvalue()


def test_pass_then_fail_still_gates(tmp_path, monkeypatch):
    """The half that is a defect. A question passing on the wording of the day
    is how q05 passed at 2cea737 and failed at e26d8ef with identical tokens."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", True)
    card(tmp_path, "bbbbbbb-s3vectors-full", "2026-08-02T00:00:00+00:00", False)
    rc, out = replay(tmp_path, monkeypatch)
    assert rc == 1
    assert "FRAGILE" in out


def test_fail_then_pass_reports_and_does_not_gate(tmp_path, monkeypatch):
    """A question the repo repaired. Gating on it taxes every future fix, and
    the pre-fix cards never age out."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", False)
    card(tmp_path, "bbbbbbb-s3vectors-full", "2026-08-02T00:00:00+00:00", True)
    rc, out = replay(tmp_path, monkeypatch)
    assert rc == 0
    assert "IMPROVED" in out
    assert "FRAGILE" not in out


def test_a_fix_that_later_breaks_is_still_caught(tmp_path, monkeypatch):
    """fail -> pass -> fail contains a pass -> fail, so it gates. IMPROVED must
    not become a way to launder an oscillating question."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", False)
    card(tmp_path, "bbbbbbb-s3vectors-full", "2026-08-02T00:00:00+00:00", True)
    card(tmp_path, "ccccccc-s3vectors-full", "2026-08-03T00:00:00+00:00", False)
    rc, out = replay(tmp_path, monkeypatch)
    assert rc == 1
    assert "FRAGILE" in out


def test_direction_is_read_from_the_timestamp_not_the_filename(tmp_path, monkeypatch):
    """LOAD-BEARING, and it is q14's own shape.

    Cards were sorted by `HISTORY.glob("*.json")` — alphabetically, by the sha
    in the name — under a docstring claiming "oldest card first". q14's three
    cards sort 2cea737, a7bd28c, e26d8ef by name but ran FAIL, FAIL, PASS in
    time. By name that reads FAIL -> PASS -> FAIL: a pass -> fail transition
    that never happened, and the gate would still be red.

    So this names the cards so that alphabetical order REVERSES the true order.
    """
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-09T00:00:00+00:00", True)
    card(tmp_path, "zzzzzzz-s3vectors-full", "2026-08-01T00:00:00+00:00", False)
    rc, out = replay(tmp_path, monkeypatch)
    assert rc == 0, "sorted by name this is PASS -> FAIL and would gate"
    assert "IMPROVED" in out


def test_a_card_with_no_timestamp_does_not_crash_the_run(tmp_path, monkeypatch):
    """Cards predating `at`, or hand-written ones, must sort somewhere
    deterministic rather than taking the gate down."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", False)
    (tmp_path / "bbbbbbb-s3vectors-full.json").write_text(json.dumps({
        "sha": "bbbbbbb", "mode": "agent",
        "questions": [{"id": "qX", "pass": True,
                       "response": {"answer": "cites 101.13(h)"}}],
    }), encoding="utf-8")
    rc, _ = replay(tmp_path, monkeypatch)
    assert rc in (0, 1)   # a verdict, not a traceback
