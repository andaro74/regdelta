# RULING, WITH SOURCES — a paused run must not assert an answer

*(Accepted with amendments, 2026-08-23. 3b remains open.)*

> **STATUS: ACCEPTED WITH AMENDMENTS by the human SME seat, 2026-08-23.**
> One proposition was **split and half of it deferred** — see 3a/3b — and one
> was **added**. The accept/reject block at the end records what was decided
> and what was not.
>
> **What acceptance means here, stated precisely.** CLAUDE.md's rule is that
> what makes a ruling sound is **a primary-source citation a reader can falsify
> — never a signature.** So this document is not load-bearing because the seat
> accepted it; it is load-bearing because every claim in it names a source, and
> the seat's acceptance is what authorises the ground-truth edit in line 4 and
> nothing else. A reader who finds a cited source says otherwise should reopen
> it. Say "ruling, with sources", not "approved".
>
> Prepared by `sme-eval-triage` (2026-08-23) and verified against source before
> being put to the seat. `evals/golden_questions.json` is **still unedited** —
> line 4's edit is sequenced after the system fix and has not been made.

## What triggered this

M08's Playwright suite, on its first run against the deployed stack, found that
the `needs-review` scenario **pauses for human review and asserts an answer in
the same response**. Observed twice, identically, on the deployed system.
Recorded at `milestones/M08/README.md` finding 1 and
`evals/history/940af83-playwright.json`.

The response carried `status: needs_input` with review reason *"no product or
label claim to apply a rule to"* — and, beneath the pause banner, a verdict row
reading `real_deadline: 2028-02-25`, `confidence: 0.95`, plus prose reading
*"Yes, you are affected. … Because your company makes a 'healthy' claim, you
must comply with the new criteria."*

The asker's `company_profile` is `{}`. That is not an accident of the run — it
is the scenario's whole purpose (`evals/scenarios.json`: "The empty
company_profile is the point and must not be 'fixed'").

Run 2's card records `cache: miss`, so this is **the graph's current answer, not
a replay from cache**.

---

## Ruling 1 — the invariant

**Proposed: a run that pauses for human review must not assert a compliance
deadline to the asker. This is ground truth, not a test author's preference.**

The basis is **not** the code comment M08 originally cited. A comment can be
edited by the party it constrains. The basis is
`evals/check_discrimination.py:300-310`, which has classified this exact
behaviour since **2026-08-15** (`cf1d3d2`):

```python
(LIMIT_FALSE_PASS, "gate fires but the answer asserts a deadline anyway", (
    "I need more detail about your products. Your compliance date is "
    "February 25, 2028.", "pending_review")),
```

`LIMIT_FALSE_PASS` is defined in that file as **"a WRONG answer that scores PASS
today, knowingly."** So the seat has already ruled that a gate firing alongside
an asserted deadline is a wrong answer; what M08 added is the observation that
**the deployed system now does it**, which is the standard trigger for revisiting
a declared limitation.

Corroborating, weaker: `src/graph/nodes.py:786-788` — *"A question asking whether
something applies to the asker, with no asker in it, cannot be answered at any
confidence."* The deployed run answers it at 0.95.

**If the seat rejects this**, M08's assertion should be retracted and the
`LIMIT_FALSE_PASS` specimen re-labelled, because the two cannot both stand.

---

## Ruling 2 — the merits, as three separate propositions

They are not equally defensible and they do not have the same owner.

### (a) The date — TRUE. No objection.
- **89 FR 106064** (doc. 2024-29957), DATES: *"This rule is effective February
  25, 2025. The compliance date of this final rule is February 25, 2028."*
- **90 FR 10592** (doc. 2025-03118), DATES: the effective date is delayed to
  April 28, 2025 — **effective date only.**

This is q01's trap, correctly held. Nothing here proposes moving it.

### (b) The row — TRUE about the rule, but over-broad and mis-columned.

