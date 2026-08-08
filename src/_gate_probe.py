"""TEMPORARY — isolating test for the required-check context format.

Prior probe (PR #3) proved `context: "unit"` gates correctly: F401 -> BLOCKED,
clean -> CLEAN. But it changed two things at once versus the deadlocked state
— the context string AND the removal of `eval-gate / golden-set` — so it could
not say which one had stuck PR #1.

This run isolates the format. Required checks are set to `eval-gate / unit`
alone (golden-set already out). This file is lint-clean, so `unit` will pass.

  BLOCKED -> the slash/display format never matched; context mismatch was the
             real cause of PR #1, and ADR-0005 names the wrong one.
  CLEAN   -> the slash format is valid, and the SKIPPED explanation stands.

Delete this file and close the PR once observed; it must never reach main.
"""
