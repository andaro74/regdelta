---
name: close-milestone
description: End-of-milestone ritual — run when a SPEC's Done-when passes and the user asks to close the milestone. Produces the evidence pack, ADRs, tag, and README progression update.
disable-model-invocation: true
---
# Close Milestone $ARGUMENTS

Run these steps in order; stop and report if any fails.

1. Verify: run the milestone's Done-when command(s) from SPEC/$ARGUMENTS.
   Then `make evals` (full set). Do not proceed on failure.
2. Evidence: `python evals/run_evals.py --record` on the active tier; if
   this milestone touches retrieval, run once per tier (make down/up as
   needed) so history has both rows.
3. Journal: create milestones/M$ARGUMENTS/README.md from
   milestones/TEMPLATE.md. Fill the scorecard from evals/history/, compute
   the delta vs M00b, and write the 2-3 step demo script for this stage.
   Ask the user for the "what broke" notes — do not invent them.
4. ADR: if this milestone made a consequential choice not yet recorded,
   draft docs/adr/NNNN-*.md from the template and ask the user to accept.
5. README: update the Progression table row for this milestone
   (status, pass %, tag).
6. Git: commit everything as "mNN: close — <one-line summary>", tag
   `mNN` (short form — NOT the branch name, or the tag and branch collide
   and pushing fails), and show the user the tag + scorecard delta. Do not
   push unless asked.
