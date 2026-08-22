"""What the admitted-false-fail register may and may not do.

The register is an override list, and the standing objection to an override
list is that it becomes a general admit path — the thing M05 §11 refused when
it declined to build one into FRAGILE. The answer given in ADR-0015 is that an
entry names an ARTIFACT rather than a rule, so these tests exist to pin that
claim rather than to restate it: every way an entry could reach past the one
observation the seat ruled on has a test that it does not.

The subprocess tests read the REAL register and the real history, so they also
serve as the standing check that the repo's own green gate is green for the
reason it claims. If q03 is ever genuinely fixed, its entry stops matching
anything, `replay_history` reports STALE ADMISSION and gates, and
`test_the_gate_is_green_only_because_of_the_register` says so. That is the
register self-cleaning, not a defect — remove the entry.
"""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "evals" / "replay_history.py"
REGISTER = ROOT / "evals" / "admitted_false_fails.json"

sys.path.insert(0, str(ROOT / "evals"))
import replay_history  # noqa: E402
from run_evals import flatten_answer  # noqa: E402

REQUIRED = ("question", "sha", "scored_sha256", "admits_fails", "ruling",
            "ruled_at", "why")

QUESTION = {"id": "qX", "question": "does it?", "must_contain": ["101.13(h)"]}
PASSING, FAILING = "cites 101.13(h)", "cites nothing useful"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def digest(answer: str) -> str:
    return hashlib.sha256(
        flatten_answer({"answer": answer, "citations": []}).encode()).hexdigest()


def card(tmp_path, name, at, passed, *, mode="agent"):
    (tmp_path / f"{name}.json").write_text(json.dumps({
        "sha": name.split("-")[0], "at": at, "mode": mode,
        "questions": [{"id": "qX", "pass": passed,
                       "response": {"answer": PASSING if passed else FAILING,
                                    "citations": []}}],
    }), encoding="utf-8")


def replay(tmp_path, monkeypatch, entries=(), argv=()):
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": [QUESTION]}), encoding="utf-8")
    register = tmp_path / "admitted.json"
    register.write_text(json.dumps({"admissions": list(entries)}), encoding="utf-8")
    monkeypatch.setattr(replay_history, "HISTORY", tmp_path)
    monkeypatch.setattr(replay_history, "GOLDEN", golden)
    monkeypatch.setattr(replay_history, "ADMISSIONS", register)
    monkeypatch.setattr(sys, "argv", ["replay_history.py", *argv])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = replay_history.main()
    return rc, buf.getvalue()


def entry(**over):
    """The shape that WOULD admit the failing synthetic card."""
    base = {"question": "qX", "sha": "bbbbbbb",
            "scored_sha256": digest(FAILING),
            "admits_fails": ["missing required: '101.13(h)'"],
            "ruling": "milestones/M07/q03-rulings.md", "ruled_at": "2026-08-21",
            "why": ["synthetic"]}
    base.update(over)
    return base