`product: "All products bearing a 'healthy' claim"` is **over-broad against
existing ground truth.** q09 rules that the rule reaches human food only — its
`must_contain_any` accepts "applies to human food", "pet food is not", and its
`must_not_contain` forbids "yes, reformulate your dog treats". The rule amends
**21 CFR 101.65**, i.e. part 101 human-food labeling; it does not reach animal
food under part 501. "All products" is false as written; "all FDA-regulated
human foods bearing the claim" would be true.

`real_deadline` under a column headed **"Real deadline"** overstates the
obligation. 21 CFR 101.65(d)(3) is permissive — a manufacturer may simply drop
the claim rather than reformulate. **The system's own recorded answers say so**,
which is the falsifiable corroboration: `evals/history/` carries *"the claim
remains voluntary; you are not required to bear it, but if you do, you must meet
the new definition"* and *"…or remove the claim"* in `required_change`. The
prose gets it right and the column does not.

### (c) The prose — FALSE. **This is the correctness bug.**

*"Because your company makes a 'healthy' claim"* asserts a fact about the asker
that the system recorded, one node earlier, that it does not have:
`supervisor` set `profile_sufficient = False` (`src/graph/nodes.py:311-316`).

Under the conduct-based applicability ruling of 2026-08-12 (2024-29957 #0303,
Response 135) — applicability turns on **whether the label bears the claim**,
never on company size — the fabricated fact is the **dispositive** one. Conduct
-based applicability makes this worse, not better.

This is not new. The same sentence appears in
`evals/history/e26d8ef-s3vectors-full.json`.

**Proposed: this is a separate defect with a separate ticket. Suppressing the
table does not fix it.**

### (d) The confidence — the mismatch, not the magnitude.

From one recorded run (`c256b81`, 2026-08-22, all `bypass`, tier `s3vectors`):

| question | profile | status | confidence |
|---|---|---|---|
| q10 "Are we affected…" | none | `needs_input` | **0.95** |
| q18 same question + "shelf-stable lentil soup labeled 'healthy'" | product + claim | `ok` | **0.92** |

**The system is more confident about an asker it knows nothing about than about
one it knows.** The number is honest about the generic proposition; it is
rendered directly beneath a sentence about a specific asker. The defect is the
juxtaposition.

---

## Ruling 3 — the gate is over-firing (3a accepted, 3b deferred)

**Not previously reported anywhere.** In the three most recent recorded full runs
(`e26d8ef`, `95235d9`, `c256b81`), **identically every time**, four golden
questions return `status: needs_input` with the same reason — and all four
score PASS:

| id | tags | question | conf |
|---|---|---|---|
| **q04** | smoke, **trap** | "HHS asked manufacturers to phase out Red No. 3 sooner than 2027. Is that binding on us?" | 0.93 |
| q10 | hitl | "Are we affected by the healthy-claim changes?" | 0.95 |
| q16 | honesty | "Do we have to put a nutrition summary on the front of our package, and by when?" | 0.85 |
| **q19** | timeline, **trap** | "Our supplier says the Red No. 3 order sets no compliance date… Are they right?" | 0.90 |

**The proposed reading: three of these four pauses are wrong on the merits.**
Whether an HHS request is legally binding (q04), and whether a supplier's
reading of an order is correct (q19), are questions **of law and of the
documents**. They need no asker. The trigger appears to fire on the words
"us"/"our" rather than on the question actually requiring a profile. Measured
false-positive rate on that trigger: **3 of 4**.

Two consequences:

1. **It explains the three-milestone blind spot.** If the pause fired only when
   it should, a pause-carrying-an-answer would be visible on one question.
   Because it fires on ordinary questions that then pass on content, the golden
   set has learned to read `needs_input` as noise.
2. **It forbids the obvious fix, today.** `run_evals.flatten_answer` scores
   `answer_rows` + `answer` + `citations` together. If the answer is withheld on
   `needs_input`, **q04, q16 and q19 lose the text they pass on** — three
   REGRESSIONs under `gate_verdict`, **two of them trap questions**. Suppression
   applied first would look exactly like weakening the traps.

### Split at the seat's direction: 3a accepted, 3b deferred

