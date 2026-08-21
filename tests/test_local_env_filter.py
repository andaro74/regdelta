"""What `evals/local_env.py` refuses to export into the operator's shell.

Its output is `eval`'d by the Makefile, so a name it emits reaches the shell
and every command after it. M05 put that on the default path — `make evals` and
`make smoke` now resolve the deployed environment — so the filter went from
covering one target to covering nearly every session.

VALUES cannot inject: `shlex.quote` single-quotes them and the Lambda API
constrains names to `[a-zA-Z][a-zA-Z0-9_]+`, so no metacharacter reaches an
unquoted position. That is not what this list is for. It exists to stop a
variable from REDIRECTING tooling, and the settable redirects were the ones
missing from it — most of the original entries name variables Lambda's
reserved-key check already refuses to set. Found by security-reviewer at M05.

Precondition for the threat: `lambda:UpdateFunctionConfiguration` on QueryFn.
Defence in depth, not a boundary.
"""
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

import local_env


def blocked(name: str) -> bool:
    return name.startswith(local_env._NOT_OURS)


def test_credential_resolution_cannot_be_redirected():
    """Each of these points boto3 or the CLI at someone else's credentials."""
    for name in ("AWS_CONTAINER_CREDENTIALS_FULL_URI",
                 "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                 "AWS_SHARED_CREDENTIALS_FILE",
                 "AWS_CONFIG_FILE",
                 "AWS_WEB_IDENTITY_TOKEN_FILE",
                 "AWS_ROLE_ARN"):
        assert blocked(name), name


def test_interpreters_the_make_targets_invoke_cannot_be_redirected():
    """`NODE_OPTIONS` reaches `npx cdk` in core/up/fault-drop and can
    `--require` arbitrary JS; `BASH_ENV` is sourced by every non-interactive
    bash, i.e. the next make recipe."""
    for name in ("NODE_OPTIONS", "BASH_ENV", "PYTHONPATH", "PYTHONSTARTUP",
                 "LD_PRELOAD", "PATH"):
        assert blocked(name), name


def test_the_configuration_regdelta_actually_needs_still_passes():
    """The filter must not eat the reason this script exists.

    `local_env.py`'s design is that a variable added to the deployed function
    reaches the shim with no change here — a filter that blocked real config
    would defeat it, and `REGISTRY_TABLE` in particular is what
    `corpus_fingerprint()` needs to stamp a scorecard with the corpus that
    answered.
    """
    for name in ("CORPUS_BUCKET", "STATE_TABLE", "REGISTRY_TABLE",
                 "VECTOR_BUCKET", "VECTOR_INDEX", "SEARCH_ENDPOINT_PARAM",
                 "MODEL_FAST", "MODEL_VERDICT", "EMBED_MODEL",
                 "API_BASE_PATH"):
        assert not blocked(name), name


def test_the_real_emit_path_filters_and_quotes(monkeypatch, capsys):
    """Drives `main()` itself, not `shlex.quote` in the abstract.

    The first version of this test asserted properties of `shlex.quote` with an
    `or` chain that made it nearly unfalsifiable — an instrument that cannot
    fail is worth nothing, which is this milestone's recurring lesson. This one
    runs the code that actually emits, through the filter that actually
    filters, and parses the result with a POSIX parser.
    """
    hostile = "'; rm -rf /; echo pwned '"
    variables = {
        "CORPUS_BUCKET": "regdelta-corpus",
        "REGISTRY_TABLE": hostile,
        "NODE_OPTIONS": "--require /tmp/evil.js",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://169.254.169.254/evil",
        "BASH_ENV": "/tmp/evil.sh",
    }
    for name in variables:
        monkeypatch.delenv(name, raising=False)

    def fake_aws(*args):
        if "list-functions" in args:
            return "regdelta-core-QueryFn-abc123"
        return json.dumps(variables)

    monkeypatch.setattr(local_env, "_aws", fake_aws)
    assert local_env.main() == 0
    out = capsys.readouterr().out

    exported = {}
    for line in out.splitlines():
        assert line.startswith("export "), f"non-export line on stdout: {line!r}"
        # A POSIX parser, because the Makefile hands this to `eval`.
        tokens = shlex.split(line)
        assert len(tokens) == 2, tokens
        key, _, value = tokens[1].partition("=")
        exported[key] = value

    assert "CORPUS_BUCKET" in exported
    for redirect in ("NODE_OPTIONS", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                     "BASH_ENV"):
        assert redirect not in exported, (
            f"{redirect} would be exported into the operator's shell")

    assert exported["REGISTRY_TABLE"] == hostile, (
        "a hostile value did not survive quoting intact — it was either "
        "mangled or, worse, parsed as shell")
