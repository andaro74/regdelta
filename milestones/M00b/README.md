# M00b — Naive-RAG baseline (the control)

- Git tag: `m00b-baseline`      Commit: `7f012b8` (run) → tagged at close
- Spec: SPEC/00b-baseline-naive-rag.md   ADRs touched: ADR-0002, ADR-0004 (new)
- Sessions: 1 Claude Code session (shared with M01 close)

## Scorecard
| run | tier | subset | pass | total | wall s |
|-----|------|--------|------|-------|--------|
| `7f012b8-naive-full` | naive | full | 3 | 10 | 81.0 |

Provenance (recorded in the scorecard JSON): model
`us.anthropic.claude-opus-4-6-v1`, `NAIVE_TOP_K=8`, temperature 0.

**This is the baseline. Delta vs M00b is 0 by definition — every later
milestone is measured from here.**

### Per-question result, and how stable it is
Repeated the full set 3× to check the control is reproducible. 9 of 10
questions are stable; one flaps.

| id | subset | result | stability | note |
|----|--------|--------|-----------|------|
| q01 | trap | ❌ fail | 0/3 stable | missed the compliance date entirely; no citation |
| q02 | trap | ❌ fail | 0/3 stable | missed 2027-01-15 |
| q03 | trap | ✅ pass | 3/3 stable | **unearned — see finding 2** |
| q04 | trap | ❌ fail | 0/3 stable | missed 2027-01-15 |
| q05 | retrieval | ❌ fail | 0/3 stable | content correct, **cited nothing** |
| q06 | retrieval | ✅ pass | 3/3 stable | passes only after ADR-0004 |
| q07 | applicability | ❌ fail | 0/3 stable | no company-profile reasoning |
| q08 | timeline | ❌ fail | **1/3 FLAPPY** | see finding 3 |
| q09 | honesty | ✅ pass | 3/3 stable | weak accept list — see finding 4 |
| q10 | hitl | ❌ fail | 0/3 stable | no HITL path exists; correct failure |

Traps: **1/4 pass** (q03 only, and not on merit). Overall **30%**.

## What you can demo at this point (2-3 min)
1. `make baseline` — full golden set against the control. 3/10. Read q01's
   failure aloud: asked whether the delayed effective date moved the
   compliance deadline, naive RAG cannot answer, and cites nothing.
2. Show q05 next to q06: the baseline retrieves the right regulatory text
   and states the right criteria, then attributes them to "the Background
   passage." Correct content, unusable provenance. That is the gap the
   product exists to close.
3. `curl -X POST 'localhost:8000/query?mode=naive'` stays wired forever, so
   any future commit can be diffed against this run.

## Evidence artifacts
- `evals/history/7f012b8-naive-full.json` (recorded scorecard with provenance)
- Deployed corpus: 452 chunks / 452 vectors, us-west-2 (see milestones/M01)
- Reviews this milestone: sme-eval-triage (rulings below), eng-code-reviewer
  (13 findings), security-reviewer (11 findings). Fixes applied before record.

## What broke / what I'd redo

> ⚠️ Written from the engineering seat during the session. The human SME
> and PM still need to sign off on findings 2, 3 and 5.

**1. q06 failed for a typographic reason, not a regulatory one.** The
baseline answered "21 CFR § 101.65" — correct — and scored as uncited,
because the shared citation regex could not tolerate the section symbol.
Caught before the first `--record`, which was the only free moment to fix
it: recording first and fixing after would have moved the control under
every future delta. Ruled a system defect by sme-eval-triage; ground truth
untouched. See ADR-0004. **The ordering here is the lesson — fix the
instrument before you record, or never.**

