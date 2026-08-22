# RESOLVED AS TO CAUSE — the eval gate was right, and it caught a real defect

*(Filed as "the q03 gap", renamed to "run-to-run non-determinism", and both
names described the nearest symptom. This is the third name and the first one
taken from a measurement: see "FOURTH observation" below. `q05-mechanism.txt`
holds the numbers.)*

**Status: the CAUSE is established and the gate needs no change on account of
q05. What remains open is one narrow policy question — see "What is actually
still open" — plus a product defect that belongs to its own milestone.**

> **READ THIS BEFORE THE REST OF THE FILE.** Everything below the FOURTH
> observation was written before the metrics were read. The reasoning is left
> in place because being wrong three times in the same direction is the most
> useful thing this document records — but **the three candidate fixes it
> proposes are all wrong, and one of them would have buried the defect
> permanently.** Do not lift them out of here.

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

## THIRD observation, and it moves the diagnosis again

PR #22 was re-run after the document above was widened. **q05 declined a second
time, identically** — `confidence 0.00`, `pending_review`. Two consecutive CI
runs, same question, same reason. That is not what non-determinism looks like,
so "flake" was the wrong word too.

### The probe that separates the hypotheses, for ~$0.03

q05 asked directly against the same staging endpoint, cache bypassed both ways
exactly as `run_evals.ask()` does, three times:

```
call 1   status ok   confidence 0.95   citations ['89 FR 106064','90 FR 10592','2024-29957','2025-03118']
call 2   status ok   confidence 0.93   citations ['89 FR 106064','90 FR 10592']
call 3   status ok   confidence 0.93   citations ['89 FR 106064','90 FR 10592','2024-29957','2025-03118']
```

**3/3 answered, high confidence, correct citations, tier `s3vectors`,
`cache: bypass`.** The same question that declined twice inside a 20-question CI
run answers reliably when asked on its own.

### What that establishes, and what it does NOT

**Established:** q05 is not broken, and the golden set's expectation for it is
not wrong. The decline is a property of *the run*, not of the question, the
corpus, or the ground truth. So this is not a case for touching
`golden_questions.json` — and it would have been very easy to "fix" q05 by
weakening it, which would have been the ROLES.md prohibition exactly.

