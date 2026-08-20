"""What the PERSISTENT stack's Lambdas ship.

`regdelta-core` had no test coverage at all until M04 — not one test under
tests/ referenced it — while `regdelta-search` had eleven. That asymmetry is
backwards: core is the stack that stays up, and its functions hold the query
path, the poller and the processor.

What the gap hid: all three shipped `Code.from_asset("../src")` with no filter,
staging 75 files of which 39 were not Python (`.pytest_cache/`, every
`__pycache__/*.pyc`). A Lambda code zip is retrievable by anyone holding
`lambda:GetFunction` — it returns a presigned URL to the artifact — so what
ships is a disclosure question. The same allowlist had been fixed on the search
stack a day earlier and was not carried across, because nothing here would have
noticed.

These mirror tests/test_search_stack_access.py's asset tests deliberately: the
same property, asserted the same way, against the stack that was missing it.
"""
import contextlib
import sys
import tempfile
from pathlib import Path

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))

# The dependency layer is a BUILD ARTIFACT (`make layer`, ~101MB) and is not
# committed, so the stack refuses to synth without it — deliberately, because
# an empty layer deploys a function whose imports fail in the region. Tests
# assert stack SHAPE, so they stub the path with an empty directory. One test
# below asserts the refusal itself, which is the guard that makes the rest of
# this safe.
@contextlib.contextmanager
def stub_layer():
    from core import core_stack

    original = core_stack.LAYER_SRC
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "python").mkdir()
        core_stack.LAYER_SRC = Path(tmp)
        try:
            yield
        finally:
            core_stack.LAYER_SRC = original


# The handler each function declares, and a module that must therefore be in its
# zip. Keyed by handler so a renamed function construct does not silently drop a
# case — the assertion is about what the template says it will import.
HANDLERS = {
    "ingestion.poller.handler": "ingestion/poller.py",
    "ingestion.processor.handler": "ingestion/processor.py",
    "api.api.handler": "api/api.py",
    "handler.handler": "handler.py",          # the janitor, its own directory
}


def synth():
    """The core stack, synthesised into a real assembly directory.

    Assets are copied at synth time and the template records only a hash, so
    the file list can only be read off the assembly — the same reason the
    search-stack tests synthesise rather than reading the template.
    """
    import aws_cdk as cdk
    from core.core_stack import RegDeltaCoreStack

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core", env=cdk.Environment(
            account="111122223333", region="us-west-2"))
    assembly = app.synth()
    return assembly, assembly.get_stack_by_name("regdelta-core").template


def staged_files(assembly, template, handler: str) -> list[str]:
    key = next(r["Properties"]["Code"]["S3Key"]
               for r in template["Resources"].values()
               if r["Type"] == "AWS::Lambda::Function"
               and r["Properties"]["Handler"] == handler)
    root = Path(assembly.directory) / f"asset.{key.removesuffix('.zip')}"
    assert root.is_dir(), f"no staged asset for {handler} at {root}"
    return sorted(str(f.relative_to(root)).replace("\\", "/")
                  for f in root.rglob("*") if f.is_file())


@pytest.mark.parametrize("handler,module", sorted(HANDLERS.items()))
def test_each_lambda_ships_the_module_it_handles(handler, module):
    """An allowlist that ships nothing leaks nothing, and the M04 deploy failure
    was exactly that state on the other stack: "No module named 'retrieval'"."""
    assembly, template = synth()
    assert module in staged_files(assembly, template, handler)


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_lambda_ships_anything_but_python(handler):
    """The finding itself. `.pytest_cache/` and `__pycache__/*.pyc` were real —
    they are in the working tree right now, which is why this test would have
    failed before the fix and passes after it."""
    assembly, template = synth()
    leaked = [f for f in staged_files(assembly, template, handler)
              if not f.lower().endswith(".py")]
    assert leaked == [], f"{handler} stages non-Python files: {leaked}"