def fragile_history(tmp_path):
    """PASS then FAIL — the shape that gates without an admission."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", True)
    card(tmp_path, "bbbbbbb-s3vectors-full", "2026-08-02T00:00:00+00:00", False)


# --------------------------------------------------------------------------
# The register as it stands in this repo
# --------------------------------------------------------------------------

def test_the_real_register_parses_and_every_entry_is_complete():
    doc = json.loads(REGISTER.read_text(encoding="utf-8"))
    for e in doc["admissions"]:
        missing = [k for k in REQUIRED if not e.get(k)]
        assert not missing, f"{e.get('question')} at {e.get('sha')}: {missing}"
        assert len(e["scored_sha256"]) == 64, "digest is not a sha256"
        assert isinstance(e["admits_fails"], list) and e["admits_fails"], \
            "an entry admitting no failure reason admits nothing"


def test_every_entry_cites_a_ruling_document_that_exists():
    """ADR-0005: what makes a seat ruling sound is a source a reader can
    falsify. An entry pointing at a document that is not there is an assertion
    with a citation-shaped hole in it.

    `replay_history.cites_ruling` now enforces this at runtime too, so this
    test is the fast, named failure rather than the only line of defence."""
    for e in json.loads(REGISTER.read_text(encoding="utf-8"))["admissions"]:
        assert (ROOT / e["ruling"]).exists(), \
            f"{e['question']} at {e['sha']} cites {e['ruling']}, which is absent"
        assert replay_history.cites_ruling(e)


def test_m07_adds_exactly_one_entry():
    """SPEC/07 Out of scope, and the SME ruling it comes from
    (milestones/M07/q03-rulings.md §A.4): "one entry (q03 at 1f46b92) is what
    the measurement covers, and I would not open it wider."

    A second entry is a new seat ruling, not an application of this one. This
    test is what stops the register growing by habit — it fails on the second
    entry and sends whoever added it back to a seat."""
    doc = json.loads(REGISTER.read_text(encoding="utf-8"))
    assert len(doc["admissions"]) == 1, (
        "the register has grown past the one observation M07's SME ruling "
        "covers. A new entry needs its own ruling and its own line in SPEC/07 "
        "Out of scope — not a passing edit to this test.")
    only = doc["admissions"][0]
    assert (only["question"], only["sha"]) == ("q03", "1f46b92")


def test_the_gate_is_green_only_because_of_the_register():
    """The honesty test. `unit` is green; this pins WHY, so the register can
    never quietly stop being the reason and leave a stale entry behind."""
    assert _run().returncode == 0, "the repo's own gate is red"
    audit = _run("--no-admissions")
    assert audit.returncode == 1, (
        "--no-admissions came back clean, so nothing in the register is "
        "load-bearing. Either q03 was really fixed — in which case remove the "
        "entry — or the register stopped being consulted.")
    assert "FRAGILE" in audit.stdout


def test_the_admission_is_reported_on_every_run():
    """Its whole defence is visibility. A suppression a reader has to go
    looking for is the thing M05 §11 refused."""
    out = _run().stdout
    assert "FALSE FAIL" in out
    assert "milestones/M07/q03-rulings.md" in out


def test_an_admitted_run_prints_admit_and_not_pass():
    out = _run("--id", "q03").stdout
    assert "1f46b92:agent=ADMIT" in out, \
        "an admitted answer must not be indistinguishable from one that passed"


# --------------------------------------------------------------------------
# What an entry may not reach — one test per thing that must match
# --------------------------------------------------------------------------

def test_the_ruled_entry_admits_its_own_observation(tmp_path, monkeypatch):
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch, [entry()])
    assert rc == 0
    assert "FALSE FAIL" in out and "FRAGILE" not in out


def test_a_paraphrase_is_not_admitted(tmp_path, monkeypatch):
    """THE LOAD-BEARING ONE. q03's whole difficulty is that a correct answer and
    a defective one differ only in wording, so an admission keyed on anything
    weaker than the answer itself would generalise to the next paraphrase —
    which is exactly the general admit path that was refused."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch,
                     [entry(scored_sha256=digest("cites something else"))])
    assert rc == 1
    assert "FRAGILE" in out


def test_a_different_failure_reason_is_not_admitted(tmp_path, monkeypatch):
    """The same recorded answer, failing for a reason the seat did not rule on
    — a token added to the golden set, a new check kind. The entry must not
    silence a defect it was not written for."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch,
                     [entry(admits_fails=["forbidden text present: 'x'"])])
    assert rc == 1
    assert "FRAGILE" in out


def test_an_extra_failure_reason_is_not_admitted(tmp_path, monkeypatch):
    """Matching is exact, not subset: an answer failing on the ruled reason AND
    something else is not the observation that was ruled on."""
    fragile_history(tmp_path)
    rc, _ = replay(tmp_path, monkeypatch, [entry(
        admits_fails=["missing required: '101.13(h)'", "something else"])])
    assert rc == 1


def test_another_sha_is_not_admitted(tmp_path, monkeypatch):
    fragile_history(tmp_path)
    rc, _ = replay(tmp_path, monkeypatch, [entry(sha="aaaaaaa")])
    assert rc == 1


def test_an_admission_cannot_suppress_a_passing_answer(tmp_path, monkeypatch):
    """It can only ever subtract a failure. An entry aimed at an answer that
    passes reaches nothing and is reported stale."""
    card(tmp_path, "aaaaaaa-s3vectors-full", "2026-08-01T00:00:00+00:00", True)
    card(tmp_path, "bbbbbbb-s3vectors-full", "2026-08-02T00:00:00+00:00", True)
    rc, out = replay(tmp_path, monkeypatch,
                     [entry(sha="bbbbbbb", scored_sha256=digest(PASSING))])
    assert rc == 1
    assert "STALE ADMISSION" in out
    assert "FALSE FAIL" not in out


# --------------------------------------------------------------------------
# Rot, and the scoping bug that the first version of the rot check caused
# --------------------------------------------------------------------------

def test_an_entry_citing_no_ruling_does_not_admit(tmp_path, monkeypatch):
    """FOUND BY pm-spec-reviewer, M07 finding 2, and it was a hole in the
    mechanism rather than only in the prose. `ruling` was read at print time
    only, so an entry with no ruling admitted the failure exactly as well as a
    ruled one and printed "— None". SPEC/07 and ADR-0015 both asserted "every
    admission cites a ruling" as a fact while nothing required it.

    ADR-0005: what makes a seat ruling sound is a source a reader can falsify.
    An override citing nothing is not a ruling, so it admits nothing."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch, [entry(ruling="")])
    assert rc == 1
    assert "UNCITED ADMISSION" in out
    assert "FALSE FAIL" not in out
    assert "FRAGILE" in out, "the failure it tried to admit must still stand"


