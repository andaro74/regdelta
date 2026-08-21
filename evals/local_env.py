#!/usr/bin/env python
"""Print the deployed query Lambda's environment as shell `export` lines.

The loopback shim (evals/serve_local.py) runs the real graph in-process, so it
needs the same configuration the deployed function has: bucket names, table
names, the search-endpoint parameter. Until now those came from whatever the
operator happened to have exported, which failed twice in one session on
2026-08-15 — first on VECTOR_BUCKET, then, after that was fixed by reading two
CloudFormation outputs, on REGISTRY_TABLE, which the stack does not export at
all. Chasing outputs one at a time was the wrong fix.

THE LAMBDA'S OWN ENVIRONMENT IS THE SOURCE OF TRUTH. It is what production
runs with, CDK sets it, and reading it means a local run is configured exactly
as the deployed one rather than approximately. A new variable added to the
function reaches the shim with no change here.

Never overrides a variable already set, so an operator pointing at something
else keeps pointing at it. Prints nothing but export lines on stdout, so it is
safe to `eval`; everything else goes to stderr.

    eval "$(python evals/local_env.py)"
    python evals/local_env.py            # just look at it
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

REGION = os.environ.get("AWS_REGION", "us-west-2")
FUNCTION_HINT = "QueryFn"
# Names that would redirect tooling rather than configure RegDelta.
# The output of this script is `eval`'d by the Makefile, so a name here
# reaches the OPERATOR'S shell and every command after it. Values cannot
# inject — `shlex.quote` single-quotes them and the Lambda API constrains names
# to `[a-zA-Z][a-zA-Z0-9_]+` — so this list is not what makes `eval` safe. It
# is what stops a variable from REDIRECTING tooling, which is its own comment's
# stated job.
#
# Most of the original entries name variables Lambda's reserved-key check
# already refuses to set; the SETTABLE redirects were the ones missing.
# `AWS_CONTAINER_CREDENTIALS_*` points boto3's credential resolution at an
# arbitrary URL, `AWS_SHARED_CREDENTIALS_FILE`/`AWS_CONFIG_FILE`/
# `AWS_WEB_IDENTITY_TOKEN_FILE`/`AWS_ROLE_ARN` do the same by other routes,
# `NODE_OPTIONS` reaches `npx cdk` in `make core`/`up`/`fault-drop` and can
# `--require` arbitrary JS, and `BASH_ENV` is sourced by every non-interactive
# bash — i.e. later make recipes. Precondition is
# `lambda:UpdateFunctionConfiguration` on QueryFn, so this is defence in depth;
# it moved from noise to worth-fixing when M05 put RESOLVE_ENV on the default
# path for `make evals` and `make smoke`. security-reviewer, M05.
_NOT_OURS = ("PATH", "PYTHON", "LD_", "DYLD_", "AWS_ENDPOINT", "AWS_CA_",
             "AWS_PROFILE", "AWS_ACCESS", "AWS_SECRET", "AWS_SESSION",
             "AWS_CONTAINER", "AWS_SHARED", "AWS_CONFIG", "AWS_WEB_IDENTITY",
             "AWS_ROLE", "NODE_", "BASH_ENV", "ENV", "PERL", "RUBYOPT")


def _aws(*args: str) -> str:
    # MSYS_NO_PATHCONV: Git Bash rewrites arguments that look like POSIX paths,
    # which mangles --query expressions and SSM parameter names. The Makefile
    # already carries this scar for `retrieval-evals`.
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.check_output(["aws", *args], text=True, env=env,
                                   stderr=subprocess.PIPE).strip()


def main() -> int:
    try:
        name = _aws("lambda", "list-functions", "--region", REGION, "--output", "text",
                    "--query",
                    f"Functions[?contains(FunctionName,'{FUNCTION_HINT}')].FunctionName|[0]")
        if not name or name == "None":
            print(f"no deployed function matching {FUNCTION_HINT!r} in {REGION}. "
                  f"Deploy the core stack first: make core", file=sys.stderr)
            return 1
        raw = _aws("lambda", "get-function-configuration", "--function-name", name,
                   "--region", REGION, "--output", "json",
                   "--query", "Environment.Variables")
    except FileNotFoundError:
        print("the aws CLI is not on PATH", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"aws call failed: {(e.stderr or '').strip()[:400]}", file=sys.stderr)
        return 1

    variables = json.loads(raw) if raw and raw != "null" else {}
    if not variables:
        print(f"{name} has no environment variables", file=sys.stderr)
        return 1

    exported, kept, skipped = [], [], []
    for k, v in sorted(variables.items()):
        if k.startswith(_NOT_OURS):
            # These are not RegDelta settings and this output is `eval`ed by the
            # Makefile, so exporting one would redirect every subsequent aws /
            # boto3 call in the operator's shell — including the eval harness's.
            # The trust boundary is IAM and it holds; this bounds the blast
            # radius if it ever does not, and costs one comparison.
            skipped.append(k)
        elif os.environ.get(k):
            kept.append(k)
        else:
            print(f"export {k}={shlex.quote(str(v))}")
            exported.append(k)

    if skipped:
        print(f"NOT exporting {', '.join(skipped)} — not RegDelta settings",
              file=sys.stderr)
    print(f"resolved from {name}: {', '.join(exported) or 'nothing'}"
          + (f" (already set, left alone: {', '.join(kept)})" if kept else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
