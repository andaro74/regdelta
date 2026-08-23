"""SPEC/08 Scope 5 — the L3 suite's pre-registered literals, pinned.

WHAT THIS CATCHES, EXACTLY: **deletion** of a pre-registered literal from a
spec file Playwright actually executes, plus a short list of named mutations
that would otherwise leave every check green while destroying the property.

It does NOT catch every assertion weakened while its literal survives — a
literal parked in a comment satisfies the presence checks, and `hit`, `miss`,
`aoss` and `#i-cache` are short enough to appear incidentally. An earlier draft
of SPEC/08 claimed this test makes "weakening an assertion a red `unit` job",
which is more than a presence test can see. Two instruments, two failure modes,
neither pretending to be the other: this one catches the deletion and the named
mutations, and SPEC/08 Done-when 6's verbatim README quotation plus the
spec-amendment rule are what stand against the rest.

WHY IT EXISTS AT ALL. SPEC/08's exit criterion is deliberately not "the suite
is green" — a criterion an author satisfies by editing the assertion. That
decoupling only removes the incentive to loosen if the assertions are a fixed
subject, and this file is the mechanical half of making them one.

THE LIST BELOW HAS BEEN THE DEFECT IT PREVENTS THREE TIMES, all three during
the drafting of SPEC/08 and all three caught by `pm-spec-reviewer` rather than
by the author. **When an assertion is added to Spec 1 or Spec 2, its literals
are added here in the same diff.**

AND THE FIRST IMPLEMENTATION OF THIS FILE WAS ITSELF THE DEFECT, twice over.
`eng-code-reviewer` named five one-line mutations that survived it:

  · rename `needs-review.spec.ts` -> `needs-review.ts` and set `--questions 1`.
    Playwright stops collecting the file, `make ui-tests` exits 0, the card
    reads 1/1 PASS and M08's only finding disappears — because `_suite_text()`
    globbed `*.ts` where the runner globs `*.spec.ts`. Fixed by reading only
    what runs, and by pinning the filenames.
  · `{${length}}` -> `{${length + 1}}` in the token pattern, or
    `walk(document.head)`, or `return []`. The old guard looked for a LITERAL
    `[A-Za-z0-9_-]{43}`, which the interpolated form never contains, so it was
    vacuous on the shipped code. Fixed by recomputing the derivation here and
    driving it against a real minted token — the positive control it had none.
  · `await page.locator("#bypass").check()` before the click. Doubles the Opus
    spend per run against a NON-ADJUSTABLE cap and stays green, because
    `bypass` is a legal cache state. SPEC/08 calls "never ticked" a ruling and
    it had no instrument.
  · reorder Spec 2's negatives above its positives. Deletes no literal, so
    every pin passed, and the negatives then evaluate against an empty
    `#result` and pass vacuously — the single mutation that would have turned
    M08's genuine red into a green.
"""
import hashlib
import re
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
UI_TESTS = ROOT / "ui-tests"
SPECS = UI_TESTS / "tests"

# The spec files SPEC/08 pre-registers. Pinned by name because Playwright's
# default testMatch collects `*.spec.ts` and nothing else: a rename is a
# one-line edit that stops a spec running while leaving its text in the tree.
EXPECTED_SPECS = {"healthy-claim.spec.ts", "needs-review.spec.ts"}


def spec_files() -> list[Path]:
    return sorted(SPECS.glob("*.spec.ts"))


def _suite_text() -> str:
    """Only the files Playwright EXECUTES.

    Not `*.ts`. A literal that lives in a helper, a comment or an unreferenced
    file is not an assertion, and a pin that accepts one is a pin that a rename
    walks straight past.
    """
    files = spec_files()
    assert files, f"no *.spec.ts under {SPECS} — the L3 suite would run nothing"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def _helper_text() -> str:
    return (SPECS / "_page.ts").read_text(encoding="utf-8")


# Every literal SPEC/08 pre-registers, with the clause it implements. The
# second element is what a failure message says, so a red run names the spec
# clause rather than only the string.
PINNED = [
    ("2028-02-25", "Spec 1: every td.deadline reads the q01 compliance date"),
    ("89 FR 106064", "Spec 1: the 'healthy' final rule is cited"),
    ("90 FR 10592", "Spec 1: the delay document is cited"),
    ("td.deadline", "Spec 1 and Spec 2: the deadline cell, asserted and refused"),
    ('not.toBe("—")', "Spec 1: no verdict cell renders the em dash (U+2014)"),
    ("no confidence", "Spec 1: no verdict row's confidence cell reads 'no confidence'"),
    ("a verdict row carries no citation",
     "Spec 1: the uncited-row banner is absent"),
    ("#i-tier", "Spec 1: the tier that answered"),
    ("#i-cache", "Spec 1: the response cache label"),
    ("#configured-tier", "Spec 1: /health answered through the /api/* proxy"),
    ("aoss", "Spec 1: a real tier value"),
    ("s3vectors", "Spec 1: a real tier value"),
    ("hit", "Spec 1: SPEC/04's cache contract"),
    ("miss", "Spec 1: SPEC/04's cache contract"),
    ("bypass", "Spec 1: SPEC/04's cache contract"),
    ("disabled", "Spec 1: SPEC/04's cache contract"),
    ("NEEDS HUMAN REVIEW", "Spec 2: the pause renders"),
    ("resume capability was minted",
     "Spec 2: the token reached the browser and was withheld"),
    ("tokenLikeNodes", "Spec 2: the serialized DOM is scanned for the capability"),
]


