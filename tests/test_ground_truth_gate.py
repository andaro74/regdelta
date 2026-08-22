"""Door 1's gate: a ruling must be on main BEFORE the change that cites it.

Driven against real throwaway git repositories rather than mocks, because the
whole mechanism is one git question — "was this file present at the base
commit?" — and a mock would be me asserting my own answer to it. That is the
instrument defect ADR-0013 names, and the M05 assertion that survived mutation
C6 by being `"knn_vector" == "knn_vector"`.

The case that matters most is `test_a_ruling_written_in_the_same_pr_does_not_count`:
if that passes for the wrong reason, the gate is decorative and the
self-certifying hole security-reviewer named at M07 M2 is still open.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))
from check_ground_truth_ruling import SME_OWNED, evaluate  # noqa: E402

RULING = "milestones/M07/q03-rulings.md"

# A RULING NAMES WHAT IT RULES ON. The first fixture body here was "# ruling"
# and nothing else, and the gate accepted it — because the first version of the
# rule checked the SHAPE of a citation and never its subject, so `README.md`
# was a valid ruling for anything. Found by
# milestones/M07/ground_truth_gate_mutations.py, which attacks the rule rather
# than describing it. All thirteen tests in this file passed while that hole
# was open, which is what a suite written by the rule's own author is worth.
RULING_BODY = (
    "# the seat's ruling\n\n"
    "Covers evals/golden_questions.json, evals/admitted_false_fails.json\n"
    "and evals/scenarios.json.\n")


def run(repo, *args):
    return subprocess.run(("git", *args), cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def commit(repo, message, files: dict):
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        run(repo, "add", name)
    run(repo, "commit", "-m", message)
    return run(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    """A repo with one commit on main and nothing SME-owned yet."""
    run(tmp_path, "init", "-b", "main")
    run(tmp_path, "config", "user.email", "t@example.com")
    run(tmp_path, "config", "user.name", "t")
    run(tmp_path, "config", "commit.gpgsign", "false")
    commit(tmp_path, "base", {"README.md": "base\n"})
    return tmp_path


def base(repo):
    return run(repo, "rev-parse", "main").strip()


def golden(**over):
    return json.dumps({"questions": [{"id": "q01", "must_contain": ["x"], **over}]})


# --------------------------------------------------------------------------
# When the gate has nothing to say
# --------------------------------------------------------------------------

def test_a_diff_touching_nothing_owned_passes_and_says_so(repo):
    b = base(repo)
    commit(repo, "unrelated", {"src/thing.py": "x = 1\n"})
    code, out = evaluate(b, "HEAD", repo)
    assert code == 0
    assert "nothing for this gate to say" in "\n".join(out)


def test_the_watched_set_is_the_sme_owned_paths():
    """If a path is added to CODEOWNERS as SME-owned and not here, the gate
    silently stops covering it — the failure mode is invisible, so the list is
    pinned rather than left to a reader to notice."""
    assert set(SME_OWNED) == {
        "evals/golden_questions.json",
        "evals/admitted_false_fails.json",
        "evals/scenarios.json",
    }


# --------------------------------------------------------------------------
# The block
# --------------------------------------------------------------------------

def test_editing_ground_truth_with_no_ruling_is_blocked(repo):
    """Door 1 itself: the engineer edits the golden set to green a build."""
    b = base(repo)
    commit(repo, "make q01 pass", {"evals/golden_questions.json": golden()})
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 1
    assert "BLOCKED: no ruling cited." in text
    assert "Engineering may not decide what correct means" in text


def test_a_ruling_written_in_the_same_pr_does_not_count(repo):
    """THE ONE THAT MATTERS. If this passes for the wrong reason the gate is
    decorative: the change would be explaining itself, which is the
    self-certifying hole security-reviewer named at M07 M2.

    The ruling file IS in the working tree when this runs — that is exactly why
    the check asks git about the BASE commit rather than asking the
    filesystem."""
    b = base(repo)
    commit(repo, f"edit ground truth\n\nRULING: {RULING}\n",
           {"evals/golden_questions.json": golden(), RULING: RULING_BODY})
    assert (repo / RULING).exists(), "the fixture must reproduce the hazard"
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 1
    assert "no cited ruling on main names it" in text
    assert "not present on the base commit" in text
    assert "is the change explaining itself" in text


def test_a_ruling_on_main_first_lets_the_change_through(repo):
    """The intended two-PR flow, and the other direction of the test above —
    without it, "reject everything" would pass every case in this file."""
    commit(repo, "the SME ruling", {RULING: RULING_BODY})
    b = base(repo)
    commit(repo, f"apply the ruling\n\nRULING: {RULING}\n",
           {"evals/golden_questions.json": golden()})
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 0, text
    assert "on main in a separate commit before this one" in text
    assert "Merge may proceed" in text


@pytest.mark.parametrize("ruling", [
    "/etc/passwd",
    "C:/Windows/win.ini",
    "../../../etc/hostname",
    "evals/run_evals.py",          # in the tree, but not a document
])
def test_a_citation_that_is_not_a_readable_document_is_blocked(repo, ruling):
    """Same rule as the admission register's, and literally the same code —
    `ruling_paths` owns it, so the absolute-path bypass security-reviewer found
    at M07 M1 cannot come back in only one of the two callers."""
    b = base(repo)
    commit(repo, f"edit ground truth\n\nRULING: {ruling}\n",
           {"evals/golden_questions.json": golden()})
    code, out = evaluate(b, "HEAD", repo)
    assert code == 1
    assert "BLOCKED" in "\n".join(out)


def test_a_ruling_that_does_not_name_the_file_is_not_a_ruling(repo):
    """THE README.md HOLE. Until `ruling_covers` landed, the gate checked that
    a citation was a well-formed Markdown path present on main — so
    `RULING: README.md` satisfied it for any change. Every test in this file
    passed while that was open; it was found by attacking the rule
    (milestones/M07/ground_truth_gate_mutations.py), not by describing it.

    Read at the BASE commit, so the string cannot be added to some existing
    document in the pull request being gated — the self-certifying hole one
    level down."""
    commit(repo, "a document about something else",
           {"docs/unrelated.md": "# notes\n\nnothing to do with scoring.\n"})
    b = base(repo)
    commit(repo, "edit ground truth\n\nRULING: docs/unrelated.md\n",
           {"evals/golden_questions.json": golden()})
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 1
    assert "no cited ruling on main names it" in text
    assert "citation-shaped hole" in text


def test_a_ruling_covering_one_path_does_not_carry_another_in(repo):
    """Per-path, not in aggregate. A ruling about the golden set must not
    authorise an unrelated edit to the register riding along in the same PR."""
    commit(repo, "a ruling about the golden set only",
           {RULING: "# ruling\n\nCovers evals/golden_questions.json.\n"})
    b = base(repo)
    commit(repo, f"two files, one ruling\n\nRULING: {RULING}\n",
           {"evals/golden_questions.json": golden(),
            "evals/admitted_false_fails.json": register(RULING)})
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 1
    assert "evals/admitted_false_fails.json — no cited ruling on main names it" in text
    assert "    evals/golden_questions.json" in text
    assert "ruled by " + RULING in text


def test_a_second_commit_cannot_ride_in_on_the_first_ones_ruling(repo):
    """Two commits: one properly ruled, one touching a DIFFERENT owned path and
    citing a ruling that does not exist. A check that stopped at the first
    satisfied citation would let the second file through.

    This is per-path coverage doing its job. The bogus citation is also
    reported, so a reader sees why it did not help."""
    commit(repo, "a ruling about the golden set only",
           {RULING: "# ruling\n\nCovers evals/golden_questions.json.\n"})
    b = base(repo)
    commit(repo, f"first\n\nRULING: {RULING}\n",
           {"evals/golden_questions.json": golden()})
    commit(repo, "second\n\nRULING: milestones/M07/invented.md\n",
           {"evals/scenarios.json": "[]\n"})
    code, out = evaluate(b, "HEAD", repo)
    text = "\n".join(out)
    assert code == 1
    assert "evals/scenarios.json — no cited ruling on main names it" in text
    assert "invented.md" in text


# --------------------------------------------------------------------------
# The register cites in its own shape
# --------------------------------------------------------------------------

def register(ruling):
    return json.dumps({"admissions": [{
        "question": "q03", "sha": "1f46b92", "scored_sha256": "0" * 64,
        "admits_fails": ["x"], "ruling": ruling, "ruled_at": "2026-08-21",
        "why": ["synthetic"]}]})


def test_a_register_entry_carries_its_own_citation(repo):
    """No trailer needed: the entry's `ruling` field is the citation."""
    commit(repo, "the SME ruling", {RULING: RULING_BODY})
    b = base(repo)
    commit(repo, "admit one observation",
           {"evals/admitted_false_fails.json": register(RULING)})
    code, out = evaluate(b, "HEAD", repo)
    assert code == 0, "\n".join(out)


def test_a_register_entry_cannot_be_born_with_its_justification(repo):
    """security-reviewer M07 M2, closed here rather than only recorded: "one PR
    can add both the admission entry AND the ruling document it cites, and the
    entry becomes usable in the same commit that introduces it"."""
    b = base(repo)
    commit(repo, "admit one observation",
           {"evals/admitted_false_fails.json": register(RULING),
            RULING: RULING_BODY})
    code, out = evaluate(b, "HEAD", repo)
    assert code == 1
    assert "not present on the base commit" in "\n".join(out)


def test_an_unparseable_register_does_not_pass_by_accident(repo):
    """A JSON error must not read as "no entries, therefore nothing to check".
    Failing open on a malformed override file is the worst available outcome."""
    b = base(repo)
    commit(repo, "break it", {"evals/admitted_false_fails.json": "{not json"})
    code, out = evaluate(b, "HEAD", repo)
    assert code == 1
    assert "BLOCKED: no ruling cited." in "\n".join(out)
