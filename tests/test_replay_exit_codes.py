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
