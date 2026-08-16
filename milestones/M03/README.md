# M03 — Agent graph + HITL

- Git tag: `m03` → `ff5fff6`   Branch: `m03-agent-graph`
- Spec: SPEC/03-agents.md      ADRs: **ADR-0010** (checkpointer), **ADR-0011**
  (poller scope) added here; ADR-0006 and ADR-0007 are consumed by the timeline
  agent for the first time
- Sessions: 1 Claude Code session, 2026-08-15. Milestone work ~3.5 hrs
  (`6aec3cc` 05:36 → `ac839ca` 09:05), tagged `ff5fff6` 09:14. **Work continued
  for ~10 hrs after the tag** and the branch is now well ahead of it — see
  "After the tag" below. Everything in this pack up to that section describes
  the milestone as closed; everything after it is amendment.

## Scorecard
| run | tier | mode | pass | total | wall_s | corpus docs |
|-----|------|------|------|-------|--------|-------------|
| `ac839ca` | s3vectors | **agent** | **10** | 10 | 123.3 | 49 |
| `ac839ca` | s3vectors | naive (control) | 4 | 10 | 71.5 | 49 |
| `f95e716` | s3vectors | agent | 10 | 10 | 121.9 | 49 |
| `42e9010` | s3vectors | agent | 10 | 10 | 123.0 | 49 |
| `f3f00d6` | s3vectors | agent | 10 | 10 | 123.1 | 49 |
| `585a95f` | s3vectors | agent | 10 | 10 | 129.8 | 49 |
| `7f012b8` | — | naive (frozen M00b) | 3 | 10 | 81.0 | *not recorded* |
| `74822d4` | s3vectors | **agent, tightened set** | **10** | 10 | 129.2 | 49 |
| `74822d4` | s3vectors | naive (control, tightened set) | 3 | 10 | 70.4 | 49 |
| `2cea737` | s3vectors | **agent, TWENTY questions** | **16** | 20 | 257.8 | 49 |
| `2cea737` | s3vectors | naive (control, twenty) | 5 | 20 | 165.6 | 49 |

Seven agent runs are listed and an eighth happened: a 9/10 at `fd98d64`, which
scored q02 as the single failure. Its card is **not in `history/`** — it was
withdrawn at `585a95f` because a stale loopback shim had answered that run, so
the card described code its own sha did not contain. The commit message at
`c68b4a3` remains the record that the run happened.

**Delta vs baseline — three rulers, three numbers:**

| measured | instrument | overall | traps |
|---|---|---|---|
| at close, `ac839ca` | golden set as it stood then | 40% → 100% | 2/5 → 5/5 |
| re-measured, `74822d4` | tightened set, ten questions | 30% → 100% | 1/5 → 5/5 |
| **current, `2cea737`** | **twenty questions, 102 specimens green** | **25% → 80%** | **1/8 → 8/8** |

**Quote the last row.** Each is a different ruler, and the later ones are
longer: `74822d4` tightened the ten questions after finding they could be gamed,
`2cea737` added ten more. The agent's absolute score falls (100% → 80%) while
the delta over the control holds and the trap count triples — which is what a
harder instrument is supposed to do to an honest system. The earlier rows are
kept because deleting a superseded measurement is how a record becomes a story.

The three failures behind 16/20 are system defects, not question defects: they
are listed under "After the tag" and deferred to M04 with evidence.

<sup>Trap counts amended 2026-08-15 from `2/4 → 4/4`. Not a re-run — a re-read
of the cards already on file. The gate is selected by TAG, and the `trap` tag
covers five questions (q01–q04 **and q07**), not the four the criterion named
by ID. `ac839ca-naive-full.json` shows the control failing q01, q03 and q07;
`ac839ca-s3vectors-full.json` shows the agent passing all five. The delta is
wider than it was written, not narrower.</sup>

