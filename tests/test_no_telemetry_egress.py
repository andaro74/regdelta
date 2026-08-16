"""LangSmith tracing must stay off (SPEC/03 dependency, M03).

`langgraph` pulls `langsmith` transitively, and langsmith uploads prompts,
inputs and outputs to a third-party SaaS endpoint when LANGSMITH_TRACING or
LANGCHAIN_TRACING_V2 is truthy. For this product those payloads are the worst
thing to leak by accident: the company profile a user submits — revenue tier,
product lines — plus the regulatory analysis derived from it.

Upstream defaults are already off, so these tests protect against a *changed*
default and against an inherited environment variable, which is the realistic
failure: one `export LANGSMITH_TRACING=1`, or one leftover value in a Lambda
configuration, with nothing in the code reporting it.

These tests reach no network. That is the point — if one ever did, this file is
where it would be noticed.
"""
import importlib
import os

import pytest

TRACING_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2",
                "LANGSMITH_OTEL_ENABLED")


@pytest.mark.parametrize("var", TRACING_VARS)
def test_importing_config_forces_tracing_off(var):
    from shared import config
    assert os.environ[var] == "false", (
        f"{var} is not 'false' after importing shared.config — langsmith may "
        "upload prompts and company profiles to a third party")
    assert config is not None


@pytest.mark.parametrize("var", TRACING_VARS)
def test_an_inherited_truthy_value_is_overridden_not_merely_read(monkeypatch, var):
    """The realistic failure, and why config SETS rather than reads.

    A `defaults.setdefault(...)`-style implementation would leave an inherited
    value intact and quietly enable egress. Reimporting with the variable
    pre-set to a truthy value must come back false.
    """
    monkeypatch.setenv(var, "true")
    from shared import config
    importlib.reload(config)
    assert os.environ[var] == "false", (
        f"an inherited {var}=true survived importing shared.config; the "
        "override must win over the environment, not defer to it")


def test_the_control_is_not_configurable_by_an_env_var():
    """Guards the deliberate absence of an opt-in.

    Enabling tracing would mean sending customer data to a third party, which is
    an ADR-and-spec decision, not an env var. If someone adds
    `REGDELTA_ENABLE_TRACING` or similar, this fails and they have to justify it
    somewhere a reviewer will read.
    """
    from pathlib import Path
    src = (Path(__file__).parent.parent / "src" / "shared"
           / "config.py").read_text(encoding="utf-8")
    block = src.split("graph (03)", 1)[1].split("\n\n\n", 1)[0]
    code = "\n".join(ln.split("#")[0] for ln in block.splitlines())
    for var in TRACING_VARS:
        assert f'environ.get("{var}"' not in code, (
            f"{var} is being READ as configuration; it must be SET "
            "unconditionally")
    assert "TRACING" not in code.replace("LANGSMITH_TRACING", "").replace(
        "LANGCHAIN_TRACING_V2", "").replace("LANGSMITH_OTEL_ENABLED", ""), \
        "a new tracing toggle appeared — see this test's docstring"


def test_langsmith_is_present_so_the_hazard_is_real_not_theoretical():
    """If langsmith ever leaves the tree, this file can go with it.

    Asserted so the guard cannot outlive its reason and become cargo cult.
    """
    from importlib.metadata import PackageNotFoundError, version
    try:
        version("langsmith")
    except PackageNotFoundError:
        pytest.fail("langsmith is gone — delete this file and the config block "
                    "it guards rather than leaving a control with no hazard")
