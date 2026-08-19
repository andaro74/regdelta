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
import sys
import tempfile
from pathlib import Path

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))

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


def test_the_query_lambda_ships_the_graph_it_runs():
    """api.api.handler compiles the LangGraph app on first request, so the graph
    and retrieval packages have to be in the same zip. Named separately because
    "the handler's own module is present" would pass while the graph was
    missing, and the failure would arrive as a 500 in the demo."""
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
