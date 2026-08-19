"""The demo page (SPEC/04 Phase 3): its judgement, and its wiring.

TWO KINDS OF CHECK, and the split is deliberate.

`tests/ui_verdict_spec.js` runs `ui/verdict.js` under node and asserts the
panel's DECISIONS — citation URLs, which responses may become a tier
observation, the equal/differs verdict and its caveats. That file is where the
substance is; this one runs it and reports what it said.

The rest here is wiring: that the page loads the judgement it is tested on,
that the scenario buttons come from `evals/scenarios.json` rather than a
transcription of it, and that the internal review prose in that file does not
get published to an anonymous CloudFront distribution.

WHAT IS NOT TESTED HERE. The rendering. There is no DOM in this suite and
adding one would mean a dependency; asserting that a `<td>` exists would pin
the template rather than the behaviour, which is the shape of test this
milestone has already found green in a clean checkout. The rendering's evidence
is a screenshot of the deployed page taken against the deployed stack and
recorded in `milestones/M04/` — SPEC/04: "a browser procedure with no record is
rehearsal, not a criterion."

NODE IS NOT AN ADDED DEPENDENCY. `import aws_cdk` already starts a node child
process, and CI installs `aws-cdk-lib` for the infra tests, so every
environment that runs the suite today has it.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
UI = ROOT / "ui"
SCENARIOS = ROOT / "evals" / "scenarios.json"


# ------------------------------------------------------------ the judgement
def test_the_panels_judgement_holds_up():
    """Runs tests/ui_verdict_spec.js. Its output is this test's message."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH (aws_cdk needs it too, so this is unusual)")
    r = subprocess.run([node, str(Path(__file__).parent / "ui_verdict_spec.js")],
                       capture_output=True, text=True, cwd=str(ROOT))
    sys.stdout.write(r.stdout)
    assert r.returncode == 0, "ui/verdict.js failed its spec:\n" + r.stdout + r.stderr


def test_both_ui_files_parse():
    """A syntax error in the page is a blank demo, and nothing else would say so.

    `ruff check` covers `src evals infra tests`; nothing in this repo looks at
    JavaScript at all, so without this a stray brace ships to CloudFront.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                        (UI / "index.html").read_text(encoding="utf-8"), re.DOTALL)
    assert len(inline) == 1, f"expected one inline <script>, found {len(inline)}"

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.js"
        page.write_text(inline[0], encoding="utf-8")
        for target in (UI / "verdict.js", page):
            r = subprocess.run([node, "--check", str(target)],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"{target.name} does not parse:\n{r.stderr}"


def test_the_page_uses_the_judgement_it_is_tested_on():
    """The extracted logic must be the logic the page runs.

    A tested `verdict.js` beside a page that kept its own copy would be a test
    suite pinning a function the demo never calls — this milestone's defect
    class wearing a green check. So: the page loads the file, and the two
    decisions with their own spec are reached through it.
    """
    page = (UI / "index.html").read_text(encoding="utf-8")
    assert '<script src="verdict.js"></script>' in page
    for call in ("V.observationFrom(", "V.compareObservations(", "V.citationUrl("):
        assert call in page, f"the page does not call {call}"
    # And it does not carry a second copy under the same names.
    for redefined in ("function observationFrom", "function compareObservations",
                      "function citationUrl"):
        assert redefined not in page, f"the page redefines {redefined}"


# ------------------------------------------------------------- the scenarios
def _public():
    sys.path.insert(0, str(ROOT / "infra"))
    from core.core_stack import _public_scenarios

    return json.loads(_public_scenarios())


def test_one_button_per_entry_in_the_canonical_file():
    """SPEC/04: "one canned-scenario button per entry in evals/scenarios.json".

    The page fetches `scenarios.json` from its own bucket, and the stack writes
    that object from the canonical file at synth. This pins the two together:
    add, remove or reword a scenario and the demo follows it on the next deploy
    with no second edit — which is the whole reason `evals/scenarios.json`
    exists rather than the list living in prose.
    """
    source = json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]
    published = _public()["scenarios"]
    assert [s["id"] for s in published] == [s["id"] for s in source]
    assert [s["question"] for s in published] == [s["question"] for s in source]
    assert [s.get("company_profile", {}) for s in published] \
        == [s.get("company_profile", {}) for s in source]


def test_the_needs_review_scenario_keeps_its_empty_profile():
    """`needs-review` is the ONLY scenario that produces SPEC/04's "needs human
    review" state, and it does so because its profile is empty. A projection
    that dropped an empty dict would silently delete the state from the demo."""
    published = {s["id"]: s for s in _public()["scenarios"]}
    assert published["needs-review"]["company_profile"] == {}


def test_the_review_prose_is_not_published_to_an_anonymous_distribution():
    """`evals/scenarios.json` carries the PM- and SME-seat argument for each
    scenario — `_meta`, `demonstrates`, `grounded_in`, `note`. The UI bucket is
    served by CloudFront to anyone; the demo needs none of it."""
    published = _public()
    assert "_meta" not in published
    blob = json.dumps(published)
    for leaked in ("demonstrates", "grounded_in", "count_was_contested",
                   "grounding_rule", "must not be 'fixed'"):
        assert leaked not in blob, f"published internal field/prose: {leaked}"


def test_an_empty_scenario_file_fails_the_synth_rather_than_the_demo(tmp_path):
    """A page with no buttons still renders, and "one button per entry" is then
    satisfied by a file with no entries — green by construction, which is the
    shape this milestone has found four times. It raises instead."""
    sys.path.insert(0, str(ROOT / "infra"))
    from core import core_stack

    empty = tmp_path / "scenarios.json"
    empty.write_text('{"scenarios": []}', encoding="utf-8")
    original = core_stack.SCENARIOS_SRC
    core_stack.SCENARIOS_SRC = empty
    try:
        with pytest.raises(ValueError, match="no scenarios"):
            core_stack._public_scenarios()
    finally:
        core_stack.SCENARIOS_SRC = original