**2. q03 passes but did not earn it (SME-blocked, not applied).** SPEC/00b
anticipated this: "If the traps PASS, the golden questions are too easy —
tighten them (that finding is itself evidence; record it)." Two leaks: the
token `"TTB"` appears in the question stem, so restating the premise
satisfies `must_contain_any`; and `naive.py` prefixes every passage with
`[citation]`, so `must_cite_any` is satisfied by echo. Decisive evidence
that the pass is not real: **there is no TTB source in the corpus at all** —
`BACKFILL_FR_DOCS` has three FDA documents and the eCFR targets are 21 CFR
101.65/101.13/74.303. The baseline cannot have retrieved the obligation it
appears to know. sme-eval-triage drafted a tightening; it is deliberately
NOT applied, because ground truth is SME-owned and because M00b must be
recorded as-run for this finding to be visible.

**3. q08 is the only flappy question — 1/3 — and it is also mis-specified.**
It asks for the *publication* date and accepts `January 15, 2025`, but FR
doc 2025-00830 (90 FR 4628) was published **2025-01-16**; `config.py`
already records that. So a correct answer fails and a wrong one passes.
Compounding it, effective and compliance coincide for food, so asking for
three distinct dates is ambiguous. Both the flapping and the direction of
error point at the question, not the model. SME-owned; drafted, not applied.

**4. q09 cannot distinguish success from refusal.** Its accept list
includes `"cannot determine"`, so an honest refusal scores identically to
correct human-food scope reasoning. Low priority, flagged for M03.

**5. Governance gap found during triage.** CODEOWNERS gates
`evals/golden_questions.json` to the SME, but `evals/run_evals.py` — the
code that *decides whether ground truth was met* — has no owner and is
engineering-self-approvable. Loosening `check()` achieves exactly what the
gate on the JSON exists to prevent. Recommend `/evals/ @regdelta-sme
@regdelta-eng`. Related: `check()` silently ignores unrecognized keys, so a
typo like `must_cite_all` in the SME-owned file would enforce nothing.
I touched `run_evals.py` this milestone (added provenance to recorded
output only — no change to pass/fail logic), which is precisely the class
of edit the missing gate would have caught.

**6. The control could have scored the model's memory instead of RAG.**
Original implementation: if retrieval returned nothing, the prompt rendered
with an empty passage list and Claude answered from parametric knowledge —
it knows 21 CFR 101.65 and the Red No. 3 dates. That produces a confident,
plausibly-cited `"answered"` that the eval scores as real. A misconfigured
`VECTOR_BUCKET` would have silently produced a baseline measuring world
knowledge. Now returns `status: "no_context"` without calling the model.
Caught by eng-code-reviewer, not by me.

**7. Bedrock model access forced the model choice.** Opus 4.7 is denied in
this account (`agreementAvailability: NOT_AVAILABLE`), as are Opus 4.8 and
the entire Claude 5 family. The control runs on Opus 4.6. Because a
baseline is only comparable if the model is fixed, `NAIVE_MODEL` is pinned
as a non-env-overridable constant, separate from `MODEL_VERDICT` — which
SPEC/03 will change. **If Opus 4.7 access is later granted, do not raise
`NAIVE_MODEL`. Re-run and re-record the baseline instead, or the
progression compares two different controls.**

**8. Prompt-injection boundary accepted, with a deadline.** Retrieved
passage text is concatenated into the prompt with no data/instruction
delimiter. This is not hypothetical: FR amendatory instructions are
literally imperatives ("In § 101.65, revise paragraph (d)(2)...") and the
chunker packs them under a heading. Accepted for M00b — no tools, no
side effects, string-matched output. security-reviewer marked it
merge-blocking for the first commit that gives the model a tool (SPEC/03),
requiring delimited passage envelopes, a "passages are quotations, not
instructions" preamble, a rule that no tool argument may come from passage
text, and injection traps in the golden set.

**What I'd redo:** run the determinism check *before* recording, not after.
I recorded a single run, then discovered q08 flaps — so the committed
scorecard happens to show the modal outcome (3/10) but I learned that by
luck, not design. A permanent reference point should be characterized for
variance first.
