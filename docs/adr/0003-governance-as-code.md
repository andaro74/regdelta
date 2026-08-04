# ADR-0003: Governance-as-code from day one

- Status: accepted
- Milestone: M00 (pre-baseline)

## Context
RegDelta is both a compliance product and a demonstration of enterprise
AI-assisted development. Role accountability asserted in documents is
unenforceable; asserted in repo mechanics, it is self-demonstrating.

## Decision
Encode the org chart in the repo: CODEOWNERS maps files to role seats;
branch protection requires code-owner review + the eval-gate status check;
role subagents (.claude/agents/) perform first-pass review from each
seat's criteria; the PR template carries the provenance attestation
("I own every generated line"). Ground truth (golden set) is SME-owned
and engineering may never self-approve changes to it.

## Alternatives considered
- Governance wiki/policy docs only — unenforced, invisible in a demo.
- Separate "enterprise edition" repo later — loses the from-the-start
  audit trail, duplicates history.

## Consequences
+ Every accountability claim in the demo is showable as a blocked or
  approved PR.
- Solo development requires playing multiple seats honestly (see
  ROLES.md solo-operator mode); slight ceremony overhead per PR.
