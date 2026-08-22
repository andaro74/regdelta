# pm-spec-reviewer on the SPEC/07 item 5 diff — findings and disposition

Run 2026-08-21 against the first draft of SPEC/07 item 5 and its Done-when
clause. Verdict: **request changes**, five HIGH blockers.

The review is recorded here rather than summarised, because two of its findings
were defects in the **mechanism** and not in the prose — the register was
changed, not just the text describing it.

| # | severity | finding | disposition |
|---|---|---|---|
| 1 | HIGH | "an entry matching nothing **fails the run**" is stated absolutely and is false: `unevaluated` entries are reported and do not gate. The mutation set did not cover it either. | **Accepted.** Spec bullet split into the gating case and the exempt one, naming the exemption as a hole. Mutation added pinning that it reports and does **not** gate. |
| 2 | HIGH | The spec asserts "every admission cites a ruling" but `ruling` was not one of the matched fields — an entry with no ruling key admitted the failure and printed `— None`. Nothing enforced the mechanism's most load-bearing property. | **Accepted, and it was a real hole.** `replay_history.cites_ruling` added: an entry citing nothing, or citing a document not in the tree, admits nothing and fails the run as `UNCITED ADMISSION`. Two mutations and three tests added. |
| 3 | HIGH | "with the survivors count recorded" is satisfied by recording "4 survivors out of 10". | **Accepted.** Done-when now requires the count **equal to zero**; any survivor blocks the milestone. |
| 4 | HIGH | "every refusal exercised" — "refusal" undefined, set not enumerated, no mapping from the six constraints to the ten mutations, and two of the six are not refusals. | **Accepted.** Done-when criterion 2 enumerates the eleven required cases; criterion 1 requires each property to be named beside the exercise that establishes it. |
| 5 | HIGH | Out of scope unchanged, so the spec silently widened the SME ruling: the seat scoped this to **one** entry, the spec described an open-ended register. | **Accepted.** Out of scope now caps M07 at one entry and says a second is a new seat ruling. `test_m07_adds_exactly_one_entry` enforces it. |
| 6 | MEDIUM | Done-when named a non-runnable invocation, an undefined "green run", and no artifact paths. | **Accepted.** Criterion 4 names `python evals/replay_history.py --no-admissions` and `milestones/M07/`. |
| 7 | MEDIUM | Solutioning: the spec pinned the implementation file, the register filename, the CLI flag spelling and the literal token `ADMIT`. | **Accepted.** SPEC/06's carve-out adopted — names and invocation shape are engineering's and may change without reopening the clause. The `ADMIT` bullet restated as the property: "reported as admitted, never as passing". |
| 8 | MEDIUM | The criteria were authored with the artifacts in hand and map 1:1 onto tests that already pass, so they cannot discriminate — the 2026-08-15 failure mode this repo has been burned by twice. | **Accepted.** The refusal set is now enumerated in the spec, adversarially, and is falsifiable by someone who has never opened `admission_mutations.py`. Its two extra cases are exactly findings 1 and 2. |
| 9 | MEDIUM | The un-ruled OIDC PROPOSED AMENDMENT does not belong in the spec: normative text sitting beside a comment saying it is wrong, invisible in rendered Markdown, in the spec whose subject is that gate changes must be visible and owned. | **Accepted.** Moved to `milestones/M07/spec07-oidc-amendment.md`; item 2 left unamended with a one-line pointer. The "WHY THIS IS IN THE DONE-WHEN" rationale comment moved out too. |
| 10 | LOW | Homing item 5 in SPEC/07 creates no schedule problem — it is closer to a precondition for Door 1 than to a fourth door — but the spec reads as though it were new build. | **Accepted.** Item 5 now says it was implemented before the item was written and that M07 owes the demonstration, not the build. |
| 11 | LOW | Only about three sentences of item 5 are product scope; the rest is engineering detail that came along with it. | **Accepted.** The product claim is now stated as such, first, in one sentence. |
| 12 | LOW | Items 1–4 carry no Done-when clause at all; item 5 now carries the strictest in the file. For the last milestone that is backwards. | **Open, not addressed in this diff.** Correct, and pre-existing. Raised in the M07 journal rather than fixed silently: adding observables to items 1–4 is a Done-when change and therefore a PM ruling of its own. |
| 13 | LOW | Door 1's Done-when clause still points at a `demo-script.md` caption GitHub does not emit, and a code-owner requirement unsatisfiable with one collaborator. | **Open, and tracked.** Not made worse by this diff. It is M07's other blocking problem and is being worked separately — the second seat account is the user's to create, and `demo-script.md`'s caption has to be rewritten once the seats are re-split. |

## Where the reviewer was right about something I had asserted

Findings 1 and 2 are the ones worth naming. Both were places where SPEC/07
stated a property as a fact and nothing in the code required it — the same
shape as ADR-0005's original defect, which explained a deadlock with a
plausible mechanism and called it "verified empirically".

Finding 2 in particular: ADR-0015's own Consequences section says *"the only
thing requiring a ruling behind an entry is a convention"*, and I wrote that
sentence, and then wrote a spec bullet asserting the convention as a
guarantee. The reviewer read the two against each other. It is a check now.
