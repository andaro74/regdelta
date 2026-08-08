"""TEMPORARY — probe that proves the `unit` required check actually gates.

ADR-0005 records that branch protection was reconfigured without ever being
exercised: the ruleset was applied 17 minutes after PR #2 merged, so no PR
has yet been tested against `required_status_checks: [{context: "unit"}]`.
A required check whose context string does not match the reported check-run
name sits pending forever — which is exactly how PR #1 deadlocked.

Two-phase probe, because BLOCKED alone is ambiguous — an unmatched context
sits pending and also reports BLOCKED.

Phase 1 (commit 1): deliberate F401 -> unit FAILS -> expect BLOCKED.
Phase 2 (this commit): violation removed -> unit PASSES -> expect CLEAN.
Only CLEAN in phase 2 proves the context resolves. Delete and close after.
"""
