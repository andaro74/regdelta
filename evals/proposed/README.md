# Proposed: the golden set at twenty questions

**Status: MERGED 2026-08-15. This directory is now a RECORD, not a proposal.**
All ten questions were accepted by the SME seat, none withdrawn and none amended
at merge, and they live in `evals/golden_questions.json` — which is the only
place to edit them now. `golden_questions_q11_q20.json` is deleted; keeping a
second copy of ground truth is how two copies disagree.

Kept because it is the case that was made and the reasoning that was ruled on:
the coverage argument below is why the set is twenty rather than ten, and the
scoring ruling is the record of ten questions that all looked fine and all could
be gamed. The per-question evidence travelled with the questions, in their
`note` fields, per the q03 ruling — a ruling recorded somewhere else is a ruling
the next reader will not find.

Drafted 2026-08-12, on `m03-agent-graph`, against the corpus as it stands at
`m01c` (985 chunks, four FR documents, three CFR sections).

> ⚠️ **Authored against 4 FR documents; re-checked against 49.** Later the same
> day, building the M03 agent graph surfaced that the poller had grown the
> corpus unattended. Every owed check has since been discharged against the live
> index and **no question is withdrawn**: q14's crossref is citable (16 chunks
> for 21 CFR 101.13, and 2024-29957#0384 carries the (h) carve-out verbatim);
> q16 still measures what it says (the phrase "front-of-package" now appears in
> exactly one chunk, as preamble discussion establishing no requirement and no
> date, and 90 FR 5426 is still absent); and the twelvefold rise in distractor
> pressure did not break retrieval — M02's probe set re-runs at 9/9, recall@8 =
> 1.0. `$10 million` and `annual food sales` remain at zero hits, so the q07
> ruling holds. Details in `corpus_premise_rechecked` in the JSON.
>
> **Both rulings are in.** Scoring was ruled on and all ten repaired (below);
> the questions themselves were then put to the SME seat one at a time and all
> ten accepted, with q15's and q19's declared blind spots approved explicitly
> rather than merged quietly.

## Why twenty

At ten questions each one is worth 10 points, so SPEC/03's `≥80%` bar reads
"miss no more than two" and a single flaky question is the difference between
shipping and not. Coverage is also lopsided against the product's own thesis:

| tag | q01–q10 | + q11–q20 |
|---|---|---|
| timeline | **1** (q08) | **7** (q08, q11, q12, q13, q17, q19, q20) |
| trap | 5 | 8 (+q11, q19, q20) |
| retrieval | 3 | 5 (+q13, q14) |
| honesty | **2** | **3** (+q16) |
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
| q14 | crossref, retrieval | Failing to resolve a cross-reference that **is** in the corpus, or missing its carve-out. | 21 CFR 101.65(a)(2): general requirements of §101.13 apply "with the exception of §101.13(h)" for paragraph (d) claims. **Live-verified 2026-08-15** — chunk `2024-29957#0384` carries the regtext verbatim, and the index holds 16 `21 CFR 101.13` chunks including a dedicated `101.13(h)`. |
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
invisible to inspection, so it was checked mechanically instead — and the check,
as originally run, was worthless. See below.

## Scoring ruling — 2026-08-15

Routed through `sme-eval-triage`, then **every finding replayed through
`run_evals.check()`** rather than accepted on the subagent's reading. 13 of 14
specimens broke as predicted. **All ten questions needed token edits. None was
withdrawn**, and no question's subject, required dates or expected answer
changed.

Two failure shapes, one root cause — a substring scorer being asked to express
something substrings cannot say:

**A. Bans that a correct refutation reproduces** → false **fails** (q11, q12,
q13, q19, q20). These questions hand the model a false premise to rebut, and
rebutting it means restating it. q20 banned `"published on January 15, 2025"`,
so the single most likely correct answer — *"it was **not** published on January
15, 2025"* — scored FAIL. q19 was worse: it banned `"no hard deadline"`, which
is the phrase in *its own note's* model answer. Fixed by direction-binding each
ban (`extended the deadline **to**`, `**so** there is no deadline`, `**was**
published on`), or deleting bans a positive requirement already made redundant.

**B. Accept tokens that match their own negation, or echo the stem** → false
**passes** (q12, q14, q15, q16, q17, q18):

- **q18** — `"affected"` is a substring of `"not affected"`. *"You are not
  affected"* scored PASS. This is the q02 defect verbatim, reintroduced three
  days after that ruling.
