"""Set the eval gate's Actions secrets and variables from the stack's outputs.

Values are read from CloudFormation rather than retyped, because a wrong
STAGING_API_URL or AWS_EVAL_ROLE_ARN does not fail loudly — the job fails at
`configure-aws-credentials` with a message about credentials, or `run_evals`
exits "No API URL", and neither says "the variable is wrong".

WHICH ARE SECRETS AND WHY (docs/governance/branch-protection.md, and
security-reviewer M07):

  AWS_EVAL_ROLE_ARN   SECRET   — carries the AWS account id
  STAGING_API_URL     SECRET   — names an API with NO authorizer where every
                                 /query spends a Bedrock call, reachable
                                 directly past CloudFront
  REGISTRY_TABLE      variable — a table name, on a table nothing reaches from
                                 the internet, and useful to see in a log

Actions VARIABLES are not masked in logs, and a `with:` input is echoed into the
step log BEFORE the action runs — so configure-aws-credentials'
`mask-aws-account-id` cannot help. On a public repo those logs are world-
readable.

EVAL_GATE_ENABLED is deliberately NOT touched here. Flipping it starts spending
Bedrock on every pull request, so it is its own decision with its own price.

    python milestones/M07/wire_actions_config.py [--dry-run]
"""
import argparse
import hashlib
import json
import subprocess
import sys

STACK = "regdelta-core"
REGION = "us-west-2"
REPO = "andaro74/regdelta"

SECRETS = {"AWS_EVAL_ROLE_ARN": "CiEvalRoleArn", "STAGING_API_URL": "ApiUrl"}
VARIABLES = {"REGISTRY_TABLE": "RegistryTableName"}


def outputs() -> dict:
    raw = subprocess.run(
        ["aws", "cloudformation", "describe-stacks", "--stack-name", STACK,
         "--region", REGION, "--output", "json"],
        check=True, capture_output=True, text=True).stdout
    stack = json.loads(raw)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def redact(name: str, value: str) -> str:
    """Enough to confirm the right value landed, and nothing of the value.

    THE FIRST VERSION PRINTED `value[:12]`, which for the API URL is
    "https://7o8m" — four characters of the very API id that security-reviewer
    raised as this milestone's HIGH, republished into a committed artifact by
    the fix's own author, one commit later. A head-and-tail redaction always
    leaks the ends, and for a URL the ends are the interesting part.

    A digest confirms the value that landed is the one the stack output holds —
    re-derivable by anyone with the stack, meaningless to anyone without it —
    and reveals nothing at all.
    """
    if name not in SECRETS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest} ({len(value)} chars)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out = outputs()
    missing = [k for k in (*SECRETS.values(), *VARIABLES.values()) if k not in out]
    if missing:
        sys.exit(f"stack {STACK} has no output(s) {missing} — deploy first")

    for name, key in SECRETS.items():
        value = out[key]
        print(f"secret   {name:20} <- {key:20} {redact(name, value)}")
        if not args.dry_run:
            subprocess.run(["gh", "secret", "set", name, "--repo", REPO,
                            "--body", value], check=True)

    for name, key in VARIABLES.items():
        value = out[key]
        print(f"variable {name:20} <- {key:20} {redact(name, value)}")
        if not args.dry_run:
            subprocess.run(["gh", "variable", "set", name, "--repo", REPO,
                            "--body", value], check=True)

    if args.dry_run:
        print("\ndry run — nothing was set")
        return 0

    # READ BACK, because `gh secret set` reports success on a write it did not
    # verify and a secret cannot be read again. Names and timestamps are all
    # GitHub will return, and that is exactly enough to say the write landed.
    print()
    names = json.loads(subprocess.run(
        ["gh", "api", f"repos/{REPO}/actions/secrets"],
        check=True, capture_output=True, text=True).stdout)
    print(f"secrets now set: {[s['name'] for s in names['secrets']]}")
    variables = json.loads(subprocess.run(
        ["gh", "api", f"repos/{REPO}/actions/variables"],
        check=True, capture_output=True, text=True).stdout)
    print("variables now set:")
    for v in variables["variables"]:
        print(f"  {v['name']} = {v['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
