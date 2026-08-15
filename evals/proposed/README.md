# Proposed: the golden set at twenty questions

**Status: DRAFT. Not ground truth.** Ten new questions (`q11`–`q20`) in
`golden_questions_q11_q20.json`, to be merged alongside the existing `q01`–`q10`,
which this proposal does **not** modify. Requires an SME-seat ruling before merge
(CLAUDE.md role gates; ADR-0005 — a ruling is sound because of its sources, not a
signature).

Drafted 2026-08-12, on `m03-agent-graph`, against the corpus as it stands at
`m01c` (985 chunks, four FR documents, three CFR sections).

> ⚠️ **The four-document premise is already false, and this draft has not been
> re-verified against what replaced it.** Later the same day, building the M03
> agent graph surfaced that the live corpus holds **thirty-four** FR documents:
> the daily poller ingested 30 more between 2026-07-30 and 2026-08-12,
> unattended. Nothing below is withdrawn — but nothing below should be ruled on
> until it has been re-read against 34 documents rather than 4. The specific
> re-checks owed are listed in `corpus_premise_invalidated` in the JSON, and the
> headline ones are that q16's "front-of-package is not in this corpus" premise
> is now shaky (the phrase appears in the healthy rule's own preamble) and that
> every question now faces roughly eight times the distractor pressure it was
> written for. One thing was re-verified and holds: `$10 million` and `annual
> food sales` are still at zero hits across all 990 chunks, so the q07 ruling
> stands at the current corpus.

## Why twenty

At ten questions each one is worth 10 points, so SPEC/03's `≥80%` bar reads
"miss no more than two" and a single flaky question is the difference between
shipping and not. Coverage is also lopsided against the product's own thesis:

| tag | q01–q10 | + q11–q20 |
|---|---|---|
| timeline | **1** (q08) | **7** (q08, q11, q12, q13, q17, q19, q20) |
| trap | 5 | 8 (+q11, q19, q20) |
| retrieval | 3 | 5 (+q13, q14) |
| honesty | 3 | 4 (+q16) |
| applicability | 1 | 3 (+q15, q18) |
| crossref | 1 | 2 (+q14) |
| hitl | 1 | 2 (+q18) |
| smoke | 5 | 5 — unchanged |

One timeline question, for a system whose CLAUDE.md rule is that timeline
questions are answered from the amendment graph rather than similarity. And
**zero** questions touch the administrative stay, which is the subject of an
entire ADR (0007), a first-class DynamoDB interval, and a document the poller
ingested unattended. `make smoke` stays at five questions, so the fast loop does
not get slower.

## What each new question buys

| id | tags | the failure mode it catches | source, and how to falsify it |
|---|---|---|---|
| q11 | timeline, trap | Treating a stay as tolling — "suspended 18 months, so the deadline moved 18 months". | 21 U.S.C. 371(e)(2) has no day-for-day extension; 2026-15920 / 91 FR 50475 lifts and **confirms** both dates (scope `dates_confirmed`, predicate CONFIRMS, never SUPERSEDES). ADR-0007; regulatory-domain skill. |
| q12 | timeline | Answering "now" when asked "then" — no point-in-time reasoning over `STAY_PERIOD`. | `retrieval_truth.json` r05 explicitly defers this: "the point-in-time reasoning … is M03's, from the STAY_PERIOD interval, and is explicitly not asserted by this probe." This is that question. |
| q13 | timeline, retrieval | Applying the ingested-drug date to food, or collapsing two amendatory instructions into one. | Chunk `2025-00830#0002`, quoted in r09: "Remove 74.303" and "Effective January 18, 2028 remove 74.1303". |
| q14 | crossref, retrieval | Failing to resolve a cross-reference that **is** in the corpus, or missing its carve-out. | 21 CFR 101.65(a)(2): general requirements of §101.13 apply "with the exception of §101.13(h)" for paragraph (d) claims. **Fixture-verified only — see Verification owed.** |
| q15 | applicability, verdict | Collapsing two rules with two different deadlines into one row. | Both dates already established by q02/q07; adds no new ground truth, only the requirement that both survive one answer. |
| q16 | honesty | Answering from model priors about a real FDA initiative that is not in this corpus (front-of-package, 90 FR 5426). | Named in the q07 ruling as one of the rules the $10M tier really belongs to — real, and absent here. |
| q17 | timeline | Attributing the delay to the wrong date — the ADR-0006 conflation, asked directly rather than as q01's yes/no. | 2024-29957#0000, 2025-03118#0000 and #0003, all quoted in r01/r06. |
| q18 | hitl, applicability | A HITL gate that pauses on *everything* — which passes q10 perfectly and is useless. | Applicability turns on conduct, not size: 2024-29957#0303 Response 135, per the q07 ruling. |
| q19 | timeline, trap | "No compliance date" ⇒ "no deadline". The premise is true; only the conclusion is wrong. | ADR-0006 and the regulatory-domain skill: a repeal states only an effective date, `compliance_date` stays null, and the real deadline is *derived*. Probe r02 depends on the same fact. |
| q20 | timeline, trap | Accepting a wrong date the **user** asserts. Anchoring, not retrieval. | 90 FR 4628 published 2025-01-16; "January 15, 2025" is the announcement date and appears nowhere in the document. Falsify by full-text search. |

## How this draft tried not to repeat the q07 and q03 defects

The 2026-08-12 SME ruling found three defect classes. Each is guarded here:

1. **Requiring an answer the corpus cannot support** (q07's fabricated
   small-business tier). Every assertion above is traced to a document, chunk,
   ADR or skill file already in this repo, listed in the table and repeated in
   each question's `note`. The single exception is called out below rather than
   buried.
2. **The answer token sitting in the question stem** (q03's false pass). No new
   question contains its own answer. Where a question carries bait — q11, q19,
   q20 — the bait is a *true premise* with a wrong inference, so passing
   requires contradicting the stem, which is the corrected q07's construction.
3. **`must_not_contain` punishing vocabulary rather than error.** Every
   `must_not_contain` string here is assertion-shaped. The clearest case is
   q19, where **`"they are right"` is deliberately not forbidden** — the best
   answer opens by conceding the true half ("they are right that the order sets
   no compliance date, but…") and banning that phrase would punish exactly the
   answer the question exists to reward. Same reasoning keeps `"tolled"` legal
   in q11 and `"90 FR 5426"` legal in q16.

The ruling also found a fourth defect that neither the author nor the first
review caught: q07 **could not distinguish a true answer from a false one in
either direction**, and scored a stable 0/3 while measuring nothing. That is
invisible to inspection, so it was checked mechanically instead. A harness
replays the real scorer (`run_evals.py check()`) against a hand-written correct
answer and a hand-written plausible-wrong answer for each question, and requires
correct→PASS and wrong→FAIL. All ten pass; it is worth landing as
`evals/check_discrimination.py` and extending over `q01`–`q10`, which have never
been checked this way.

It has already earned itself once: q11's first draft rejected a correct answer
that cited only the lift notice. That turned out to be the question behaving
correctly — the deadline is set by 90 FR 4628, not by the notice confirming it —
but the requirement was unstated, so the note now says so explicitly.

## Verification owed before merge

**q14 is the one question not confirmed against the live corpus.** Its quoted
text was read from `tests/fixtures/ecfr_21_101.65.xml`, a repo fixture. Two
things must be confirmed against the live index first:

1. a `21 CFR 101.13` chunk actually exists (the section is tracked in
   `config.TRACKED_CFR_SECTIONS`, which is not the same as ingested), and
2. current `101.65(a)(2)` still carries the `(h)` carve-out.

If either fails, **withdraw the question rather than adjust it** — a crossref
question whose target is not in the corpus is the q03 false pass rebuilt.

Everything else is sourced to material already in the repo. Nothing here was
verified by asking a model.

## Open items this draft creates or sharpens

**1. SPEC/03's exit criterion is now unambiguously wrong, and it is a PM-seat
call.** Done-when reads "100% on q01–q04 (trap questions)". `run_evals.py`
selects by **tag** (`--subset`), and the trap tag already covered five questions
after the q07 ruling — which that ruling flagged as an open item. This draft
takes it to eight. `--subset trap` and "q01–q04" are now materially different
gates. The wording must change to name the trap subset, or exclude specific IDs;
engineering must not pick one silently, because the tag reading is stricter and
quietly tightening a milestone's exit criterion is not engineering's call. Route
through `pm-spec-reviewer`.

**2. `≥80%` of twenty is sixteen.** Worth confirming the bar is still the right
one against a set that is deliberately harder, rather than inheriting a number
chosen when the set was ten and lighter on timeline reasoning.

**3. HITL resume cannot be expressed as a golden question today.** SPEC/03's
Done-when requires a run that ends `pending_review` and "then resumes
correctly". `run_evals.py` only ever POSTs `/query` (lines 57–66); there is no
way to POST `/resume/{id}`. q18 covers the other half — the gate must *not* fire
when the profile is sufficient — but resume needs a runner change or a separate
harness, and that is a SPEC/04 API-surface decision. Recorded here rather than
faked with a question that would appear to cover it.

**4. The eval gate cannot currently fail.** `.github/workflows/evals.yml:73-76`
runs `python evals/run_evals.py | tee scorecard.txt` and then reads `$?`. In a
pipeline `$?` is the exit status of the **last** command — `tee` — and the job
sets no `pipefail` (the workflow specifies no `shell:`, so GitHub's default is
`bash -e {0}`, which does not include it). So `Enforce` runs `exit 0` no matter
how many questions failed, and the file's own header — "a PR that regresses
ground-truth answers physically cannot merge" — does not hold. It is latent
rather than live, because the job is gated on `EVAL_GATE_ENABLED`, set back to
`false` on 2026-08-08. It becomes real at exactly the moment this set starts
being scored in CI, post-M04. The fix is one line (`set -o pipefail`, or drop
the pipe and `tee` afterwards), but `.github/**` is Security-owned under
CODEOWNERS, so it wants `security-reviewer` and its own commit — not this one.

**5. A domain-skill line contradicts the q03 ruling.**
`.claude/skills/regulatory-domain/SKILL.md` still lists under "Known demo facts"
that "TTB formula re-approval required if an approved alcohol formula changes".
That is true as domain knowledge and **not citable from this corpus** — the q03
ruling verified that no TTB source exists anywhere in it. A node that reads this
skill and asserts the obligation would fail the corrected q03 while following
its own instructions. The line wants a "not in this corpus" marker. Lead-seat
call, and out of scope for the SME ruling on these questions.

## Merging

The questions are drop-in shaped: append the ten objects in
`golden_questions_q11_q20.json` to the `questions` array of
`evals/golden_questions.json` and delete the `_proposal` key. **Carry the `note`
fields across unchanged** — they are the record, and per the q03 ruling a ruling
recorded somewhere else is a ruling the next reader will not find. Whatever the
SME seat decides, that decision belongs in the `note` beside the assertion it
governs, including a decision to withdraw q14.