- **q14** — the exact negation of the correct answer passed: *"…including
  101.13(h); nothing is **carved** out"* satisfied the carve-out group via the
  word "carved", and the stem echo `"healthy"` satisfied the other.
- **q16** — broken in both directions at once, in the question written to guard
  against exactly that. `"do not have"` admitted the fabrication *"you do not
  have to"*, while the best grounded answer — *"discussed only in passing,
  establishes no requirement"* — matched none of the eight accept tokens.
- **q15** — the two deadlines **swapped between the two rules** scored PASS.
- **q17** — *"the compliance date **delayed to** February 25, 2028"*, the
  ADR-0006 conflation stated outright, evaded all four bans because each
  required "was", "moved" or "is".
- **q12** — asks two things and scored one; *"that was **never** a fair
  reading"* passed.

**Two triage recommendations were not adopted**, both because they traded a
false pass for a false fail: narrowing q14's second group to `["101.65"]` (a
correct answer need never name 101.65) and q15's groups to
`[["74.303"],["101.65"]]` (a correct answer may name the rules without their
section numbers). Reasons are recorded in those questions' notes.

**Why the original discrimination check missed all of it** — this matters more
than the defects. The same seat wrote the questions *and* the wrong-answer
specimens, and phrased the wrong answers the way its own bans anticipated. **A
discrimination test authored by whoever wrote the bans tests the bans against
themselves and always passes.** The harness was sound; the specimens were not
adversarial. It is now landed as `evals/check_discrimination.py` (`make
discrimination`) with the specimens as data and that lesson written into its
module docstring, because the harness is worse than useless if the next person
writes specimens the same way.

Fifty specimens now run: `make discrimination ARGS="--file
evals/proposed/golden_questions_q11_q20.json"`. Forty-eight must score
right-way-round; two are **declared limitations** that assert today's *wrong*
behaviour and fail the run if it ever changes — q15's swap phrased without the
banned adjacency (still passes), and q19's answer that quotes the supplier's
full inference in order to reject it (still fails). A limitation that quietly
heals leaves a note behind that overstates the defect, which is its own kind of
lie.

**`q01`–`q10` have no specimens and have never been checked this way.** The
harness exits non-zero on the live set for that reason rather than reporting a
green on zero coverage. q02 and q08 were both this defect class, each found by
one expensive failure at the keyboard.

## Verification — discharged 2026-08-15

Every check this draft owed has been run against the live index. **No question
is withdrawn.** What remains is a ruling, which is a human decision, not a
verification.

**q14 was the one question grounded only in a repo fixture**
(`tests/fixtures/ecfr_21_101.65.xml`), and its own note said to withdraw rather
than adjust it if the live index disagreed. It agrees, on better evidence than
the fixture gave:

- the index holds **16 chunks** for `21 CFR 101.13`, including a dedicated
  `cfr-21-101.13@2025-04-28#0004` whose `citation_path` is `21 CFR 101.13(h)`;
- chunk `2024-29957#0384` carries the regtext verbatim — *"The claim is made in
  accordance with the general requirements for nutrient content claims in
  § 101.13, with the exception of § 101.13(h) when the nutrient content claim is
  made in accordance with paragraph (d) of this section."*

**q16's premise survived a scare and is worth recording so the next reader does
not repeat it.** "front-of-package" now *does* appear in the corpus — in exactly
one chunk, `2024-29957#0367`, as comment-and-response discussion inside the
healthy rule about how the healthy symbol relates to FOP development. It
establishes no requirement and no date, and the FOP proposed rule itself
(90 FR 5426) returns **zero** chunks. "I cannot confirm that from my sources"
is still the correct answer.

**The corpus growth did not break retrieval.** M02's probe set was re-run at 49
documents and still scores 9/9, recall@8 = 1.0
(`evals/history/0e69ef1-retrieval-s3vectors.json`). A failure of any question
below can therefore no longer be blamed on distractor pressure without evidence.

**Unchanged:** `$10 million` and `annual food sales` remain at zero hits, so the
q07 ruling holds at the current corpus. Nothing here was verified by asking a
model.

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

Then move the ten `SPECIMENS` entries in `evals/check_discrimination.py` across
with them — nothing carries them automatically — and re-run `make
discrimination` against the merged file, which must go green on twenty
questions rather than ten. If a question is amended or withdrawn during the
ruling, **its specimens change with it**: a specimen set that no longer matches
its question is the false assurance this whole ruling was about.
