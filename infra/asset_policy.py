"""What a Lambda asset is allowed to ship, in ONE place.

Both stacks package the same `src/` tree, and until M04 they did it two
different ways: `regdelta-search` with an allowlist, `regdelta-core` with no
filter at all. Measured against the working tree, the core stack staged **75
files, 39 of them non-Python** — `.pytest_cache/`, every `__pycache__/*.pyc` —
into the poller, processor and query Lambdas on the PERSISTENT stack. A Lambda
code zip is retrievable by anyone holding `lambda:GetFunction`, which returns a
presigned URL to the artifact, so "what ships" is a disclosure question and not
a tidiness one. `security-reviewer`, M04.

Two copies of a packaging rule is the shape that drifted `_EDGE_PREDICATE` at
M01c and the index mapping before that. One module, imported by both.

THE ALLOWLIST AND ITS MODE ARE INSEPARABLE. `exclude` is meaningless without
`ignore_mode`: under CDK's default (GLOB) these same patterns stage *two files
and a leaked `.env`*, because minimatch's `*` prunes directories a later
negation can never re-enter, and does not match dot-prefixed names at all. That
is not a hypothetical — it is the M04 deploy failure, "Unable to import module
'retrieval.reindex': No module named 'retrieval'". Import both names together,
or use `python_source()` and get both.

DOCKER is .dockerignore semantics: every path is tested on its own, so a
negation re-includes files under an excluded directory, and `*` matches
dotfiles. Verified by synthesising against a tree containing .env,
.aws/credentials, dev.env, secrets.json, a `credentials` file with no extension
and __pycache__: only `**/*.py` ships, at every depth. GIT mode prunes
directories the way GLOB does.

The third pattern closes the one hole a security review found in the second:
`*` excludes a DIRECTORY named `keys.py`, `!**/*.py` then matches that directory
and re-includes its whole subtree, so `keys.py/secret.txt` shipped. Last match
wins, so re-excluding anything BELOW a `.py` path component costs one pattern
and cannot affect a real module, which has nothing below it.

Symlinks are not a hole: `follow_symlinks` defaults to `SymlinkFollowMode.NEVER`,
so a link is copied as a link and never dereferenced.
"""
from pathlib import Path

from aws_cdk import IgnoreMode, aws_lambda as _lambda

# Resolved from THIS FILE, not from the process CWD. `Code.from_asset("../src")`
# only works when cdk is invoked from infra/, which is what the Makefile does and
# what nothing else does — `cdk synth` from the repo root, and any test that
# synthesises a stack, both look for ../src one level too high. jsii runs Node in
# its own process, so a chdir on the Python side does not move it. The search
# stack carried this fix since M02; the core stack did not, which is why no test
# had ever synthesised it.
SRC = str(Path(__file__).resolve().parent.parent / "src")

ASSET_EXCLUDE = ["*", "!**/*.py", "**/*.py/**"]
ASSET_IGNORE_MODE = IgnoreMode.DOCKER

# THE SAME QUESTION FOR THE DEMO PAGE, where the answer matters more.
#
# The Lambda-code case above needs a reader holding `lambda:GetFunction`. The UI
# bucket needs no IAM at all — CloudFront serves it to anyone, and the
# distribution domain is a `CfnOutput`. `Source.asset(UI_SRC)` carried no filter
# until `security-reviewer` measured it against a `ui/` seeded with strays:
#
#     ['.env', '__pycache__/x.pyc', 'index.html', 'notes.md', 'verdict.js']
#
# So it is an explicit allowlist of the two files the page is, rather than
# `!**/*.{html,js}` — a scratch `index.old.html` or a vendored script would
# otherwise publish itself, and the whole point is that adding something to the
# anonymous distribution should be a decision someone made.
UI_ASSET_EXCLUDE = ["*", "!index.html", "!app.css", "!app.js", "!verdict.js",
                    "!favicon.svg"]


def python_source(path: str | None = None) -> _lambda.Code:
    """A Lambda asset carrying Python source and nothing else.

    Defaults to the shared `src/` tree. Pass a path for a Lambda that ships its
    own directory — the policy is the same wherever it is applied, which is the
    point of it living here.
    """
    resolved = path or SRC
    # A relative path here reintroduces exactly the CWD dependence SRC exists to
    # remove — and it would resolve under `make` and nowhere else, which is how
    # `../src` survived unnoticed. Structural rather than a convention someone
    # has to remember. security-reviewer, M04.
    if not Path(resolved).is_absolute():
        raise ValueError(
            f"asset path must be absolute, got {resolved!r} — resolve it from "
            "the calling module's __file__, as SRC does")
    return _lambda.Code.from_asset(resolved, exclude=ASSET_EXCLUDE,
                                   ignore_mode=ASSET_IGNORE_MODE)
