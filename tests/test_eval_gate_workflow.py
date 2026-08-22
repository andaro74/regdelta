"""The eval gate's workflow says what each job may do. This checks it is true.

`.github/workflows/evals.yml` carries a note declining exactly this test, on
2026-08-16, for two stated reasons and one stated reversal condition:

    "It would parse this file and assert each job holds exactly the permissions
     its steps need, which needs a YAML parser; PyYAML is not transitive from
     boto3, langgraph, fastapi, starlette, mangum or ruff, so it would have had
     to become a dependency. Declined because the guard protects a job that
     currently never runs ... REVERSAL CONDITION ...: when EVAL_GATE_ENABLED
     goes true, this job starts running and a silent permissions regression
     becomes a live failure with a misleading cause. Add the guard then, in the
     same change that flips the flag."

M07 flips the flag, so the reversal condition is met and the guard lands here.

**The dependency reason was also false.** PyYAML IS transitive:
`langgraph -> langchain-core -> pyyaml<7.0.0,>=5.3.0`, resolved to 6.0.3 and
installed in CI today by `requirements-dev.txt`'s `-r requirements.txt`. It is
imported here rather than pinned because pinning it is a dependency decision and
this repo asks before taking those; if langchain-core ever drops it, this module
fails to import loudly rather than skipping, which is the correct direction for
a guard.

The defect this exists to catch is specific and has happened: a job-level
`permissions` block REPLACES the workflow-level one rather than merging with
it. When per-job scoping landed at M04, the workflow level was lowered and
`golden-set`'s block was not added in the same commit — caught then by reading
the parsed YAML rather than the diff, which is what this now does on every PR.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "evals.yml"

# What a step's presence ENTITLES its job to. Derived from the action, not from
# the job's own declaration — otherwise the test reads the answer off the thing
# it is checking, which is the instrument defect ADR-0013 is about.
NEEDS = {
    "actions/checkout": ("contents", "read"),
    "aws-actions/configure-aws-credentials": ("id-token", "write"),
}
# github-script can do many things; what THIS repo uses it for is a PR comment.
GITHUB_SCRIPT = "actions/github-script"
COMMENT_CALL = "issues.createComment"


def workflow() -> dict:
    # `on:` parses as the boolean True under YAML 1.1, which is why nothing here
    # indexes it by name.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def required_permissions(job: dict) -> dict:
    """The narrowest permission set the job's own steps justify."""
    need = {}
    for step in job.get("steps", []):
        uses = (step.get("uses") or "").split("@")[0]
        if uses in NEEDS:
            key, value = NEEDS[uses]
            need[key] = value
        if uses == GITHUB_SCRIPT and COMMENT_CALL in str(step.get("with", "")):
            need["pull-requests"] = "write"
    return need


def test_the_workflow_level_grant_is_the_floor():
    """`contents: read` and nothing else. Everything wider is per job, next to
    the one step that spends it."""
    assert workflow()["permissions"] == {"contents": "read"}


def test_every_job_declares_its_own_permissions():
    """THE DEFECT THIS FILE EXISTS FOR. A job-level block REPLACES the
    workflow-level one; it does not merge. A job that omits it does not inherit
    `contents: read` plus its own additions — it gets the default token, and
    which default depends on repository settings, so the answer is not even
    visible in this file."""
    for name, job in workflow()["jobs"].items():
        assert "permissions" in job, (
            f"job {name!r} declares no permissions block. It does not inherit "
            f"the workflow-level one — that block is replaced, not merged.")


def test_each_job_holds_exactly_what_its_steps_need():
    """Exactly: no missing grant, and no spare one.

    The missing direction breaks OIDC or the PR comment. The spare direction is
    the one worth a test — `unit` runs author-controlled Python via pytest and
    installs tens of MB of vendored JavaScript through aws-cdk-lib, on every PR
    including forks. That is acceptable only while it holds a read-only token
    and no secrets."""
    for name, job in workflow()["jobs"].items():
        need = required_permissions(job)
        held = job["permissions"]
        assert held == need, (
            f"job {name!r} holds {held} but its steps justify {need}. "
            f"Either a step was added without its grant, or a grant outlived "
            f"the step that needed it.")


def test_unit_assumes_no_aws_role_and_reads_no_secrets():
    """Stated in the file as DO NOT WIDEN THIS, and now enforced rather than
    asked for. `unit` is the job that runs on every fork PR."""
    unit = workflow()["jobs"]["unit"]
    assert unit["permissions"] == {"contents": "read"}
    body = yaml.dump(unit)
    assert "secrets." not in body, "`unit` must see no secrets"
    assert "configure-aws-credentials" not in body, \
        "`unit` must assume no AWS role"


# --------------------------------------------------------------------------
# The two defects M07 found in the before-state. A fix without a guard is how
# it comes back.
# --------------------------------------------------------------------------