> ⚠️ **Read this before citing the trap numbers.** Later on 2026-08-15, after
> this milestone closed, the golden questions were checked for the first time
> against the thing a scorecard implicitly assumes: that a question can tell a
> right answer from a wrong one. **They could not.** 18 of 48 hand-written
> answers scored the wrong way, and **all five trap-tagged questions** (`q01`–
> `q04` *plus* `q07`, which is what `--subset trap` actually selects) passed at
> least one wrong answer — including, in each case, the exact wrong answer that
> trap was built to catch. The questions were tightened under the scoring ruling
> recorded in `_scoring_ruling` in `evals/golden_questions.json`.
>
> What that does and does not do to the numbers above. It does **not** show the
> system answered anything wrongly — a question that *can* pass a wrong answer
> did not necessarily do so. But it could not be checked either way from the
> cards of this vintage: they record `{id, pass, fails}` and no answer text, so
> their passes are unauditable and not backfillable (fixed at `aa79ec5`, going
> forward only).
>
> **RESOLVED THE SAME DAY, by re-running rather than by argument.** At `74822d4`
> the full set was re-run against the tightened questions, and per ADR-0002 the
> naive control was re-run at the same commit on the same instrument:
>
> - **agent 10/10, traps 5/5** — the claim survives the tightening intact;
> - **control 3/10, traps 1/5** — down from 4/10, so the tightening did cost the
>   control a question, exactly as predicted, and the delta **widened** to
>   **30% → 100% overall, traps 1/5 → 5/5**;
> - both cards carry answer text, so the passes are auditable. Spot-checked: q01
>   quotes *"the compliance date remains unchanged at this time"* from
>   2025-03118; q07 names Response 135 and FDA's rejection of the small-business
>   extension; q04 distinguishes the HHS request from the binding order and gets
>   the stay right unprompted. **Earned, not token-matched.**
>
> So the caveat on the runs above stands for those runs — cite `ac839ca` as
> "10/10 against the golden set as it stood then", nothing stronger. The claim
> that **this system answers the trap questions correctly** now rests on
> `74822d4`, where the instrument has been shown to discriminate (48 specimens,
> none scoring the wrong way, 7 declared limitations) and the answers are on
> file to read.

Measured the honest way: the control was **re-run at this same commit, against
these same questions, over this same 49-document corpus** (`ac839ca-naive-full.json`).
ADR-0002 freezes `src/baseline/naive.py`, and re-running it is not improving it.

The frozen M00b card says 3/10, and that number **must not** be used for this
delta. Four of the ten questions have been rewritten since it was recorded
(q03 and q07 on 2026-08-12, q02 and q08 on 2026-08-15) and the corpus has gone
from 4 documents to 49. It is a different instrument on different data; the
30% → 100% arithmetic would be a claim about two things that were never
compared.

Every card carries `corpus.documents_sha`, added this milestone, because the
poller changed the corpus **during the session** — 34 documents at 05:36, 49 by
09:05. Two runs an hour apart were otherwise indistinguishable in `history/`.

## Done-when
SPEC/03: `make evals` ≥ 80% overall AND 100% on q01–q04, on the S3 Vectors
tier; HITL demonstrated — one golden question with an underspecified company
profile ends pending_review, then resumes correctly.

- ≥ 80% overall — **10/10**, seven full runs, the last of them (`74822d4`) on the tightened set.
- 100% on q01–q04 — **4/4**, every run since `a082219`.
- HITL demonstrated — **both halves**, live, on q10 (see the demo below).

**Criterion amended after close, 2026-08-15 — no re-measurement.** The quote
above is left exactly as it read at close, because an evidence pack records
what was true then and rewriting it would make the pack agree with a spec it
was never measured against. SPEC/03's Done-when has since been reworded
(pm-spec-reviewer) to name the **trap tag** rather than the IDs `q01–q04`,
because `run_evals.py` selects subsets by tag and the tag reaches q07 — so the
two readings were materially different gates. Nothing was re-run and nothing
needed to be: the recorded evidence is 10/10, which entails 100% on every
subset, so the reworded and stricter criterion is already satisfied by cards on
file. The trap line in the scorecard summary above is restated as 5/5 for the
same reason. The false-pass caveat below the scorecard **stands unchanged** —
5/5 is a wider count on the same weak instrument, and the count moving does not
move the evidentiary point.

