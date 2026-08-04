# Branch protection setup (5 minutes, cannot live in the repo itself)

GitHub → Settings → Branches → Add rule for `main`:
- [x] Require a pull request before merging
- [x] Require approvals (1)
- [x] Require review from Code Owners        ← activates CODEOWNERS
- [x] Require status checks to pass:
      - eval-gate / unit
      - eval-gate / golden-set   (after setting EVAL_GATE_ENABLED=true)
- [x] Do not allow bypassing the above (include administrators)

Repo → Settings → Secrets and variables → Actions → Variables:
- EVAL_GATE_ENABLED = true          (after M04: staging API exists)
- STAGING_API_URL   = https://...   (regdelta-core ApiUrl output)
- AWS_EVAL_ROLE_ARN = arn:aws:iam::...:role/regdelta-ci-eval
  (OIDC trust to this repo; permissions: invoke the API only)

Teams (org) or collaborator accounts:
- regdelta-pm, regdelta-sme, regdelta-security, regdelta-lead, regdelta-eng
Solo mode: map all to yourself, or create 2 extra free accounts for the
SME and Security seats — the demo's Door 1 and Door 3 need at least one
seat you don't control from your main account.