The draft asked the seat to rule, in one line, both that the over-firing is a
defect **and** which three of the four pauses are the wrong ones. Those rest on
different evidence and the seat separated them.

**3a — ACCEPTED, and it rests on observation alone.** The `needs_input` gate
fires on 4 of 20 golden questions, identically across three recorded runs, and
all four score PASS. That warrants investigation, and — the operative part —
**no suppression fix may land until it is resolved**, because
`flatten_answer` scores `answer_rows` + `answer` + `citations` together and
withholding the answer would regress q04, q16 and q19. This is the sequencing
constraint, and nothing about it depends on why the gate fires.

**3b — DEFERRED, pending measurement.** *Which* of q04, q10, q16 and q19
legitimately require a company profile is **not ruled here.** The reading that
the trigger fires on the words "us"/"our" is a hypothesis drawn from reading
recorded outputs; it has not been measured. This document's own open-questions
section names the way to settle it — replay the four stems through
`supervisor()` with raw model output captured — and then the draft asked the
seat to decide without it.

**Ruling before measuring is the specific failure this repository has recorded
twice.** ADR-0005 answered a question, said "verified empirically", and was
wrong, because the observation behind it had two equally good explanations and
nothing had been run to tell them apart. `milestones/M07/eval-gate-flake-gap.md`
records three successive misdiagnoses made before anyone read the metrics, and
carries a warning at its top not to lift its candidate fixes out of it. A
fourth instance, in a ruling document, would be the same defect wearing the
authority of a seat decision.

3b is answered in an addendum to this file once the probe has run. The probe is
one `MODEL_FAST` call per question, no retrieval and no verdict model, and it
blocks nothing else.

---

## Ruling 4 — q10's guard

**Proposed: q10's expected answer is UPHELD. Its guard is incomplete.**