def test_an_entry_citing_an_absent_document_does_not_admit(tmp_path, monkeypatch):
    """A path that does not resolve is the same defect with a longer string."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch,
                     [entry(ruling="milestones/M07/does-not-exist.md")])
    assert rc == 1
    assert "UNCITED ADMISSION" in out


def test_an_uncited_entry_is_not_also_reported_stale(tmp_path, monkeypatch):
    """It matched an answer; it is unusable for a different reason. Reporting
    it twice under two names would describe one defect as two."""
    fragile_history(tmp_path)
    _, out = replay(tmp_path, monkeypatch, [entry(ruling="")])
    assert "STALE ADMISSION" not in out


def test_a_stale_entry_gates(tmp_path, monkeypatch):
    """The register paying for itself. An entry that describes nothing is the
    list rotting into a general admit path, and it can only be caused by
    editing the register or the history — never by an ordinary change."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch, [entry(), entry(sha="ccccccc")])
    assert rc == 1
    assert "STALE ADMISSION" in out


def test_scoping_to_another_question_does_not_make_an_entry_stale(tmp_path,
                                                                  monkeypatch):
    """REGRESSION. The first version of the staleness check compared usage
    against the WHOLE register, so `--id q05` reported q03's entry as stale and
    turned the gate red on a scoping flag. Two synthetic-history tests failed
    the same way. An entry describes an observation; a run that never looked at
    that question has learned nothing about it."""
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch, [entry(question="qOTHER")])
    assert rc == 1, "qX itself is still FRAGILE here"
    assert "STALE ADMISSION" not in out
    assert "NOT EVALUATED" in out


def test_no_admissions_reports_the_unadmitted_state(tmp_path, monkeypatch):
    fragile_history(tmp_path)
    rc, out = replay(tmp_path, monkeypatch, [entry()], argv=("--no-admissions",))
    assert rc == 1
    assert "FRAGILE" in out and "FALSE FAIL" not in out


def test_a_missing_register_gates_more_not_less(tmp_path, monkeypatch):
    """A checkout without the file must be stricter, never looser."""
    fragile_history(tmp_path)
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": [QUESTION]}), encoding="utf-8")
    monkeypatch.setattr(replay_history, "HISTORY", tmp_path)
    monkeypatch.setattr(replay_history, "GOLDEN", golden)
    monkeypatch.setattr(replay_history, "ADMISSIONS", tmp_path / "absent.json")
    monkeypatch.setattr(sys, "argv", ["replay_history.py"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = replay_history.main()
    assert rc == 1
    assert "FRAGILE" in buf.getvalue()


def test_run_evals_is_untouched_by_the_register():
    """The register is about what blocks a MERGE, not about what the scorer
    believes. `make evals` must still score the admitted answer as failing, or
    the live scorecard stops being evidence."""
    import run_evals

    assert not hasattr(run_evals, "ADMISSIONS")
    source = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert "admitted_false_fails" not in source, \
        "the register reached the scorer; it must only reach the gate"