def test_the_gate_runs_in_the_region_the_stack_is_in():
    """WAS us-east-1 against a us-west-2 stack, unexercised because the job has
    never run. configure-aws-credentials EXPORTS AWS_REGION, and
    shared/config.py reads it with `us-west-2` as the default — so the wrong
    value here overrides the default that makes everything else work, and every
    boto3 client in the job looks in an empty region."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from shared import config

    text = WORKFLOW.read_text(encoding="utf-8")
    regions = set(re.findall(r"aws-region:\s*(\S+)", text))
    assert regions, "no aws-region declared; the default is not us-west-2"
    assert regions == {config.REGION}, (
        f"workflow uses {regions}, config.REGION is {config.REGION!r}. "
        f"A gate measuring a stack it cannot see reports availability, not "
        f"a score.")


def test_the_gate_can_fingerprint_the_corpus():
    """Without REGISTRY_TABLE, `shared.corpus.fingerprint()` returns
    `{"available": false}` and every scorecard the gate posts on a PR is
    corpus-blind — in the silent direction, because fingerprint() swallows its
    own failure by design.

    That field is what ruled corpus drift in or out in one line when q03
    regressed during the M05 window, and M05 recorded against itself that the
    one card where q03 first failed was the one recorded without the
    environment resolved."""
    jobs = workflow()["jobs"]
    step = next(s for s in jobs["golden-set"]["steps"]
                if s.get("id") == "evals")
    assert "REGISTRY_TABLE" in step.get("env", {}), (
        "the eval step passes no REGISTRY_TABLE, so every scorecard it posts "
        "will carry corpus: {'available': false}")


def test_the_gate_does_not_run_on_fork_pull_requests():
    """The OIDC trust policy CANNOT tell a fork from an owner PR — the `sub`
    claim is `repo:andaro74/regdelta:pull_request` for both, because GitHub's
    token carries no fork claim. What isolates a fork today is that fork-PR
    token permissions cap at read and `id-token` has no read level, so it
    resolves to `none`. That is real and it is PLATFORM behaviour, invisible
    to a reader of this repo.

    It is also the operational fix: without the clause an outside
    contributor's PR carries a permanently red `golden-set` reading
    "Credentials could not be loaded" — not their fault and not fixable by
    them. security-reviewer, M07 M3."""
    condition = workflow()["jobs"]["golden-set"]["if"]
    assert "github.event.pull_request.head.repo.full_name" in condition
    assert "github.repository" in condition
    assert "vars.EVAL_GATE_ENABLED" in condition


def test_the_account_id_and_the_api_host_are_secrets_not_variables():
    """Actions variables are NOT masked in logs, and on a public repo those
    logs are world-readable. A `with:` input is echoed into the step log
    BEFORE the action runs, so configure-aws-credentials' `mask-aws-account-id`
    cannot help — masking is registered by the action, after the echo.

    STAGING_API_URL is the one that matters: it names an API with no
    authorizer where every /query spends a Bedrock call, reachable directly
    past CloudFront. security-reviewer, M07 HIGH and the vars question.
    See docs/governance/branch-protection.md."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in ("AWS_EVAL_ROLE_ARN", "STAGING_API_URL"):
        assert f"secrets.{name}" in text, f"{name} must be a secret"
        assert f"vars.{name}" not in text, \
            f"{name} is read as a variable; variables are not masked in logs"


def test_no_stray_actions_expression_in_a_script_body():
    """A `script:` body is a YAML VALUE, not a comment, so Actions expression
    syntax written there — even inside a // JavaScript comment — is parsed and
    evaluated, and an empty one is a workflow syntax error. Caught while
    writing the L4 fix, by an editor rather than by a failed run."""
    for job in workflow()["jobs"].values():
        for step in job.get("steps", []):
            script = (step.get("with") or {}).get("script", "")
            for expr in re.findall(r"\$\{\{(.*?)\}\}", script, re.DOTALL):
                assert expr.strip(), \
                    "empty Actions expression in a script body: syntax error"


def test_the_enforce_step_still_fails_closed():
    """Pinned because it has been broken twice: once by a pipe that made `$?`
    tee's exit status, once by an empty interpolation rendering to a bare
    `exit`, which returns 0. Both were gates that passed because their own
    measurement had died."""
    jobs = workflow()["jobs"]
    enforce = next(s for s in jobs["golden-set"]["steps"]
                   if s.get("name") == "Enforce")
    assert enforce.get("if") == "always()", \
        "a failed comment step would skip enforcement entirely"
    run = enforce["run"]
    assert '-z "$EVAL_RC"' in run, "no guard against a missing exit code"
    assert "exit 1" in run, "the missing-exit-code path must fail closed"
    assert "${{" not in run, \
        "the exit code must be read through env:, never interpolated into shell"