One wording divergence, flagged not smoothed: SPEC says the underspecified
question "ends pending_review"; the implementation reports `needs_input` and
reserves `pending_review` for the confidence trigger, because they are
different situations for whoever picks up the review — one needs an *input*,
the other a *judgement*. q10 accepts either. That is a PM-seat wording call.

## What you can demo right now (3 min)

**1. The graph answers with citations, and gets the trap right.**
```
make agent-evals          # 10/10, ~2 min
```

**2. Timeline answers come from the amendment graph, not from prose.**
```python
from graph import amendment_graph as ag
t = ag.load("2025-00830")
ag.operative_deadline(t)   # 2027-01-15, kind="derived-from-effective"
ag.resolve(t, "compliance")# ()  — the order sets none (ADR-0006)
t.stays                    # 2025-02-18 → 2026-08-05, 21 U.S.C. 371(e)(2)
ag.as_of(t, "2025-06-01")  # the stay was not knowable then
```

**3. HITL, end to end.**
```
POST /query   "Are we affected by the healthy-claim changes?"
  → needs_input, paused, needs company_profile, resume_with POST /resume/<id>
POST /resume/<id>  {"company_profile": {"claims": ["healthy"], ...}}
  → ok, confidence 0.95, cites 89 FR 106064 / 2024-29957 / 2025-03118
```

## Evidence artifacts
- `evals/history/ac839ca-s3vectors-full.json` — the close scorecard
- `evals/history/ac839ca-naive-full.json` — the control, same commit/questions/corpus
- `milestones/M03/q02-flap.md` — the q02 episode, including a wrong finding of
  mine and its correction
- `docs/adr/0010-hand-written-checkpointer.md`, `docs/adr/0011-poller-subject-scope.md`
- 504 unit tests, `ruff` clean

## What broke / what I'd redo

**The answer layer truncated the answer off the end of its own source.** The
verdict node fenced retrieved passages at 1200 characters — a constant copied
from the reranker, where it is right because ranking only needs the gist.
Chunk `2025-00830#0021` is 1891 characters and its decisive sentence starts at
1811. Retrieval ranked that chunk *second*; the answer layer then cut the last
700 characters and reported that its sources did not address the question.
Every chunk over 1200 characters was losing its tail on every question. Cost:
the whole q02 investigation below. Redo: bound passages by the ingest cap that
already exists, and never re-use a constant across a change of purpose without
asking what it was chosen for.

**I searched the corpus for the wrong words and reported a wrong finding.**
q02 was reported as requiring an answer the corpus cannot support, on a scan
showing zero hits for `not adulterated`, `may remain`, `manufactured before`.
The corpus says "will **not be regarded as** adulterated" — same meaning, no
substring match. The scan searched for the *question's* phrasing rather than
the *source's*. That finding was acted on in conversation before it was
corrected. Redo: when a corpus scan comes back empty, read the document before
concluding anything.

