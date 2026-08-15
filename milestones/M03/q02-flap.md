# q02: a flap, a bug in the answer layer, and a wrong finding of my own

Superseded record, kept because the correction is the useful part. Written
2026-08-15 during M03; **the central claim in its first version was wrong** and
is corrected below rather than deleted.

## What was first reported, and why it was wrong

The first version of this file said q02 required an answer **the corpus cannot
support**, on the strength of a scan showing zero hits across all 990 chunks
for `not adulterated`, `may remain`, `manufactured before`, `manufactured
prior`, `existing stocks` and `sell-through`. It put q02 in the same class as
the q07 fabricated exemption and the q03 uncitable TTB proposition.

**That was a methodological error.** The scan searched for the QUESTION's
phrasings, not for the SOURCE's. The proposition is squarely citable and always
was — 90 FR 4628 (doc 2025-00830), section VI. Conclusion, chunk `#0021`:

> "In accordance with 21 CFR 80.32(h), all certificates for existing batches
> and portions of batches of FD&C Red No. 3 will cease to be effective for use
> in food on the effective date for the removal of § 74.303 … Use of FD&C Red
> No. 3 after its certificate ceases to be effective will result in such food
> or ingested drugs being adulterated. **When FD&C Red No. 3 has been used in
> food or ingested drugs while its certificate is still effective, such food or
> ingested drugs will not be regarded as adulterated by reason of the use of
> such color additive.**"

"will **not be regarded as** adulterated" does not contain the substring "not
adulterated", which is the entire reason the scan came back empty. Falsifiable
by reading that chunk, or by FR full-text search for "will not be regarded as
adulterated by reason of the use".

The lesson is cheap to state and was not: **searching a corpus for the words an
answer would use does not tell you whether the corpus supports the answer.**
Search for the source's language, or read the document.

## What was actually wrong: the answer layer truncated the answer away

`nodes._passages` fenced retrieved passages at `untrusted.SNIPPET` — 1200
characters, a constant inherited from the reranker, where it is correct because
ranking only needs to see what a paragraph asserts.

Chunk `2025-00830#0021` is **1891 characters** and the decisive sentence starts
at character **1811**. Retrieval ranked that chunk **second** — it did its job
— and the verdict node then cut the last 700 characters off and reported that
its sources did not address the question. Every chunk over 1200 characters was
losing its tail, on every question; q02 is only where it showed.

Fixed by bounding verdict passages at `config.CHUNK_MAX_CHARS`, the chunker's
own ingest cap, so the passage is bounded by construction and no second,
smaller cap removes evidence. `test_a_passage_is_not_cut_at_the_rerankers_snippet_length`
pins it. After the fix q02 answers correctly and quotes the sentence above.

## The defect in the question that was real

Independent of both of the above, and the reason q02 was rewritten rather than
left alone: **the accept token `manufactured before` matched the negation of
the intended answer.**

Measured over ten live runs before the fix, q02 passed about 1 in 4, and every
passing run matched inside this sentence:

> "The sources do not provide an explicit FDA enforcement-discretion statement
> or transition period for products **manufactured before** the effective date
> but still in commerce after it."

That is an answer stating it *cannot confirm* the allowance, scoring as though
it had confirmed it. The failing runs said the same thing as "regardless of
when it was manufactured" and scored zero. The check was tracking phrasing in
both directions — the fourth defect the q07 ruling named, reproduced.

## What was done

q02 was **rewritten, not patched**, under an SME-seat ruling recorded in its
`note` field in `evals/golden_questions.json`. The accept tokens now match the
source's own language and additionally require the certification mechanism the
order turns on (21 CFR 80.32(h)); `manufactured before` is removed and must not
return. `must_not_contain` now bans the wrong CONCLUSION — "adulterated
regardless of when" — rather than any vocabulary. Five hand-written answers
were replayed through the real scorer to confirm it discriminates, including
the pre-fix answer that used to pass, which now fails.

## What still stands from the first version

Nothing about the corpus scan. These two do:

- q02 is a genuine trap and belongs in the trap set.
- The verdict prompt was never tuned to emit the accept phrase, and must not
  be. That would be the q03 false pass rebuilt with a milestone deadline as the
  motive — and it is now unnecessary, because the answer is in the document.
