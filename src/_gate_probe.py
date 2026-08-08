"""TEMPORARY — probe that proves the `unit` required check actually gates.

ADR-0005 records that branch protection was reconfigured without ever being
exercised: the ruleset was applied 17 minutes after PR #2 merged, so no PR
has yet been tested against `required_status_checks: [{context: "unit"}]`.
A required check whose context string does not match the reported check-run
name sits pending forever — which is exactly how PR #1 deadlocked.

This file contains a deliberate F401. Expected: `unit` fails, the PR reports
BLOCKED, and the gate is proven to gate. Delete this file and close the PR
once observed; it must never reach main.
"""

import json  # noqa-free on purpose: unused, trips F401