Nothing about q10's ground truth is wrong. `expect_status_any:
[pending_review, needs_input]` is correct and stands.

**One correction to how M08 framed this.** M08 asked whether q10's guard "should
assert on `answer_rows` at all". **It already does** —
`run_evals.flatten_answer` folds `json.dumps(answer_rows)` into the same string
`must_not_contain` is scored against. The guard's *scope* is fine. Only its
*needle* misses: `"you must comply by"` against the model's actual
`"you must comply with the new criteria"` plus `real_deadline: 2028-02-25`.

**Proposed action — a strict tightening, never a weakening:**

1. Add date-bound needles to q10's `must_not_contain`: `"2028-02-25"` and
   `"February 25, 2028"`. Bound to the *date* rather than to a phrasing, because
   phrasing is what the current needle got wrong.
2. Amend q10's `note` to record the limitation. Today it reads only
   *"Deliberately underspecified: no company profile. Expected: pending_review
   or explicit request for profile."*

**Sequencing is part of the proposal, not an afterthought: this lands AFTER the
system fix, or it turns q10 red and blocks merges for a defect it did not
cause.**

**Adoption condition, per the 2026-08-15 process rule:** every proposed token is
replayed through the real `run_evals.check()` — including against
`check_discrimination.py`'s CORRECT specimen for q10 (*"I need to know what
product you make and what claims its label bears…"*) — **before** it is written
to the file. A token that fails the correct answer is a worse defect than the
one it fixes. Testing the oracle before trusting it is the point; a guard that
rejects a good answer is how a tightening becomes a regression.

**Recorded limitation of this tightening.** It hardens q10 and only q10. If
q04, q16 and q19 keep pausing (3a), the same defect stays undetected on those
three, because each carries its own `must_not_contain` list and none of them
carries a date needle. Generalising the guard — asserting the invariant on
every question that can pause, rather than question by question — is the right
end state and is **deferred to 3b's resolution**, because which questions may
legitimately pause is exactly what 3b decides.

### Two book-keeping defects, worth fixing whatever the seat decides

- `check_discrimination.py:580` prints *"known limitation, documented in the
  question's note"* **unconditionally** — it is a format string, not a check.
  **q10's note documents no such limitation.** The instrument asserts a
  documentation link that does not exist.
- `golden_questions.json`'s `_scoring_ruling.scope` says **"q10 unchanged
  (clean)"** and "After this ruling: 4 declared limitations, nothing
  undeclared." The q10 `LIMIT_FALSE_PASS` specimen was added in `cf1d3d2` on
  **2026-08-15 — the same day as that ruling.** So the scope line was **wrong
  when written**, not stale. Dated with `git log -L 300,310`.

---

## Recommendation on ownership — ENG SEAT'S CALL, with one domain input

The domain question is *what is the reviewer actually reviewing?* — and the
answer differs by door (`src/graph/nodes.py:892-936`, verified):

| status | `needs` | what resume does | is the draft reviewed? |
|---|---|---|---|
| `needs_input` | `company_profile` | `_resume_with` sets `profile_sufficient=True`, `status="resumed"`; the conditional edge sends the run **back through retrieval** and re-synthesises | **No — the draft is discarded** |
| `pending_review` | `reviewer_decision` | `approve` → `status: ok`, **releasing the existing answer** | **Yes — the draft IS the subject** |

So the "we would lose the draft a reviewer wants" objection **does not apply to
this scenario**. On the `needs_input` path the draft is thrown away regardless.

Proposed order:

1. **The supervisor first** (`src/graph/nodes.py:282-321`). Prerequisite, not a
   parallel workstream — see Ruling 3.
2. **Then the graph, for `needs_input` only.** Do not synthesise once
   `profile_sufficient` is false. **Do not extend this to `pending_review`,**
   where the draft is the reviewed artifact.
3. **Then `_shape`, for `pending_review`.** A draft answer on an
   unauthenticated `/query` belongs to the reviewer, not to an anonymous caller.
4. **The page last, and never alone.** A page-only fix leaves `/query` handing
   an unasserted answer to every non-browser caller, and is **invisible to every
   instrument in this repo** — `run_evals` reads the API body, not the DOM.

**A gap this exposes, worth its own ticket:** `write_review_item`
(`src/graph/checkpoint.py:114-124`) persists `status`, `reason`, `question`,
`needs`, `opened_at`, `ttl` — it **drops `draft_answer`**. So the SME staffing
the HITL queue (ROLES.md) cannot see the draft from the queue at all. The
"preserve the draft for the reviewer" argument currently defends a capability
the review queue does not have.

---

---

## Ruling 6 — ADDED at the seat's direction: the prose defect needs an oracle

**Proposed and accepted: 2c does not close without a regression test.**

As originally drafted this document gave the *table* defect an assertion (the
Playwright spec) and a guard (q10's needles), and gave the *prose* defect a
ticket and nothing else. **A defect with no oracle is a defect that returns** —
and this one has already survived three milestones unnoticed, which is the
empirical case rather than the theoretical one.

The check does not need to be expensive or clever: when `profile_sufficient` is
false, the answer text must not assert the asker's conduct in the second
person. It belongs in the same family as the existing specimens in
`evals/check_discrimination.py`, which is where behaviour of this kind is
already declared, and it costs no model call to run.

Scoped deliberately narrowly: this is an oracle for **the fabricated premise**,
not a general hallucination detector. The wider question — what the system may
say about an asker it knows nothing about — is a domain question and is not
opened here.

---

## What this document does NOT rule

- **No trap question is touched.** q01–q04 unchanged, and nothing here proposes
  moving any expected answer, required date, or citation requirement.
- **M08's dropped-citation observation** (the deployed answer reached for
  21 CFR 101.65(d), 101.13(b)(2)(ii), 101.65(a)(2), which the sources did not
  carry) is **not ruled here.** The guard worked — it became a banner. What is
  unruled is the acceptance bar for a non-zero `dropped_citations` on a canned
  demo scenario, and a related collision: **q18's `must_cite_any` accepts
  `"21 CFR 101.65"`**, a section the retrieved sources may not support. Its own
  ticket.
- **Whether SPEC/04 should gain an explicit suppression clause.** PM seat.

## What would settle the remaining uncertainty

1. **Why does the supervisor mark q04/q16/q19 insufficient?** Replay the four
   stems through `supervisor()` alone with raw model output captured. One
   supervisor call each — no full graph runs, negligible cost. Tells us whether
   the prompt or the classifier is at fault before anyone edits either.
2. **Does the deployed prose still carry the voluntariness caveat?** The
   Playwright card records only the instruments and the failing assertion, not
   `body.answer`. Capturing the full prose on the next `needs-review` run costs
   nothing extra and decides whether the prose defect is "fabricated premise"
   or "fabricated premise plus dropped caveat".

---

## Sources a reader can falsify

- [89 FR 106064 / doc. 2024-29957](https://www.federalregister.gov/documents/2024/12/27/2024-29957) — compliance date February 25, 2028
- [90 FR 10592 / doc. 2025-03118](https://www.federalregister.gov/documents/2025/02/25/2025-03118) — effective date delayed to April 28, 2025, compliance date unchanged
- [21 CFR 101.65](https://www.ecfr.gov/current/title-21/section-101.65) — the amended section; part 101 is human-food labeling
- 2024-29957 #0303, Response 135 — conduct-based applicability (per the 2026-08-12 q07 ruling)
- `evals/check_discrimination.py:300-310` — the `LIMIT_FALSE_PASS` specimen, added `cf1d3d2` 2026-08-15
- `evals/run_evals.py` — `flatten_answer`, `gate_verdict`
- `src/graph/nodes.py` — supervisor 282-321, `_needs_review` 781-830, `hitl_gate` 857-904, `_resume_with` 907-936
- `src/graph/checkpoint.py:89-124` — `write_review_item`
- `evals/history/c256b81-s3vectors-full.json` — q04, q10, q16, q18, q19
- `evals/history/940af83-playwright.json` — the M08 observation, `cache: miss`

---

## Decision — HUMAN SME SEAT, 2026-08-23

Each line was separately decided. The seat accepted the propositions below,
**split proposition 3**, and **added proposition 6**.

| # | proposition | decision | seat's note |
|---|---|---|---|
| 1 | A paused run must not assert a compliance deadline to the asker. Ground truth. | **ACCEPTED** | Rests on `check_discrimination.py:300-310`, which has classed this a wrong answer since 2026-08-15 — not on a code comment. Two artifacts cannot disagree about whether a behaviour is acceptable; rejecting would have obliged the seat to relabel that specimen and affirmatively decide a pause may ship a deadline. |
| 2c | The prose asserting the asker's conduct is a **correctness** defect, separately ticketed from the table. | **ACCEPTED** | Different root cause, different fix site, different severity. Merged into one ticket, the suppression fix would close it while the fabricated premise ships unchanged through the `pending_review` door. |
| 2b | "All products bearing a 'healthy' claim" is over-broad against q09's human-food boundary. | **ACCEPTED AS AN OBSERVATION** — no work item opened | Plausibly a *symptom* of 1's root cause: the row is over-broad because there is no asker to narrow it to, so it may not survive the fix. Verify after; open work only if it does. Recorded now so nobody later "fixes" the row generically. |
| **3a** | The gate firing on 4 of 20 is a defect worth investigating, and **no suppression fix may land until it is resolved.** | **ACCEPTED** | Rests on observation alone — three recorded runs, identical. The regression arithmetic (`flatten_answer` + `gate_verdict`) does not depend on *why* the gate fires. |
| **3b** | Of q04, q10, q16, q19, **only q10** legitimately requires a company profile. | **DEFERRED** — pending the `supervisor()` probe | Split out of 3 by the seat. The "fires on us/our" reading is an unmeasured hypothesis, and this file already names the probe that settles it. ADR-0005 and `milestones/M07/eval-gate-flake-gap.md` are what a ruling-before-measuring costs here. |
| 4 | q10's expected answer is **upheld**; its guard gains date-bound needles and a note, **after** the system fix, replayed through `check()` first. | **ACCEPTED** | Uphold the behaviour, strengthen the oracle — the only safe direction. Bind to the date, not to a phrasing, because a phrasing is what the current needle got wrong. Generalising it to the other pausing questions waits on 3b. |
| 5 | The two book-keeping defects (`check_discrimination.py:580`'s unconditional print; the "4 declared limitations / q10 clean" scope line) are corrected. | **ACCEPTED** — and **not filed as minor** | An instrument that prints "documented in the question's note" unconditionally is a **false attestation**: tooling that manufactures confidence, which every downstream reader trusts. The audit trail is itself a deliverable here. |
| **6** | The prose defect (2c) does not close without a regression oracle. | **ACCEPTED** — added by the seat | A defect with no test is a defect that returns, and this one already survived three milestones. Narrow scope: the fabricated premise, not hallucination in general. |

**Seat:** the human seat of this repository (ADR-0005: one human, no gate is
mechanically enforced) · **Date:** 2026-08-23

**What this acceptance authorises, exactly:** the ground-truth edit in line 4,
sequenced after the system fix and replayed through `check()` first — **and
nothing else.** It does not authorise any change to a trap question, any change
to an expected answer, or any code change; the system fix is the engineering
seat's, ordered per the recommendation above. **`evals/golden_questions.json`
remains unedited as of this document's acceptance.**

**Open against this ruling:** 3b, which is answered by addendum once the probe
has run.


---

# ADDENDUM — 3b, measured. **DRAFT: awaiting the human SME seat.**

> Ruling 3b was deferred pending measurement. The probe has run
> (`milestones/M09/supervisor_probe.py`, raw output in
> `supervisor-probe.json`, 18 `MODEL_FAST` calls, no Opus, no retrieval).
> **This addendum is a draft. 3b is not ruled until the block at the end is
> filled in.** The deferral was worth it: the measurement does not support the
> hypothesis the original draft asked the seat to accept.

## What the probe found

`supervisor()` alone, three calls per question, raw model output captured.

| id | control | stable | `profile_sufficient` | `claims` the model extracted |
|---|---|---|---|---|
| q04 | | yes | **false** | `[]` |
| q10 | | yes | **false** | `['healthy']` |
| q16 | | **NO — 2 false, 1 true** | — | `['nutrition summary', 'front of package nutrition label']` |
| q19 | | yes | **false** | `[]` |
| q18 | ✓ | yes | true | — |
| q01 | ✓ | yes | true | — |

**Both controls held.** q18 — q10's twin, with a product and a claim in the
question text — came back sufficient every time, and q01 likewise. So the
classifier is not broken generally, and the four-question reading has a real
subject. Had q18 failed, nothing else in this table could have been read.

**H3 is ruled out.** Every raw output parsed and every one carried the
`profile_sufficient` key. No verdict here is a parser fallback; each is the
model's own judgement.

## The original hypothesis does not survive

The draft's reading was *"the trigger fires on the words us/our"*. **q19
refutes it as a general explanation.** q19 asks *"Our supplier says … Are they
right?"* — it asks whether the **supplier's reading of a document** is correct,
not whether anything applies to the asker. The first-person pronoun is
incidental. Yet it pauses stably.

More importantly, the pronoun theory cannot explain **q10 and q16 at all**, and
what those two show is a different mechanism.

## The mechanism, from the prompt

`_SUPERVISOR_PROMPT` (`src/graph/nodes.py`) asks for a `claims` array described
as `"<label claim at issue, e.g. healthy>"`, and then rules:

> `profile_sufficient` is false ONLY when the question asks whether something
> applies to the asker but names no product and no label claim to apply it to.
> **A question that names a product or a claim IS sufficient** …

**q10 extracted `claims: ['healthy']` and returned `profile_sufficient: false`
anyway.** By the prompt's own stated rule that is a contradiction — a claim was
named, so it should be sufficient. The model is not misreading the rule; it is
resolving an ambiguity the rule does not address:

> **"names a claim" is ambiguous between "the asker's label bears this claim"
> and "this is the claim the rule is about".**

"Are we affected by the healthy-claim changes?" names `healthy` in the second
sense only. The model's judgement is **right**, and the prompt's literal rule is
**wrong** — which is H1, a prompt defect, not H2.

**q16 is the same ambiguity, caught mid-flip.** It extracted `['nutrition
summary', 'front of package nutrition label']` — the *regulatory subject*
classified as a "claim" — and then returned false, true, false across three
identical calls. **The classifier is unstable exactly where the prompt is
ambiguous**, which is the signature of an under-specified instruction rather
than an unreliable model.

**q04 and q19 are a second, separate defect.** Both extracted nothing, so the
"names no product and no claim" half is satisfied; what licenses the pause is
the first half, *"asks whether something applies to the asker"*. q04
(*"Is that binding on us?"*) satisfies that literally. q19 does not — it asks
whether a third party's reading is correct. So:

- **q04 = H1.** The prompt has no way to express *"this is a question of law
  about a document, and needs no asker at all"*. A question of law phrased in
  the first person reads as an applicability question under the current
  wording.
- **q19 = H2.** The model misapplied the first clause. Stable across three
  calls, so not noise.

## Proposed classification — FOR THE SEAT

| id | pauses? | proposed | why |
|---|---|---|---|
| **q10** | yes | **CORRECT — keep the pause** | Genuinely asks whether the rule reaches the asker, with no asker in it. The model's `false` is right; only the prompt's stated rule is wrong. |
| **q16** | unstable | **CORRECT to pause, for the wrong reason** — and the instability is its own defect | "Do we have to put a nutrition summary on **our package**" does ask about the asker with no product named. But a classifier that answers differently on identical input is a defect regardless of which answer is right. |
| **q04** | yes | **WRONG — should not pause** | Whether an HHS *request* is legally binding is a question of law. It is answerable with no asker, and it is a **trap** question: the trap is the request/rule distinction, and a pause sidesteps it. |
| **q19** | yes | **WRONG — should not pause** | Asks whether the supplier's reading of the order is correct. A question about a document. Also a **trap** — the trap is that an order with no compliance date still has an operative deadline derived from the effective date (ADR-0006). |

**So the original draft's count was right (3 of 4 wrongly, or 2 wrong + 1
unstable) and its reason was wrong.** The fix is not "stop firing on us/our".
It is two changes with different characters:

