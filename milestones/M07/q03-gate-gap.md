# OPEN — the eval gate does not consult the admitted-false-fail register

**Status: OPEN. Not fixed in M07, deliberately. A seat decision with a
measurement already attached.**

Found on 2026-08-22 by Door 1's own run — hours after the ruling it contradicts.

## What the PM ruling claimed

`milestones/M07/eval-gate-bar-ruling.md` changed the eval gate from `passed ==
total` to a regression bar, and justified the shape like this:

> **This is the theory the repository already uses.** `evals/replay_history.py`
> gates `unit` on regression against recorded history, with an admission
> register for observations a seat has ruled on (ADR-0015). Before this change
> there were two gates in one repository with two different theories of what
> "acceptable" means […]

**That claim is wrong in one respect, and the respect matters.** The two gates
now agree about *regression*. They do **not** agree about *admission*.
`replay_history.py` consults `evals/admitted_false_fails.json`;
`run_evals.gate_verdict()` does not consult it at all.

## What it cost, immediately

PR [#20](https://github.com/andaro74/regdelta/pull/20), the first pull request
opened after the bar landed:

```
KNOWN, not gating (1): q15
REGRESSION (1): q03
```

q03 is the FRAGILE question — `replay_history.py` classifies it as "agent
answers disagree across runs", and that non-determinism is the entire reason
ADR-0015 and the register exist. `unit` was green on the same commit, because
`replay_history` honoured the ruled admission. `golden-set` failed, because
nothing told it about the ruling.

**So a question the SME seat has already ruled on can block a merge through one
gate while being admitted by the other, on the same commit, in the same run.**

## Why it is not fixed here

Three reasons, in order of weight.

1. **It amends a ruling made hours earlier by the same person at the end of a
   long session.** That is the condition under which this project's worst
   decisions have been made, and the ruling itself names the failure mode it was
   avoiding. Handing it over with the evidence attached is better than patching
   it tired.

2. **The register does not fit a live run as it stands.** Entries are keyed per
   recorded artifact — a `sha` plus the scored digest of a specific recorded
   answer (`replay_history.scored_digest`). A live CI run against staging
   produces a *new* answer with no recorded artifact to match, so
   `gate_verdict()` cannot look one up. Any fix has to decide what an admission
   means for an answer nobody has seen before, and that is a question about the
   register's semantics, not a missing function call.

3. **The obvious shortcut is wrong.** "Exempt q03 from the eval gate" would
   hard-code one question id into a gate, which is the shape ADR-0015 exists to
   avoid — its whole point is that an override is per-observation and ruled,
   never per-rule.

## What a fix would have to answer

- Does an admission attach to a **question** (q03 may fail), to an **observed
  failure mode** (q03 may fail *on this reason*), or only to a **recorded
  artifact** (the current design)? Only the middle one helps a live run, and it
  is strictly weaker than what ADR-0015 ruled.
- If the eval gate admits a live failure, **what stops the admission set from
  growing** every time a question turns flaky? `unit`'s answer is that the cap
  is one entry and enforced by a test; the eval gate would need its own.
- Should a FRAGILE question be **retried** rather than admitted? That is a
  different answer to the same problem and it costs Bedrock rather than
  authority. Nobody has measured q03's failure rate across live runs, so nobody
  can say what a retry would buy.

## What is true today, so nobody is surprised

`golden-set` will **intermittently block merges on q03** until this is settled.
The bypass is gone, so there is no override. The recourse is to re-run the job
— which costs ~$0.20 and is exactly the "repeat the run until it goes green"
behaviour `run_evals.py` prints a warning about at record time.

That is the honest state of it. The gate is stricter than the seat ruled, in a
way nobody chose.
