"""Can Door 1's gate be made to let a ground-truth edit through?

The gate's whole value is one property: a ruling cited by a pull request must
already be on `main`, so the change cannot justify itself. Thirteen passing
tests do not establish that — the tests were written by the gate's author,
which is the 2026-08-15 failure this repo has now committed twice
(milestones/M05/q03-ruling.md §10).

So this attacks the RULE rather than the code: each case is a way someone might
try to land a ground-truth edit, run end to end against a real throwaway git
repository, asserting the gate still refuses. Two cases must be ALLOWED, and
they are the ones that stop "refuse everything" scoring a clean sheet here.

No API, no AWS, no cost, no network.

    python milestones/M07/ground_truth_gate_mutations.py
"""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "evals"))
from check_ground_truth_ruling import evaluate            # noqa: E402

RULING = "milestones/M07/q03-rulings.md"
GOLDEN = json.dumps({"questions": [{"id": "q01", "must_contain": ["x"]}]})


def git(repo, *args):
    return subprocess.run(("git", *args), cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def commit(repo, message, files):
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        git(repo, "add", name)
    git(repo, "commit", "-m", message)


def fresh(ruling_on_main):
    """A repo whose main may or may not already carry the ruling."""
    repo = pathlib.Path(tempfile.mkdtemp())
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")
    files = {"README.md": "base\n"}
    if ruling_on_main:
        # THE RULING NAMES WHAT IT RULES ON. The first version of this fixture
        # wrote "# the seat's ruling" and nothing else, which is why the
        # README.md survivor below was reachable: the gate checked the shape of
        # a citation and never its subject. A ruling that names no file is a
        # citation-shaped hole.
        files[RULING] = (
            "# the seat's ruling\n\n"
            "Covers evals/golden_questions.json, "
            "evals/admitted_false_fails.json and evals/scenarios.json.\n")
    commit(repo, "base", files)
    return repo, git(repo, "rev-parse", "HEAD").strip()


def entry(ruling):
    return json.dumps({"admissions": [{
        "question": "q03", "sha": "1f46b92", "scored_sha256": "0" * 64,
        "admits_fails": ["x"], "ruling": ruling, "ruled_at": "2026-08-21",
        "why": ["synthetic"]}]})


# label -> (ruling already on main?, commits, must the gate BLOCK?)
CASES = [
    ("edit ground truth, cite nothing — Door 1 as filmed",
     False, [("green the build", {"evals/golden_questions.json": GOLDEN})], True),

    ("write the ruling in the same commit as the change",
     False, [(f"edit\n\nRULING: {RULING}\n",
              {"evals/golden_questions.json": GOLDEN, RULING: "# ruling\n"})], True),

    ("write the ruling in an EARLIER commit of the SAME branch",
     False, [("the ruling", {RULING: "# ruling\n"}),
             (f"edit\n\nRULING: {RULING}\n",
              {"evals/golden_questions.json": GOLDEN})], True),

    ("cite a ruling that was never written at all",
     False, [(f"edit\n\nRULING: {RULING}\n",
              {"evals/golden_questions.json": GOLDEN})], True),

    ("cite a real file on main that is not a document",
     True, [("edit\n\nRULING: README.md\n",
             {"evals/golden_questions.json": GOLDEN})], True),

    ("cite an absolute path outside the repo",
     True, [("edit\n\nRULING: /etc/passwd\n",
             {"evals/golden_questions.json": GOLDEN})], True),

    ("traverse out of the repo and back to something that exists",
     True, [("edit\n\nRULING: ../../../etc/hostname\n",
             {"evals/golden_questions.json": GOLDEN})], True),

    ("hide the edit behind a second, properly-ruled commit",
     True, [(f"legit\n\nRULING: {RULING}\n", {"src/thing.py": "x = 1\n"}),
            ("sneak the edit in", {"evals/golden_questions.json": GOLDEN})], False),

    ("a register entry citing a ruling written in the same PR (M2)",
     False, [("admit one", {"evals/admitted_false_fails.json": entry(RULING),
                            RULING: "# ruling\n"})], True),

    ("corrupt the register so it parses as 'no entries'",
     True, [("break it", {"evals/admitted_false_fails.json": "{not json"})], True),

    ("change scenarios.json — product scope, same treatment",
     False, [("reword a demo question", {"evals/scenarios.json": "[]\n"})], True),

    # ---- MUST BE ALLOWED. Without these, a gate that refused everything would
    # score a clean sheet above and be worse than useless.
    ("the intended two-PR flow: ruling on main first",
     True, [(f"apply\n\nRULING: {RULING}\n",
             {"evals/golden_questions.json": GOLDEN})], False),

    ("an ordinary change touching nothing SME-owned",
     False, [("refactor", {"src/thing.py": "x = 1\n"})], False),
]

print(f"{'attempt':62} {'want':7} {'got':7} ")
print("-" * 88)
survivors = []
for label, on_main, commits, must_block in CASES:
    repo, base = fresh(on_main)
    try:
        for message, files in commits:
            commit(repo, message, files)
        code, out = evaluate(base, "HEAD", repo)
    finally:
        pass
    blocked = code != 0
    ok = blocked == must_block
    survivors += [] if ok else [label]
    print(f"{label:62} {('BLOCK' if must_block else 'allow'):7} "
          f"{('BLOCK' if blocked else 'allow'):7} {'' if ok else '<-- SURVIVOR'}")

print()
print(f"{len(survivors)} survivor(s) out of {len(CASES)}"
      f"{': ' + '; '.join(survivors) if survivors else ''}")
sys.exit(1 if survivors else 0)
