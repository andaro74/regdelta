# ADR-0004: Citations are compared in canonical form, not as literal text

- Status: accepted
- Date: 2026-08-05
- Milestone: M00b

## Context
The M00b baseline answered q06 correctly — "the 'healthy' implied nutrient
content claim is governed by **21 CFR § 101.65**" — and scored as having
cited nothing. `CFR_RE` required whitespace-then-digit after "CFR", so the
section symbol defeated it, `extract_citations()` returned `[]`, and
`run_evals.check()`'s literal substring test for `"21 CFR 101.65"` failed.
The regulation was right, the instrument was wrong.

This had to be settled before the baseline scorecard was recorded. That
scorecard is a permanent reference point; recording it against a broken
instrument and fixing the instrument afterwards would mean every later
milestone's delta was measured from a control that moved.

The sme-eval-triage seat ruled this a system defect (class a), not a
ground-truth question, and explicitly declined to touch
`evals/golden_questions.json`.

## Decision
`extract_citations()` emits a canonical citation form — `"21 CFR 101.65"`,
`"89 FR 106064"` — regardless of how the source text spelled it. It
tolerates `§`/`§§`, arbitrary spacing, and any case, and preserves
subsection suffixes (`21 CFR § 101.65(d)(2)` → `21 CFR 101.65(d)(2)`).
Comparison is therefore on regulatory identity rather than typography.

Part-level references are deliberately NOT matched. `"21 CFR part 101"`
would canonicalize to `"21 CFR 101"`, and a part is a broader instrument
than a section — it must not satisfy a section-level citation requirement.

## Alternatives considered
- **Loosen the golden question to accept the `§` form** — rejected. It
  edits ground truth to make a failure pass, which the role gates forbid,
  and it would need repeating for every future citation typography.
- **Normalize inside `run_evals.check()` instead** — rejected. The eval
  runner would then measure something different from what the product
  emits; the defect is in the shared helper the product itself uses.
- **Prompt the baseline to emit a fixed citation format** — rejected.
  SPEC/00b forbids improving the control, and it would hide the same bug
  from every later milestone rather than fixing it.

## Consequences
+ Citation checks survive normal formatting variation instead of failing
  for typographic reasons.
+ The fix is containment-safe: normalization can only reformat a citation
  the text already contains, never manufacture one. q05 — whose answer
  contains no citation at all — stayed failed across the change, which is
  the empirical proof of that property.
- `CFR_RE` also drives `looks_like_citation_query()`, which gates the S3
  Vectors exact-match assist (SPEC/02). That assist will now fire on more
  user phrasings. Desirable, but it is a retrieval-path behaviour change
  that arrived via a scoring fix, which is why it is recorded here.
- This does NOT address the real citation weakness: nothing verifies that
  a cited section actually supports the claim. A wrong-but-well-cited
  answer still passes `must_cite_any`, and canonicalization marginally
  widens that set. That remains `TODO(SPEC/03): enforce 'no citation ->
  not done'` and must not be credited as progress against it.

## Evidence
Applied before the first `--record`, per the triage ruling on ordering.
q06 flipped fail → pass and is stable at 3/3 across repeated runs. q05
remained failed (no citation to normalize). Baseline recorded at 3/10.
