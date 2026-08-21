"""The question counts `make smoke` and `make evals` declare to the Opus guard.

`evals/check_opus_headroom.py` refuses a run that would approach the
non-adjustable daily cap, and it is told how many questions the run will ask.
The Makefile states those counts as literals — 5 and 20 — rather than deriving
them, so that changing a subset shows up as a diff against the guard rather
than silently loosening it.

A literal nobody checks is exactly the kind of stale number this project keeps
finding, so these tests are the check. If the golden set grows, both this file
and the Makefile fail together, which is the intended cost.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

GOLDEN = json.loads(
    (ROOT / "evals" / "golden_questions.json").read_text(encoding="utf-8"))
QUESTIONS = GOLDEN if isinstance(GOLDEN, list) else GOLDEN.get("questions", [])
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def declared(target: str) -> int:
    """The `--questions N` the named target passes to the guard."""
    body = MAKEFILE.split(f"\n{target}:", 1)[1].split("\n\n", 1)[0]
    match = re.search(r"--questions (\d+)", body)
    assert match, f"{target} does not check Opus headroom at all"
    return int(match.group(1))


def test_the_golden_set_is_not_empty():
    """Every count below is a fraction of this; a parse failure would make all
    of them vacuously true."""
    assert len(QUESTIONS) >= 5


def test_make_evals_declares_the_whole_golden_set():
    assert declared("evals") == len(QUESTIONS)


def test_make_smoke_declares_the_smoke_subset():
    smoke = [q for q in QUESTIONS if "smoke" in (q.get("subset") or [])]
    assert smoke, "no question is tagged `smoke`; the subset would be empty"
    assert declared("smoke") == len(smoke)


def test_both_targets_check_before_they_spend():
    """`&&`, not `;`. Chained with a semicolon the guard prints its refusal and
    the run proceeds anyway, which is worse than no guard: it produces a log
    line saying the cap was about to be crossed, next to the run that crossed
    it."""
    for target in ("smoke", "evals"):
        body = MAKEFILE.split(f"\n{target}:", 1)[1].split("\n\n", 1)[0]
        guard_at = body.index("check_opus_headroom.py")
        run_at = body.index("run_evals.py")
        assert guard_at < run_at, f"{target} spends before it checks"
        between = body[guard_at:run_at]
        assert "&&" in between, (
            f"{target} does not chain the guard with && — a refusal would not "
            "stop the run")