@pytest.mark.parametrize("literal,clause", PINNED, ids=[p[0] for p in PINNED])
def test_the_pre_registered_literal_is_still_in_the_suite(literal, clause):
    assert literal in _suite_text(), (
        f"{literal!r} is no longer in any executed spec. It implements — {clause}. "
        "SPEC/08 pre-registers it; removing it is a spec amendment through "
        "pm-spec-reviewer, not a test edit.")


def test_both_pre_registered_specs_are_still_collected():
    """A rename is the cheapest way to delete a finding.

    `needs-review.spec.ts` -> `needs-review.ts` leaves every byte of the file in
    the tree, stops Playwright collecting it, and takes M08's only finding with
    it. `eng-code-reviewer` H5.
    """
    found = {p.name for p in spec_files()}
    assert found == EXPECTED_SPECS, (
        f"the collected spec files are {sorted(found)}, not {sorted(EXPECTED_SPECS)}. "
        "A spec Playwright does not collect is a spec that does not run.")


# ------------------------------------------------------- the token derivation
def _token_length(nbytes: int) -> int:
    """base64url of n bytes, padding stripped. The helper's own arithmetic."""
    return -(-nbytes * 4 // 3)


def _derived_pattern() -> re.Pattern:
    sys.path.insert(0, str(ROOT / "src"))
    from api import resume_token

    n = resume_token._TOKEN_BYTES
    return re.compile(
        rf"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{{{_token_length(n)}}}(?![A-Za-z0-9_-])")


def test_the_derived_pattern_matches_a_real_minted_token():
    """THE POSITIVE CONTROL, which this file had none of.

    The old check asserted that the string `_TOKEN_BYTES` appeared somewhere in
    the suite — which it does in a comment, independently of the pattern — and
    that no LITERAL `[A-Za-z0-9_-]{43}` appeared, which an interpolated
    `{${length}}` never contains. So `{${length + 1}}` was a one-line edit that
    disabled the only security assertion in the milestone with every check
    green. `eng-code-reviewer` H6.

    This drives the derivation against a token the real minting function
    produced, which is the only thing that can tell "derived correctly" from
    "derived".
    """
    sys.path.insert(0, str(ROOT / "src"))
    from api import resume_token

    pattern = _derived_pattern()
    for _ in range(50):
        token, _digest = resume_token.mint()
        assert pattern.search(token), (
            f"the derived pattern does not match a token this repo actually "
            f"mints (length {len(token)}, _TOKEN_BYTES={resume_token._TOKEN_BYTES}). "
            "The scan in ui-tests/tests/_page.ts would never fire.")


def test_the_derived_pattern_ignores_what_the_page_legitimately_renders():
    """THE NEGATIVE CONTROL. A pattern that matches everything is not a scan.

    The page renders a uuid4 thread id and, elsewhere, sha256 hex digests. Both
    are drawn from a subset of the token's alphabet and neither is a capability.
    """
    pattern = _derived_pattern()
    for _ in range(50):
        assert not pattern.search(str(uuid.uuid4())), "a uuid4 thread id matches"
    assert not pattern.search(hashlib.sha256(b"x").hexdigest()), "a sha256 digest matches"
    assert not pattern.search(secrets.token_urlsafe(8)), "a short random string matches"


def test_the_suite_derives_the_pattern_rather_than_transcribing_it():
    text = _helper_text()
    assert "_TOKEN_BYTES" in text, (
        "the resume-token pattern no longer reads _TOKEN_BYTES from "
        "src/api/resume_token.py. SPEC/08 requires it derived, not transcribed.")
    hardcoded = re.findall(r"\[A-Za-z0-9_-\]\{\d+\}", text)
    assert not hardcoded, (
        f"the token pattern carries a hardcoded length {hardcoded} instead of "
        "deriving it from _TOKEN_BYTES.")


def test_the_scan_reads_the_serialized_dom_and_not_the_pages_own_javascript():
    """`security-reviewer` M1.

    `page.evaluate` compiles and runs in the page's main world, where `RegExp`,
    `Node` and `Element.prototype.attributes` are all overridable — so the page
    under inspection could return `[]` from the one security assertion in this
    suite. `page.content()` is scanned in Node and is not forgeable by the page.
    """
    text = _helper_text()
    scan = text.split("export async function tokenLikeNodes", 1)
    assert len(scan) == 2, "tokenLikeNodes is gone"
    body = scan[1]
    assert "page.content()" in body, (
        "the capability scan no longer reads the serialized DOM in Node.")
    assert "page.evaluate" not in body, (
        "the capability scan runs inside the page's own JavaScript context, where "
        "the page it is inspecting can forge its result.")


def test_the_scan_never_prints_the_capability_it_finds():
    """`security-reviewer` H1.

    The first version redacted the match and printed `outerHTML` beside it,
    which contains the match in full — and `record_verdict.py` copies failure
    messages verbatim into a COMMITTED card. The day the assertion caught a real
    leak it would have committed the token.
    """
    body = _helper_text().split("export async function tokenLikeNodes", 1)[1]
    assert "redact" in body, "the capability scan no longer redacts what it reports"
    assert "outerHTML" not in body, (
        "the scan reports outerHTML, which contains the matched token in full.")
    assert body.count("redact") >= 2, (
        "only one field is redacted; the match and its surrounding window both "
        "have to be.")


# --------------------------------------------------------------- cost control
def test_no_spec_ticks_the_bypass_box():
    """SPEC/08's cost posture calls this a ruling, and it had no instrument.

    One added line — `await page.locator("#bypass").check();` — doubles the Opus
    spend per execution against a NON-ADJUSTABLE daily cap, and the suite stays
    green: `bypass` is a legal cache state, so the contract assertion accepts it
    and the card records it as an ordinary observation. `eng-code-reviewer` M7.
    """
    text = "\n".join(f.read_text(encoding="utf-8") for f in sorted(SPECS.glob("*.ts")))
    stripped = re.sub(r"//.*|/\*[\s\S]*?\*/", "", text)
    assert not re.search(r"#bypass\"\s*\)\s*\.check\(", stripped), \
        "a spec ticks the bypass checkbox"
    assert not re.search(r"\.check\(\)", stripped), \
        "a spec calls .check() on a checkbox; the only checkbox on the page is #bypass"
    assert '"no_cache"' not in stripped and "bypass=1" not in stripped, \
        "a spec asks the page to bypass the response cache"
    # And each spec still asserts the box is untouched before it clicks.
    for f in spec_files():
        assert "not.toBeChecked()" in f.read_text(encoding="utf-8"), \
            f"{f.name} does not assert the bypass box is unticked before asking"


def test_the_headroom_guard_declares_the_number_of_specs():
    """`make ui-tests` pre-pays for what it is about to spend.

    Same reasoning the Makefile already states for `make smoke` and
    `make evals`: the count is declared rather than derived, so that adding a
    spec shows up as a diff here instead of silently under-declaring against a
    NON-ADJUSTABLE daily Opus cap.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nui-tests:", 1)
    assert len(recipe) == 2, "the Makefile has no ui-tests target"
    body = recipe[1].split("\n\n", 1)[0]
    found = re.search(r"--questions\s+(\d+)", body)
    assert found, "make ui-tests does not check Opus headroom before spending it"
    assert int(found.group(1)) == len(spec_files()), (
        f"make ui-tests declares --questions {found.group(1)} but ui-tests/tests "
        f"holds {len(spec_files())} specs, each able to spend an uncached graph run.")


# ------------------------------------------------------------- the assertions
def test_spec_2_still_asserts_its_positives_before_its_negatives():
    """SPEC/08 M7's ordering, which the spec calls load-bearing.

    Moving the negatives above the positives deletes no literal, so every pin
    above passes — and the negatives then evaluate against an empty `#result`,
    pass vacuously, and today's genuine red run reports green. It is the single
    mutation that would have erased this milestone's only finding.
    `eng-code-reviewer` M8.
    """
    text = (SPECS / "needs-review.spec.ts").read_text(encoding="utf-8")
    body = text.split("test(", 1)[1]
    pause = body.index("toContainText(PAUSE)")
    minted = body.index("toContainText(MINTED)")
    deadline = body.index("toHaveCount(0")
    scan = body.index("tokenLikeNodes(page")
    assert pause < minted < deadline, (
        "Spec 2's negatives no longer run after its positives; against an empty "
        "#result they are true by construction.")
    assert minted < scan, "the capability scan runs before the page has answered"


def test_the_capability_scan_cannot_be_masked_by_the_deadline_failure():
    """`eng-code-reviewer` H2, `security-reviewer` H3.

    A hard `await expect(...).toHaveCount(0)` on a violated negative polls for
    the full expect timeout and throws, so everything after it is dead code —
    which is why M08's first run reported a token scan that never executed, and
    why the capability check sat behind a known-failing product assertion.
    `expect.soft` keeps the red and lets the scan run.
    """
    text = (SPECS / "needs-review.spec.ts").read_text(encoding="utf-8")
    assert "expect.soft(" in text, (
        "the deadline negative is a hard assertion again; when it fails it masks "
        "the capability scan below it.")
    soft = text.split("expect.soft(", 1)[1].split(";", 1)[0]
    assert "timeout:" in soft, (
        "the deadline negative has no explicit timeout, so a violated negative "
        "polls for the whole expect window and blows the test timeout.")


def test_the_suite_has_no_skip_path():
    """SPEC/08 Done-when 2: it fails closed.

    `ui_dom_spec.js` exits 64 for "no chrome found" and the pytest wrapper
    turns that into a SKIP, which is right there because chrome is not a
    declared dependency. Here Chromium IS one, and a skip would be a green
    check for a thing that did not run — which is what `fail_closed: true` on
    the recorded card asserts.

    `describe.skip` and `test.fail` are matched too: neither fools the recorder
    (the card stays honest) but both make `make ui-tests` exit 0, and nothing
    compares the suite's exit code to the card.
    """
    text = "\n".join(f.read_text(encoding="utf-8") for f in sorted(SPECS.glob("*.ts")))
    stripped = re.sub(r"//.*|/\*[\s\S]*?\*/", "", text)
    bad = re.findall(r"\btest\.(?:describe\.)?(?:skip|fixme|fail)\b|\bfixme:\s*true",
                     stripped)
    assert not bad, f"the L3 suite can skip or expect-fail itself: {bad}"


def test_the_suite_cannot_retry_its_way_to_green():
    """SPEC/08's ruling: a red result closes the milestone red.

    A retry is that ruling loosened, spelled as a config value instead of as an
    edited assertion — and it spends a second uncached graph run to do it.
    """
    config = (UI_TESTS / "playwright.config.ts").read_text(encoding="utf-8")
    assert re.search(r"\bretries:\s*0\b", config), (
        "playwright.config.ts no longer sets retries: 0. SPEC/08 records the "
        "failure as the finding; a retry is the loosening it forbids.")


# ---------------------------------------------------------------- the recorder
def test_the_recorder_refuses_a_dirty_tree_and_supersedes():
    """SPEC/08 Scope 3, the two properties that make the card evidence.

    Pinned by NAME here; the BEHAVIOUR is driven in
    `tests/test_ui_record_verdict.py`, which is what Done-when 3's "checkable by
    recording two runs at one sha and reading the trail" actually asks for.
    """
    src = (UI_TESTS / "record_verdict.py").read_text(encoding="utf-8")
    assert "git_dirty" in src, "the recorder no longer checks for a dirty tree"
    assert "allow_dirty" in src, "the recorder lost its provisional escape hatch"
    assert "_peek_trail" in src and "_archive" in src, (
        "the recorder no longer supersedes: a second run at one sha would write "
        "over the first, and re-running until green would leave no trace — which "
        "is exactly what SPEC/08's headline ruling forbids.")


def test_the_card_is_inert_to_the_golden_set_tooling():
    """SPEC/08 Done-when 4.

    `evals/replay_history.py` globs `history/*.json` and treats any card with a
    `questions` key as a golden-set card. This card is not a golden run, gates
    nothing in `unit`, and must not appear in a pass-rate history — so its
    per-item array is `specs`.
    """
    src = (UI_TESTS / "record_verdict.py").read_text(encoding="utf-8")
    assert '"specs"' in src, "the per-spec array is no longer named `specs`"
    assert '"questions"' not in src, (
        "the card carries a `questions` key, which makes replay_history.py read "
        "it as a golden-set card with no answers in it.")


def test_no_committed_artifact_carries_a_token_shaped_string():
    """The last line of defence, over what is actually in the tree.

    Everything above reasons about what the suite would do. This looks at what
    git is tracking: the recorded cards, the milestone write-up and the suite
    itself. `security-reviewer` H1/H2 — the traces are gitignored, and this is
    what says so was enough.
    """
    pattern = _derived_pattern()
    tracked = subprocess.check_output(
        ["git", "ls-files", "evals/history", "milestones/M08", "ui-tests"],
        text=True, cwd=str(ROOT)).split()
    scanned = 0
    for name in tracked:
        path = ROOT / name
        if not path.is_file() or path.suffix in (".png", ".zip", ".ico"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        hit = pattern.search(text)
        assert not hit, (
            f"{name} contains a {len(hit.group(0))}-character string shaped like a "
            "resume token. If it is one, a bearer capability is committed to this "
            "repository.")
    # A scan that scanned nothing proves nothing — the same guard the rest of
    # this file applies to the suite, applied to this test.
    assert scanned, "no tracked files were scanned; this check measured nothing"
