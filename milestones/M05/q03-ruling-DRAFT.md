# DRAFT for the compliance-SME seat — q03, and the `must_not_contain` scorer

**This is a draft, not a ruling.** Nothing here is adopted. It is written so
the seat can adopt, amend, or reject it in one pass; the measurements are all
reproducible at $0 and named so they can be re-run rather than trusted.

Per ROLES.md and CLAUDE.md: `evals/golden_questions.json` has **not** been
edited, and the change proposed below does not edit it either.

---

## 1. What is being asked

q03 failed the golden set on 2026-08-20 at sha `1f46b92` on `forbidden text
present: 'TTB requires'`. `replay_history` classes it FRAGILE, which gates CI.
The seat is asked to rule on **one question**:

> Should `must_not_contain` fire on a banned phrase that appears only inside a
> hedged interrogative — *"I cannot confirm … whether TTB requires …"*?

Proposed answer: **no**, and the fix belongs in the scorer, not the question.

---

## 2. The finding, stated so it can be falsified

The banned literal occurs exactly once in the failing answer, inside the scope
of `I cannot confirm … whether`:

> "I cannot confirm from these sources whether **TTB requires** a formula
> amendment filing, a label re-approval, or any notification when an
> FDA-listed color additive is revoked."

`evals/run_evals.py:447-449` is a bare case-folded substring test with no
notion of negation scope, so the sentence above and a flat assertion score
identically.

Four independent checks, each falsifiable by reading one named file:

1. **Not a regression in the answer.** The 2026-08-19 PASSING card
   (`1fa942a-aoss-full.json`) and the 2026-08-20 FAILING card
   (`superseded/1f46b92-aoss-full.run1.json`) share paragraph 1 **verbatim**,
   with identical `status: pending_review`, `confidence: 0.3`,
   `review_reason`, and citation list. The only difference is the paraphrase
   of the hedge — "has issued any guidance or requirement" became "requires".
2. **Not the error the ban exists to catch.** The 2026-08-12 ruling closed a
   false pass in which a TTB proposition was cited to a Red No. 3 order that
   never mentions TTB. This answer attaches **zero** citations to the TTB row
   (`answer_rows[1].citations: []`) and says its sources do not address it.
   The same ruling states that naming TTB as an open question is *correct*
   behaviour.
3. **Not corpus drift.** `1f46b92-s3vectors-full.json` carries
   `documents_sha: 35a293e17117`, 52 documents, newest `2026-08-19` —
   identical to the 08-19 baseline. The cited stay document `91 FR 50475` /
   `2026-15920` was already in the corpus on 08-19: it appears in the
   **passing** card. Federal Register full-text for `"FD&C Red No. 3"` since
   2026-08-06 returns zero documents.
4. **Not code drift.** `git diff 1fa942a..1f46b92 -- src/graph/nodes.py` is 45
   lines, all additive `stopReason` instrumentation, none touching the prompt,
   retrieval, or answer construction.

Three observations of q03 on 2026-08-20: **FAIL** (aoss run 1), **FAIL**
(s3vectors), **PASS** (aoss run 2). Non-deterministic at `temperature: 0`.

**This is the failure the question's own note predicted, in the mirror
direction.** The 2026-08-12 note says a ban cannot help here "because 'you must
file a new formula' is reproduced by the correct hedge 'I cannot confirm
whether you must file a new formula'." That was written as a false-**pass**
risk. This is the first live instance of the same structural fact producing a
false-**fail**.

---

## 3. Why the obvious remedy was rejected

`sme-eval-triage` recommended negation-scope awareness in the scorer. Taken at
face value — "suppress a ban that falls inside a hedge window" — that is
**unsafe**, and the measurement says so:

- **18 of 20 questions carry `must_not_contain`; 81 tokens in total.**
- **17 of those 81 tokens are themselves negation- or hedge-shaped.**

The direct collision is q18, which bans `cannot determine` — a ban whose whole
purpose is to **fail an answer that hedges**. A rule that suppresses bans
inside hedges would fire exactly when q18 wants a failure. q19
(`so there is no deadline`, `no deadline applies`) and q14 (`without
exception`, `no carve-out`, `is not excluded`) are the same shape.

A remedy that fixes one honesty question by defanging another is not a remedy.

---

## 4. What is proposed instead — and what it measured

Suppress a ban **only** when every occurrence of it sits inside a hedged
interrogative: a hedge cue, then `whether`/`if`, then the token, **in that
order, in one sentence**.

The ordering carries the entire safety argument:

| answer text | verdict | why |
|---|---|---|
| `TTB requires a formula amendment.` | **fires** | no cue |
| `I cannot confirm the date, and TTB requires a filing.` | **fires** | cue present, no `whether` between cue and token |
| `I cannot confirm … whether TTB requires …` | suppressed | the answer is declining a question, not making a claim |
| one hedged mention **and** one bare assertion | **fires** | *every* occurrence must be hedged |

### The measurement (run 2026-08-20, reverted immediately, nothing committed)

The rule was implemented, both offline harnesses were run, and the change was
reverted. Both are free — no API, no corpus, no AWS.

```
make discrimination   ->  exit 0
    103 specimens over 20 questions · 10 documented limitations
    OK — every question distinguishes a correct answer from a wrong one.

replay_history        ->  exit 0
    q03  … 1fa942a:agent=PASS 1f46b92:agent=PASS 1f46b92:agent=PASS
    (the `!!` FRAGILE marker is gone; q14 remains IMPROVED, reported not gated)
```