1. **Disambiguate `claims`** — separate "a claim the asker's label bears" from
   "the claim the rule is about". This is what q10 and q16 turn on, and it is
   the change that makes the classifier stable.
2. **Give the prompt a way to say "no asker needed"** — a question of law about
   a document is not an applicability question, whatever pronoun it uses. This
   is what q04 and q19 turn on.

Both are prompt changes in `src/graph/nodes.py`, both are engineering-seat work,
and **neither touches a golden question.**

## What this addendum does NOT claim

- **It does not measure the fix.** These are the classifier's verdicts under
  today's prompt. Whether a rewritten prompt fixes q04 and q19 without
  regressing q18, q01 or q10 is a re-run of this same probe, and it must be run
  before any prompt change is called done.
- **q16's instability is unquantified.** Three calls found 2:1. That is enough
  to establish instability and not enough to rate it. The probe takes `--runs`.
- **It says nothing about the answers themselves** — only about the
  classification that precedes them.

## Decision — 3b, FOR THE HUMAN SME SEAT

| # | proposition | decision | note |
|---|---|---|---|
| 3b-i | **q10 pauses correctly.** | | |
| 3b-ii | **q04 and q19 should not pause** — both are questions of law, both are trap questions, and a pause sidesteps the trap. | | |
| 3b-iii | **q16 should pause on its merits, and its 2:1 instability is a separate defect** worth its own fix regardless. | | |
| 3b-iv | The remedy is **two prompt changes** — disambiguate `claims`, and admit "no asker needed" — verified by re-running this probe, with q18/q01 as regression controls. **No golden question is edited.** | | |

**Seat:** ______________________  **Date:** ______________

Until 3b is decided, **ruling 3a still stands and still blocks**: no
suppression fix may land, because q04, q16 and q19 currently pass on text that
suppression would remove.