**NOT established: the mechanism.** The obvious hypothesis is load — twenty
questions in sequence hitting a Bedrock throttle or timeout, one of them losing,
which question varies. That is a *hypothesis*. What supports it: the single-shot
probe passes; the failures move between questions (q03 on PR #20, q05 twice on
PR #22); and `confidence 0.00` is distinct from the ordinary HITL declines in
CloudWatch, which sit at 0.20-0.30 with a real answer attached. **0.00 with an
empty answer looks like something failing, not like the model being unsure.**

What has NOT been done: no throttling metric has been read, no correlation
between position-in-run and failure has been measured, and the query Lambda's
logs were searched only coarsely. **Anyone continuing this should start there
rather than from my hypothesis.**

> Someone did. The metrics say the hypothesis is wrong. Read on.

### Why this document has been renamed twice

It was filed as "the q03 gap", widened to "run-to-run non-determinism", and both
names were wrong in the same direction: they described the symptom nearest to
hand. It is recorded here rather than tidied away, because a document that has
been wrong twice about its own subject should say so to the person reading it
third.

## FOURTH observation — the metrics, and the load hypothesis dies

Read 2026-08-22 from CloudWatch, at no Bedrock cost, exactly where the note
above said to start. Full tables and method in
[`q05-mechanism.txt`](q05-mechanism.txt). The short form:

| what was hypothesised | what the metrics say |
|---|---|
| a Bedrock throttle | `InvocationThrottles` has **no datapoints in either window, and does not exist in `list-metrics` for this account and region at all**. There has been no throttle. |
| a timeout | verdict model's worst call in either run: **16.6 s**, against a 120 s client timeout. No Lambda invocation exceeded 18.4 s. |
| a client/server error | `InvocationClientErrors` and `InvocationServerErrors`: no datapoints in either window. |
| a retry storm | exactly **20 invocations per model per run**, both runs. Twenty questions, twenty calls. `retry()` never fired. |
| load accumulating over a 20-question run | **q05 is question five of twenty.** The two longest invocations in the run are questions 19 and 12, and both passed. |
| "whichever question loses" | **the same question lost both times**, and q03 on PR #20 was a different and already-explained failure. Conflating the two is what produced the word "non-determinism". |

**And the call that "declined" did not fail. It succeeded.** Both times, byte
for byte:

```
run A  17:37:11.643  input 7083  output 764  Confidence 0.0  Citations 0.0  VerdictRows 0.0
run B  18:21:15.701  input 7083  output 764  Confidence 0.0  Citations 0.0  VerdictRows 0.0
```

764 output tokens generated and billed, against a `max_tokens` of 2000. The
model answered at length. `draft_answer` in the HITL interrupt is `''`.

`Confidence 0.0` **and** `Citations 0.0` **and** `VerdictRows 0.0` **and**
`DroppedCitations 0.0` **and** an empty answer is the signature of exactly one
thing in `verdict()`: **`_json_object(raw)` returned `{}`** and every
downstream field collapsed to its empty value. A model that answered and cited
badly would have left something in `dropped_citations`. A model that genuinely
declined would have left prose. Nothing survived the parse.

### The prompt was identical to the one the probe answered six times

verdict-node input tokens for q05, every observation that day: **7083 in all
eight** — the two CI declines and all six probe passes. (The probe was run
twice, not once; `q05-probe.txt` records the second run. Its real score is
6/6.) `cacheRead`/`cacheWrite` are 0.0 throughout, `temperature` is 0, and
retrieval returned 8 chunks every time. The twenty verdict input token counts
are identical question-for-question between the two CI runs, so retrieval, the
timeline graph, the crossref append and prompt assembly are all reproducible.

The only thing that varies between a pass and a decline is **which completion
Bedrock returns for a byte-identical request**, and whether `_json_object` can
parse it.

### What is established, and what is still a guess

**ESTABLISHED.** q05's decline is a **parse failure in `verdict()`**. Not a
throttle, not a timeout, not load, not concurrency, not position in the run,
not the corpus, not the question, not the ground truth. `run_evals.py`
reported a regression **correctly**. The HITL gate declined **correctly**.
Both gates behaved as designed; the system under them did not.

**STILL A GUESS, and labelled as one.** *Why* that reply did not parse. The raw
text is logged nowhere and cannot be recovered. Leading candidate: `json.loads`
is strict about literal control characters inside strings, and 764 tokens is
the longest q05 completion observed — longer than all six that parsed. That is
a guess with a shape, and it deserves the same suspicion as this document's
first three framings.

### The instrument that would have said so was built, and nothing reads it

`nodes.py:126-131` predicted this failure class in writing, and named the field
that separates it from an honest silence: the stop reason. M05 and ADR-0013
built it. `verdict()` returns `stop_reason` and `truncated`, `instrument.py`
carries them, `api.py` puts them in the response body — and then `run_evals.py`
never prints either on a failure, `q05_probe.py` never printed them either, and
nothing anywhere records the raw completion.

**Three successive framings of this document named a symptom because the
reading that separates them was in the response body the whole time and no
consumer looked at it.** That is the finding with the longest reach here, and
it is bigger than q05.

(The comment was also half wrong, which is worth saying: it predicted the
`max_tokens` cut-off. This is its sibling — a *complete* reply that does not
parse. `truncated` alone reads `False` here and sends the reader back to the
start. Only `stop_reason` tells the two apart.)

---

## RULING ON THE GATE — **ADOPTED**, PM seat, 2026-08-22

Adopted as drafted. Sources are the tables in `q05-mechanism.txt`; every claim
below is falsifiable against them, which is what makes this a ruling rather
than a signature.

**1. The eval gate needs no change on account of q05, and the bar ruled on
2026-08-22 stands.** It was asked to catch a regression against recorded
history. On those two runs the system genuinely failed to answer a question it
had answered eleven times. That is a regression, and the gate said so. The
premise that made this a gate-theory problem — that the failure was noise —
is refuted.

**2. All three candidate fixes below are wrong, and the most attractive one is
the most dangerous.** They are kept in this file as a record, not as options:

| candidate | what the measurement does to it |
|---|---|
| *Retry on failure, gate on the retry* | The probe passes 6/6. A retry would go green almost every time, so this converts a caught defect into a defect that can never be caught. It buys silence, not reliability. |
| *Gate on recorded history; the eval gate becomes a reporter* | Recorded history has q05 passing eleven times. This hides it too, and additionally makes the requiredness of `golden-set` cosmetic — which is the state M07 exists to leave behind. |
| *Treat an abstention as distinct from a wrong answer* | **The worst of the three, and it reads as the most principled.** q05 did not abstain. There was no answer to abstain with. A rule forgiving `confidence 0.00` with an empty body forgives *precisely* the parse-failure signature, silently and permanently. It would have institutionalised this defect as correct behaviour. |

The general lesson, and the reason to keep the table: **each one would have
made the symptom go away by teaching the gate to ignore the class of failure
the gate exists for.** The document proposed all three while believing the
failure was noise. That belief was the error; the fixes were downstream of it.

**3. The defect is real, is in the product, and is not M07 scope.** It belongs
beside q12 and q15 in its own milestone. Note the family resemblance:

- **q05** — the answer-composition layer silently discards a complete model
  reply it cannot parse, and reports it as low confidence.
- **q12** — the answer-composition layer inverts a verdict sentence it has
  already reasoned correctly.
- **q15** — retrieval embeds one raw query at `NAIVE_TOP_K = 8` with no
  decomposition.

Two of the three now sit in the same layer. That is a milestone-shaped
observation, not three separate bugs.

**4. The smallest useful next step is instrumentation, not a gate change.**
Make `_json_object`'s failure observable rather than silent, and make the eval
scorecard print `stop_reason` on any decline. Both were built already
(ADR-0013); only the reading is missing. Until that lands, any future decline
will cost another session of exactly this archaeology.

## What is actually still open

One thing, and it is narrower than this document has been claiming:

**A real product defect blocks an unrelated documentation pull request, there
is no bypass, and a retry costs ~$0.20.** That is the gate working as designed
producing an outcome nobody chose. It is a *policy* question — how does a
docs-only change land while a product defect is outstanding? — and not a
question about what the gate should consider a regression.

It is a seat question. What it is **not** is a reason to loosen the bar, and
the three tables above are why.

## Why it is not fixed here

Three reasons, in order of weight. **Reason 2 below is now known to be beside
the point** — the register was never the issue — but it is left standing
because it was load-bearing for the decision made at the time.

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

> **SUPERSEDED by the FOURTH observation.** The question this section opens
> with — *does a single live sample mean anything?* — presupposes that the
> sample was noise. It was not: the same prompt produced a reply the parser
> dropped. Read the three candidates below as a record of what looked
> reasonable before anyone read the metrics, and the ruling above for what
> each one would actually have cost.

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

**Corrected by the FOURTH observation.** This section previously said the gate
was "stricter than the seat ruled, in a way nobody chose". It is not. It is
exactly as strict as the seat ruled, and it is reporting a defect in the
product.

What is true: `golden-set` will block a merge whenever the verdict node's
reply fails to parse, on whichever question draws the unlucky completion. The
bypass is gone, so there is no override, and a re-run costs ~$0.20 — which
*is* the "repeat the run until it goes green" behaviour `run_evals.py` warns
about at record time, and which now also happens to be the only way past a
real defect.

That is the honest state of it. The uncomfortable part is not that the gate is
wrong; it is that the gate is right and the fix is a milestone away.