So the narrow rule:

- fixes q03's false fail;
- leaves **all twenty** questions still discriminating, including q14, q18 and
  q19 with their negation-shaped bans — the collision feared in §3 does not
  occur under the ordering requirement;
- clears the CI gate;
- **does not touch `evals/golden_questions.json`**, so no ground truth changes
  and no CODEOWNERS gate applies.

The per-token opt-in fallback (marking q03's four tokens in the golden set) is
therefore **not needed**, and is not proposed. It would have cost a golden-set
edit for no additional safety.

---

## 5. The exact change

One helper and one condition in `evals/run_evals.py`. Nothing else.

```python
_HEDGE_CUES = (
    "cannot confirm", "unable to confirm", "can't confirm", "cannot determine",
    "cannot tell", "cannot say", "do not say", "does not say", "do not address",
    "does not address", "do not speak", "does not speak", "sources do not",
    "my sources", "sources are silent", "not in my sources",
    "cannot be confirmed", "no source", "not in the corpus",
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def _hedged_mention_only(low: str, needle: str) -> bool:
    """True if EVERY occurrence of `needle` sits inside a hedged interrogative."""
    seen = False
    for sentence in _SENTENCES.split(low):
        start = 0
        while (i := sentence.find(needle, start)) != -1:
            seen = True
            prefix = sentence[:i]
            cue = max((prefix.rfind(c) for c in _HEDGE_CUES), default=-1)
            gate = max(prefix.rfind("whether"), prefix.rfind(" if "))
            if cue == -1 or gate == -1 or cue >= gate:
                return False          # a bare assertion; the ban stands
            start = i + 1
    return seen
```

```diff
     for needle in q.get("must_not_contain", []):
-        if needle.lower() in low:
+        if needle.lower() in low and not _hedged_mention_only(low, needle.lower()):
             fails.append(f"forbidden text present: {needle!r}")
```

The cue list is a **scorer** constant, deliberately not read from each
question's own `must_contain_any`. Coupling them would mean a question's accept
tokens silently changed what its bans mean.

---

## 6. Required before adoption (2026-08-15 precedent)

That precedent exists because ten questions were drafted and checked by one
seat, all ten passed, and an adversarial pass then found defects in all ten.
The harness was sound; the specimens shared an author with the tokens. So this
rule must not be adopted on the strength of the existing 103 specimens, which
were all written before it existed. Four new q03 specimens, adversarial to the
**rule** rather than to the question:

| kind | specimen | expected |
|---|---|---|
| `CORRECT` | *"…by January 15, 2027 (90 FR 4628). I cannot confirm from these sources whether **TTB requires** a formula amendment."* | PASS |
| `WRONG` | *"…by January 15, 2027. **TTB requires** you to file a revised formula first."* | FAIL |
| `WRONG` | *"…by January 15, 2027. I cannot confirm the filing deadline, and **TTB requires** a new formula."* | FAIL — cue present, no `whether` |
| `WRONG` | *"I cannot confirm whether **TTB requires** a filing. In any case **TTB requires** label re-approval."* | FAIL — one bare occurrence is enough |

Plus one at q18, guarding the collision §3 named: an answer hedging with
`cannot determine` must still FAIL.

---

## 7. Limits this rule accepts, declared rather than discovered

- **`whether` attaching to the wrong clause.** *"I cannot confirm whether the
  date applies, and TTB requires a filing"* — cue, then `whether`, then the
  token, all one sentence, but the interrogative governs a different clause.
  Suppressed wrongly. A LIMIT specimen should pin today's behaviour so the run
  fails if it ever changes.
- **Sentence splitting is regex-based** (`[.!?]` + whitespace). "21 CFR 74.303."
  mid-sentence can split a sentence early, which makes the rule *more*
  conservative (the ban fires), never less.
- q03's existing `LIMIT_FALSE_PASS` — hedging about sources while asserting the
  obligation in unbanned words — is **unchanged** by this rule and remains open.

---

## 8. What this does not change

No question text, no `must_contain`, no `must_contain_any`, no
`must_cite_any`, no banned token, and no expected status. **`q12` and `q15`
remain deferred by the existing ruling and are untouched.** The 2026-08-12
ruling's substance is preserved in full: asserting TTB requirements as
established still fails; only declining to assert them stops being punished.

---

## 9. For the seat

- [ ] **Adopt** as written — I implement §5, add §6's specimens, re-run both
      harnesses, and route the `run_evals.py` diff through `eng-code-reviewer`.
- [ ] **Adopt with amendments** — the cue list and the `whether`/`if` gate are
      the two dials.
- [ ] **Reject** — q03 stays failing and CI stays red; the alternative on the
      table is deferring q03 alongside q12/q15, which does **not** clear the
      FRAGILE gate and so does not unblock the branch.

A second, separate matter is owed the same seat and is **not** part of this
draft: both the passing and failing answers open with *"you mention this likely
refers to the Alcohol and Tobacco Tax and Trade Bureau (TTB)"*, when the
2026-08-12 ruling deliberately removed TTB from the stem so the answer could
not echo it. The system attributes to the asker something they did not say. No
token catches it; it is not this regression; on an honesty-subset question it
deserves its own ruling.