def test_the_query_lambda_ships_the_first_party_graph_it_runs():
    """api.api.handler compiles the LangGraph app on first request, so the graph
    and retrieval packages have to be in the same zip.

    FIRST-PARTY ONLY, and the name says so because an earlier version did not.
    Its third-party imports — fastapi, mangum, langgraph — are not in this asset
    at all and never were; they arrive via the layer. This test passing says
    nothing about whether the function can import. See
    test_the_query_lambda_gets_the_dependency_layer below, and the invoke that
    found it: "Unable to import module 'api.api': No module named 'fastapi'".
    """
    assembly, template = synth()
    files = staged_files(assembly, template, "api.api.handler")
    for module in ("graph/graph.py", "graph/nodes.py", "retrieval/router.py",
                   "shared/config.py"):
        assert module in files, f"{module} missing from the query Lambda"


def test_the_asset_path_does_not_depend_on_the_working_directory(monkeypatch,
                                                                 tmp_path):
    """`Code.from_asset("../src")` resolved only when cdk ran from infra/.

    The Makefile does `cd infra && npx cdk`, so it worked there and nowhere
    else — including from the repo root and from any test. Synthesising from an
    unrelated directory is what makes the difference visible.
    """
    monkeypatch.chdir(tmp_path)
    assembly, template = synth()
    assert "api/api.py" in staged_files(assembly, template, "api.api.handler")


# ---------------------------------------------------------- the dependency layer
# src/ ships first-party Python only, so fastapi, mangum, langgraph and the
# pinned boto3 reach Lambda through a layer or not at all. Until M04 they did not
# arrive at all, and nothing caught it: every "end to end" run in this repo
# drives the graph IN-PROCESS with the deployed function's environment variables
# rather than invoking the function. Invoking it returned
#   Unable to import module 'api.api': No module named 'fastapi'
# and had done since the function first deployed.
def test_the_query_lambda_gets_the_dependency_layer():
    """The half no asset test can see: what is NOT in the function's own zip."""
    _, template = synth()
    query = next(r["Properties"] for r in template["Resources"].values()
                 if r["Type"] == "AWS::Lambda::Function"
                 and r["Properties"].get("Handler") == "api.api.handler")
    assert query.get("Layers"), \
        "the query function has no layer, so fastapi/mangum/langgraph are absent"


@pytest.mark.parametrize("handler", ["ingestion.poller.handler",
                                     "ingestion.processor.handler",
                                     "handler.handler"])
def test_only_the_query_path_carries_the_layer(handler):
    """The poller, processor and janitor import boto3 and the standard library
    and nothing else. A layer on them is ~101MB of cold start for no import."""
    _, template = synth()
    fn = next(r["Properties"] for r in template["Resources"].values()
              if r["Type"] == "AWS::Lambda::Function"
              and r["Properties"].get("Handler") == handler)
    assert not fn.get("Layers"), f"{handler} does not need the layer"


def test_a_missing_layer_refuses_to_synth_rather_than_shipping_an_empty_one():
    """THE GUARD THAT MAKES stub_layer() SAFE, and the reason the build step is
    a hard dependency of `make core`.

    An empty or absent layer directory would otherwise synth and deploy
    perfectly, and the failure would arrive as a 500 from the region on a
    function whose imports cannot resolve — which is precisely the state this
    stack was in before M04.
    """
    import aws_cdk as cdk
    from core import core_stack

    original = core_stack.LAYER_SRC
    core_stack.LAYER_SRC = Path(tempfile.gettempdir()) / "regdelta-no-such-layer"
    try:
        app = cdk.App(outdir=tempfile.mkdtemp())
        with pytest.raises(FileNotFoundError, match="make layer"):
            core_stack.RegDeltaCoreStack(
                app, "regdelta-core",
                env=cdk.Environment(account="111122223333", region="us-west-2"))
    finally:
        core_stack.LAYER_SRC = original