**Two golden questions were scoring phrasing, not substance.** q02's accept
token `manufactured before` matched the *negation* of its own ground truth
(measured: passed ~1 run in 4, and every passing run matched inside "no
transition period for products manufactured before the effective date").
q08 required one of four exact phrasings of "no compliance date" and failed a
correct answer that wrote "Compliance date: None stated." Both are now ruled on
with sources. The q07 ruling had already named this defect class on 2026-08-12
and it was still present in two more questions.

**The measuring tools were broken in three ways, all of which would have
produced false confidence.** `run_evals.py` crashed on a cp1252 console before
question one; it had no dirty-tree guard while its sibling harness did, and a
90% run came within one flag of being filed under a commit containing none of
the code; and no scorecard recorded which corpus answered it. Redo: when two
harnesses do the same job, diff them — `run_retrieval.py` already had two of
these three right.

**The local shim let two copies serve the same port.** `http.server` sets
`allow_reuse_address`, which on Windows permits a second process to bind a port
another is actively LISTENING on, and the banner printed *before* the bind. A
stale shim survived its `kill`, the replacement announced success, and the
golden run was answered by the old code — so a recorded card carried the
previous commit's provenance under the new commit's sha. Caught only because a
field was expected to be absent and was not.

**I overstated a defect to the user.** q08 was reported as "flapping the same
way q02 did" on the strength of one observed failure; probed directly it passed
8/8, and the real rate is about 1 in 12. The fix was still right; the
characterisation was not.

**A parameter name cost an hour.** LangGraph injects run-time configuration by
parameter *name*. `hitl_gate` took `config_` — renamed to avoid shadowing the
`shared.config` module — and was silently passed nothing: the gate never saw
`resumable`, never paused, and seven resume tests failed with no error to read.

**The dirty-tree guard I added broke `make baseline`.** Both shim targets write
a `.pid` file into the repo root and `.gitignore` did not cover it, so the
harness refused to record because of a file the harness had just created. It
would have failed the M00b control's reproduction command, not this milestone's.

**What I would redo about the milestone itself:** the golden set was expanded
to twenty questions in a draft (`evals/proposed/`) whose four-document corpus
premise was false within hours of being written. Drafting ground truth against
a corpus that changes daily needs the corpus pinned first — which is now
possible, because the cards carry a fingerprint.

---

## After the tag — 2026-08-15, ~10 hrs (`ff5fff6` → `09e0014`)

The milestone closed at 10/10 and then the instrument that produced that number
was checked, for the first time, against the thing a scorecard implicitly
assumes: **that a question can tell a right answer from a wrong one.** It could
not. What follows happened after the tag, on the same branch, and is amendment
rather than milestone evidence.

**The golden questions could be gamed, all of them.** 21 of 48 hand-written
answers scored the wrong way — 18 false passes, 3 false fails — and **every one
of the five trap-tagged questions passed the exact wrong answer it was built to
catch.** q18's accept token `affected` is a substring of `not affected`; q14
passed the precise negation of its own correct answer; q05 could not tell the
'healthy' criteria from their inverse. Ruled on and closed
(`_scoring_ruling` in `evals/golden_questions.json`); `evals/check_discrimination.py`
now replays the real scorer against 102 right-and-wrong specimens and is the
reason any of this is checkable.

**Why it was invisible:** the same seat wrote the questions and the wrong-answer
specimens, and phrased the wrong answers the way its own bans anticipated. A
discrimination test authored by whoever wrote the bans tests the bans against
themselves and always passes. That is the single most transferable thing this
session produced, and it is in the harness's module docstring rather than only
here.

**Scorecards now record the answer, not just the verdict.** They carried
`{id, pass, fails}`, so a FAILURE was legible and a PASS was dark — the wrong
way round. When the false passes were found there was no way to ask whether any
recorded pass had been earned. Re-running settled it (see the scorecard table),
but only for runs from `aa79ec5` onward; earlier cards are not backfillable.

**A shim that never started recorded a 0/10 scorecard, twice.** Both eval
targets backgrounded the loopback shim and slept a fixed 2–3 s, which cannot
distinguish "still starting" from "never started". Fixed at three layers: the
runner refuses to record a run where nothing reached the API, `wait_ready.py`
fails before the Bedrock spend, and the Makefile resolves configuration from the
deployed Lambda instead of the operator's shell.

**The golden set is now twenty questions**, ruled on one at a time. Coverage was
the reason: one timeline question, for a product whose thesis is timelines, and
zero touching the administrative stay that ADR-0007 exists for. On its **first
live run** the new questions found three real system defects — a `crossref_agent`
whose output no node reads, retrieval crowding that hides a chunk which
demonstrably exists, and a single unfiltered query that answers a two-trigger
question with one trigger. All three are deferred to M04 with evidence, not
fixed at the end of a long session.

**Current: 16/20 (80%), traps 8/8; control 5/20.** That is the honest number on
the longer ruler, and it sits exactly on the ≥80% bar with no margin — which is
why `≥ 80%` as a *form* of bar is now an open PM item in SPEC/03.

**Reviews:** `security-reviewer` found the CI eval gate could not fail (two
independent fail-open paths, both fixed at `b6b7779`) and three unpaginated
DynamoDB reads in the checkpointer, one of which meant `delete_thread` never
deleted the review item it exists to delete (`09e0014`). `pm-spec-reviewer`
found SPEC/03's exit criterion named four questions by ID while the gate selects
five by tag, plus three further defects in the same sentence.
