# OPEN — the eval gate blocks on run-to-run non-determinism

*(Filed as "the q03 gap". That name was wrong and the second observation is why — see "It is not q03" below.)*

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

## IT IS NOT q03. Second observation, one pull request later.

PR [#22](https://github.com/andaro74/regdelta/pull/22) — the pull request
carrying *this document* — was blocked by `golden-set` too. Different question:

```
KNOWN, not gating (2): q12, q15
REGRESSION (1): q05
```

And q05 did not fail on a token. It failed because the system **declined to
answer**:

```
q05: DECLINED, not answered — status pending_review, confidence 0.0
     the token misses below follow from an empty answer; they are not its cause
```

q05 has passed in **eleven** recorded S3 Vectors runs and failed in two. It is
not a known-bad question; it is a question the system usually answers and
sometimes abstains on.

**So two consecutive pull requests were blocked by two different questions, for
two different reasons, neither related to the contents of either pull request.**
PR #22 changes documentation only. It cannot have caused a retrieval abstention.

### What that reframes

The narrow reading — "`gate_verdict()` should consult the register" — is now
clearly insufficient. The register admits **one ruled q03 observation**
(ADR-0015 caps it at one entry, enforced by a test). It has nothing to say about
q05 abstaining, and adding an entry per flake is exactly the growth ADR-0015
forbids.

The real shape is: **`run_evals.py` scores a single live sample per question and
the gate treats any miss as a regression.** `replay_history.py` never had this
problem because it compares *recorded* runs and can see a question flip back and
forth over time — that is literally what its `FRAGILE` classification is. The
eval gate has one sample and no notion of variance at all.

### The operational consequence, now demonstrated twice

With no admin bypass, a docs-only pull request cannot be merged until a
non-deterministic system happens to produce a passing sample. The only recourse
is re-running the job at ~$0.20 a time — which is precisely the "repeat the run
until it goes green" behaviour `run_evals.py` prints a warning about at record
time. **The gate currently makes the repository's own anti-pattern the only way
to merge.**

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

**Added after the q05 observation.** The first question is now prior to all the
others: *does a single live sample mean anything?* Candidate answers, none
ruled:

- **Retry on failure, gate on the retry.** Cheapest to reason about, costs
  Bedrock, and needs a measured flake rate nobody has. It also weakens the gate
  by exactly the retry count.
- **Gate on the recorded history the way `unit` does**, and stop treating a live
  run as authoritative at all — the eval gate becomes a reporter and
  `replay_history` stays the gate. This is close to what the repo did before
  M07 and would make the eval gate's requiredness cosmetic again.
- **Treat an abstention as distinct from a wrong answer.** q05 did not answer
  wrongly; it declined at confidence 0.00, which the HITL design calls correct
  behaviour. A gate that cannot tell "refused to answer" from "answered wrong"
  is measuring the wrong thing — and `run_evals.py` already prints the
  distinction, so the information is there and unused.

### And the original questions, still open

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
