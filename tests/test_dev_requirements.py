"""The dev environment must be able to RUN the tests that gate merges.

`tests/test_search_stack_access.py` opens with `pytest.importorskip("aws_cdk")`,
which is right — someone without the infra dependencies should still be able to
run the suite. But it means a missing dependency turns twenty tests off and says
`1 skipped` about it, and CI reported that for the whole life of the file: 713
tests there against 733 locally.

A red test says something. A silent skip says nothing, and what was not running
was the AOSS data-access policy — the whole of AOSS authorization — plus the two
tests written at M04 after the reindex Lambda shipped an asset with no source in
it and a leaked `.env`.

So this asserts the DECLARATION rather than the environment: these tests run
without aws_cdk installed, and they fail if the pin that makes CI install it
disappears. Checking the declaration is the part that can be checked from
anywhere; checking the environment is what `importorskip` already does.
"""
import importlib.util
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DEV = ROOT / "requirements-dev.txt"
INFRA = ROOT / "infra" / "requirements.txt"

# `name==1.2.3` or `name>=1.2.3`, ignoring comments and blank lines.
_REQ = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(==|>=)\s*([0-9][0-9A-Za-z.]*)\s*$")


def pins(path: Path) -> dict[str, tuple[str, str]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if (m := _REQ.match(line)):
            out[m.group(1).lower()] = (m.group(2), m.group(3))
    return out


def version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".") if p.isdigit())


# DERIVED from infra/requirements.txt, not written out here. A hardcoded
# ["aws-cdk-lib", "constructs"] reproduces this defect exactly the next time an
# infra test needs a third package — both tests green, the module skipping
# again. security-reviewer L2.
@pytest.mark.parametrize("package", sorted(pins(INFRA)))
def test_ci_installs_what_the_infra_tests_need(package):
    """Without these, tests/test_search_stack_access.py skips in CI.

    That file holds the AOSS data access policy tests and the asset-allowlist
    tests. A deploy-breaking or credential-leaking regression in
    infra/search/search_stack.py would pass CI with them skipped, which is how
    the M04 asset defect reached a real deploy.
    """
    assert package in pins(DEV), (
        f"{package} is required by infra/requirements.txt but is not pinned in "
        "requirements-dev.txt, so the eval gate's unit job will not install it "
        "and the infra tests will silently skip")


@pytest.mark.skipif(not os.environ.get("CI"),
                    reason="asserts the CI environment, not a laptop's")
def test_ci_can_actually_import_aws_cdk():
    """The declaration is one hop from the mechanism; this asserts the mechanism.

    Everything else in this file reads requirements-dev.txt. What actually
    installs anything is .github/workflows/evals.yml — so changing that line to
    `pip install -r requirements.txt`, or adding `--no-deps`, leaves every
    assertion above green while the twenty infra tests silently skip again: the
    same defect, moved upstream by one file. security-reviewer M2.

    Guarded on CI rather than asserted everywhere, because a laptop without the
    infra dependencies must still be able to run the suite — which is why
    test_search_stack_access.py uses importorskip in the first place. This also
    catches the one failure `importorskip` swallows: a package that installs
    but does not import.
    """
    assert importlib.util.find_spec("aws_cdk") is not None, (
        "aws_cdk is not importable in CI, so tests/test_search_stack_access.py "
        "is skipping there — check the install step in .github/workflows/evals.yml")


def test_the_dev_pin_is_not_below_the_deploy_floor():
    """One-directional, and only that. Named precisely because the first
    version of this docstring claimed more.

    It stops the TEST pin dropping below the floor infra/requirements.txt
    declares. It does not make CI and a deploy use one version: that floor
    admits every release from 2.230.0 up, and a deploy in fact runs whatever
    CDK is in the operator's venv, which no file in this repo constrains. If
    asset-staging semantics across versions ever matter enough to need that
    guarantee, the instrument is raising the floor, not this test.
    security-reviewer L6.
    """
    dev, infra = pins(DEV), pins(INFRA)
    for package, (_, floor) in infra.items():
        if package not in dev:
            continue
        assert version(dev[package][1]) >= version(floor), (
            f"requirements-dev.txt pins {package}=={dev[package][1]} but "
            f"infra/requirements.txt requires >={floor}: CI would test against "
            "an older CDK than a deploy is allowed to use")
