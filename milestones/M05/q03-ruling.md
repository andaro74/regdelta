# SME-seat ruling 2026-08-20 — q03, and the `must_not_contain` scorer

**ADOPTED BY THE SEAT. IMPLEMENTED, REVIEWED, AND REVERTED THE SAME DAY.**

The seat ruled "adopt with amendments" and the amendments were applied. The
implementation then **failed engineering review**: it created four reproducible
FALSE PASSES, one of which is the exact bug q03's ban exists to prevent — a
fabricated TTB obligation, asserted flatly, scored PASS. The scorer is back to
its pre-ruling behaviour. §10 has the reproductions.

**The seat's ruling on the SUBSTANCE stands and is not in question**: q03's
failure is a false fail, the ban is right, the question is right, and the fix
belongs in the scorer rather than in ground truth. What failed is my
*implementation* of that ruling — a substring-and-window heuristic — not the
ruling itself. §10 sets out what the seat now has to decide.

Per ROLES.md and CLAUDE.md: `evals/golden_questions.json` was never edited, and
is not edited now.

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

**CORRECTION, 2026-08-20.** The paragraph that stood here read "the collision
feared in §3 does not occur under the ordering requirement," on the strength of
that clean `make discrimination` run. **That was wrong**, and the clean run did
not support it: no specimen in the 103 had the collision's shape, so the
harness could not have caught it either way. Probing the shape directly after
implementation found it live —

> "You are affected, but I cannot confirm whether the rule applies, so I
> cannot determine your deadline."

q18 bans `cannot determine` and wants that answer to FAIL; the rule suppressed
the ban, because a `whether` belonging to a **different clause** sat between an
unrelated cue and the token. q14 and q19 are reachable the same way. This is
the 2026-08-15 failure mode exactly: specimens written before a rule cannot be
adversarial to it, and a green run over them proves only that the rule did not
break what was already there.

Fixed by the third amendment in §9 (`whether` must GOVERN the token, not merely
precede it). With all three amendments applied and the five new specimens
added:

```
make discrimination   ->  exit 0   108 specimens over 20 questions
replay_history        ->  exit 0   q03's `!!` FRAGILE marker gone
pytest                ->  956 passed, 1 skipped, 0 failed
```

So the rule as adopted:

- fixes q03's false fail;
- leaves all twenty questions still discriminating, **and** now carries a
  specimen for the collision so it cannot come back silently;
- clears the CI gate;
- **does not touch `evals/golden_questions.json`**.

The per-token opt-in fallback (marking q03's four tokens in the golden set) is
not needed and was not adopted: the seat chose global scope in §9.

---

## 5. The exact change

One helper and one condition in `evals/run_evals.py`. Nothing else.

```python
_HEDGE_CUES = (
    "cannot confirm", "unable to confirm", "can't confirm", "cannot determine",
    "cannot tell", "cannot say", "do not say", "does not say", "do not address",
    "does not address", "do not speak", "does not speak", "sources do not",
    "sources are silent", "not in my sources", "cannot be confirmed",
)
# Regex-based, and that is safe in one direction only: an abbreviation like
# "21 CFR 74.303." splits a sentence early, which can only STRAND a cue from
# its token and make the ban fire. It cannot merge two sentences into one.
_GATE_WINDOW_WORDS = 3
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def _hedged_mention_only(low: str, needle: str) -> bool:
    """True if EVERY occurrence of `needle` sits inside a hedged interrogative.

    Returns False the moment one bare occurrence is found, so an answer that
    hedges once and asserts once still fails the ban. Returns False for a
    needle that does not occur at all, which the caller never asks about.
    """
    seen = False
    for sentence in _SENTENCES.split(low):
        start = 0
        while (i := sentence.find(needle, start)) != -1:
            seen = True
            prefix = sentence[:i]
            cue = max((prefix.rfind(c) for c in _HEDGE_CUES), default=-1)
            gate = prefix.rfind("whether")
            if cue == -1 or gate == -1 or cue >= gate:
                return False          # a bare assertion; the ban stands
            between = prefix[gate + len("whether"):].split()
            if len(between) > _GATE_WINDOW_WORDS:
                return False          # the `whether` governs a different clause
            start = i + 1
    return seen
```

```diff
     for needle in q.get("must_not_contain", []):
-        if needle.lower() in low:
+        if needle.lower() in low and not _hedged_mention_only(low, needle.lower()):
             fails.append(f"forbidden text present: {needle!r}")
```

The block above is the code **as shipped**, with all three amendments applied —
not the version this section proposed before the seat ruled. The long rationale
comment that accompanies it in `evals/run_evals.py` is not reproduced here.

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

## 9. The ruling as adopted

Selected by the seat, 2026-08-20: **Adopt with amendments.**

| # | Amendment | Effect | Authorised |
|---|---|---|---|
| 1 | Cue list holds only explicit first-person disclaimers. `my sources`, `no source`, `not in the corpus` dropped — they match as bare noun phrases ("my sources include…") rather than as refusals. 16 cues remain. | tightening | seat |
| 2 | The gate is `whether` alone. ` if ` dropped as too common a word to carry the interrogative weight the rule rests on. | tightening | seat |
| 3 | `whether` must **govern** the token: at most `_GATE_WINDOW_WORDS` (3) between them. | tightening | **not authorised — see below** |

**Amendment 3 was not asked for, and is flagged rather than folded in.** It was
found by probing after implementing 1 and 2: the collision §3 feared was still
live, because a `whether` in an unrelated clause could reach across and
suppress a ban. "whether TTB requires" has nil words between; "whether the rule
applies, so I cannot determine" has five and now fires.

It moves in the same direction as the seat's own two amendments — a tightening
can only make a ban fire **more** often, so it cannot create a false pass, and
the worst case is a hedge that gets failed. Shipping the rule without it would
have put a known false pass into the honesty questions, which is why it is in
the code; leaving it undocumented would have been substituting my judgement for
the seat's, which is why it is here. **One word reverses it.**

### Verification performed

- `make discrimination` — 108 specimens over 20 questions, exit 0.
- Both mutations killed by the specimen written for them: removing amendment 3
  turns the q18 collision specimen into a **FALSE PASS**; removing the rule
  entirely turns q03's hedged specimen into a **FALSE FAIL**.
- `replay_history` exit 0; q03's FRAGILE marker gone.
- Full suite 956 passed, 1 skipped, 0 failed. Lint clean.
- `eng-code-reviewer` on the `run_evals.py` diff, per §6.

### Still owed the same seat, separately

A second, separate matter is owed the same seat and is **not** part of this
ruling: both the passing and failing answers open with *"you mention this likely
refers to the Alcohol and Tobacco Tax and Trade Bureau (TTB)"*, when the
2026-08-12 ruling deliberately removed TTB from the stem so the answer could
not echo it. The system attributes to the asker something they did not say. No
token catches it; it is not this regression; on an honesty-subset question it
deserves its own ruling.

---

## 10. Why the implementation was reverted

`eng-code-reviewer`, run on the implementing commit as §6 requires, reproduced
four false passes end-to-end through `run_evals.check()` against the live
golden set. I re-ran all four before acting; all four reproduced.

| # | Shape | Question | Result |
|---|---|---|---|
| B1 | **Concessive `whether`** — `"…but whether exempt or not, TTB requires a revised formula."` The clause after a concessive `whether` is a flat assertion, and it fits inside the 3-word window. | q03, q14 | **FALSE PASS** |
| B2 | **A repeated needle self-satisfies its own window** — the first, hedged occurrence's text *is* the `between` window for the second. "Hedge once, assert once **in the same sentence**" was suppressed, contradicting the helper's own docstring. | q03, q19 | **FALSE PASS** |
| B3 | **The §3 collision was never closed, only narrowed** — `"I cannot say whether I cannot determine your date…"` reaches q18's ban by a *different* cue. | q18 | **FALSE PASS** |
| B4 | **The scorer reads a JSON blob, not prose** — `flatten_answer` returns `json.dumps(answer_rows) + answer + citations`, and JSON separators contain no `[.!?]`, so the whole rows array is ONE sentence. A hedge in one field governs a token in another field of another row. | q03 | **FALSE PASS** |

B1 is the one that settles it: a fabricated TTB obligation, stated as fact,
scoring PASS. That is the precise defect the 2026-08-12 ruling closed, and this
implementation reopened it.

### The claim of mine that was wrong

I wrote, in code and to the seat, that *"a tightening can only make a ban fire
MORE often, so it cannot create a false pass."* That is true of **amendment 3
in isolation** and false of **the rule**, which is a loosening — it can only
make bans fire LESS. I conflated the increment with the whole and reported the
increment's safety as the rule's. The seat adopted on that basis.

### Why the specimens did not catch it

They were written **after** the rule but **by the rule's author**, and they
trace the four paths the rule was designed to handle. That is the same failure
as the 2026-08-15 one it was written to avoid, one level up. The shapes I did
not write: same-sentence hedge-then-assert separated by `;`, concessive
`whether … or not`, the token inside `answer_rows`, and a boundary specimen at
exactly four words — without which `_GATE_WINDOW_WORDS` was never pinned at all
(review measured: the harness passes for every window from 0 to 8).

### What is kept

The five specimens stay. Four are good specimens against the bare substring
test as well, and the q18 collision specimen becomes a **standing guard**: any
future attempt at negation scope must keep it FAILING. q03's hedged answer is
now a declared `LIMIT_FALSE_FAIL`, which is the repo's own mechanism for a
correct answer that knowingly scores FAIL — the defect is recorded rather than
hidden.

### What the seat now has to decide

CI is red again on the q03 FRAGILE gate, which is the honest state: a **visible,
gated false fail** in place of four invisible false passes.

1. **Accept the false fail and defer q03** alongside q12 and q15. Costs: the
   FRAGILE gate stays red until the deferral mechanism is extended to reach it,
   which is its own change.
2. **Commission a different implementation.** The review's judgement — which I
   share after reproducing it — is that substring-plus-window is the wrong
   instrument for negation scope, and that each patch invites the next bypass.
   A real fix reads structure, not characters, and would want an author other
   than the one who wrote the specimens.
3. **Leave it.** q03 fails intermittently, visibly, on a gate that stops
   milestone close. Nothing is silently wrong.

I recommend **(1) or (2), not a fifth patch from me.** I have now been wrong
about this rule's safety twice — first that the §3 collision did not occur, then
that a tightening could not create a false pass — and both times the error ran
in the direction of believing my own instrument.

---

## 11. Decision, 2026-08-20: option 3, leave it

The seat asked for **(1) defer q03** if it was the recommended approach. On
investigation it is not, and the reason is dispositive rather than a matter of
taste:

- **There is no deferral mechanism to follow.** q12 and q15 carry no marker of
  any kind — not in `golden_questions.json`, not in `run_evals.py`, not in
  `replay_history.py`. They are "deferred" purely as a standing seat decision
  that 18/20 is the bar.
- **That kind of deferral cannot clear this gate.** q12 and q15 never trip
  FRAGILE because they fail *consistently*. q03 trips it because it is
  *inconsistent*. FRAGILE detects non-determinism, not failure. Deferring q03
  the way they are deferred leaves CI red and changes nothing.
- **Making it clear the gate means building an admit path into FRAGILE**, which
  `replay_history` was deliberately built without: "FRAGILE and REGRESSED are
  defects a change either introduces or does not, so they fail the run." That
  mechanism would then be permanently available to silence real
  non-determinism, and the first thing it would silence is the detector that
  just caught a real defect.

**So: option 3.** q03 keeps failing, visibly and intermittently, on a gate that
stops milestone close. Nothing is silently wrong, and the cost is one honest
red check rather than a weakened instrument. `evals/golden_questions.json`
remains unedited.

### Where the real fix goes

Not into this milestone, and not into a SPEC without the PM seat. Recorded as
an M05 open thread, with the shape it should take:

**Score the structure, not the characters.** The 2026-08-12 ruling already
states the true invariant — the defect is *a TTB proposition carrying a Red
No. 3 citation*, not the appearance of a phrase. The failing answer had
`answer_rows[1].citations: []`, so the invariant is checkable structurally, and
no paraphrase can bypass a check that never looks at wording. That needs a new
check kind in `run_evals.check()`, an SME ruling on the semantics, a PM ruling
to home it in a SPEC, and — per the review that killed the last attempt —
specimens written by someone other than whoever writes the rule.

Any attempt must clear `milestones/M05/negation_scope_false_passes.py`, which
reports 0 false passes against today's scorer.
