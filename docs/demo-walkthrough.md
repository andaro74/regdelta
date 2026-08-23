# The Product Demo — a 5-minute walkthrough

This is the product-side demo: what to open, what to click, what to say.
The governance demo ("one change, three doors") is separate —
[docs/governance/demo-script.md](governance/demo-script.md).

**Live demo:** https://d2rdgeiujg622n.cloudfront.net

## Before you open anything

- **The demo is already on.** The always-on tier (S3 Vectors) serves it; you
  do **not** need `make up`. That command brings up the ephemeral OpenSearch
  hot tier, bills ~$0.24/hr from the moment it exists, and is only needed for
  the optional Act 5.
- **Each uncached question costs ~12 seconds and ~5,900 Bedrock Opus
  tokens**, against a daily account cap that is not adjustable
  (`make opus-headroom` shows what is left). A demo is cheap; a loop is not.
- Nothing to start, no local server. Just a browser.

## Act 1 — Open the page (30 sec)

Top to bottom:

| Area | What to say |
|---|---|
| Four instrument tiles | "Which tier answered, was it cached, how fast was retrieval, how long did the whole request take." Every value comes from the response body of the last request — nothing is inferred. |
| Canned-scenario buttons | The demo scenarios, one per entry in `evals/scenarios.json` — a real company profile, Nordvale Foods. |
| Question box | Anyone can type their own question. |
| Cross-tier panel | Only matters for Act 5. |

**Tick "bypass the response cache"** before the first ask, so the audience
sees an answer being computed, not replayed. (It defaults to unticked because
the demo URL is public: every bypassed ask spends ~5,900 Opus tokens against
a non-adjustable daily cap, and cache hits are free.)

## Act 2 — The money shot (2 min)

Click **"'Healthy' claim — did the deadline move?"** and let the ~12 seconds
pass ("it's reading the actual Federal Register documents"). The verdict
table fills in:

| | |
|---|---|
| **Product** | strawberry-frosted granola bar |
| **Trigger** | updated 'healthy' claim definition, 21 CFR 101.65(d) |
| **Required change** | food-group-equivalent and nutrients-to-limit criteria |
| **Real deadline** | **2028-02-25** |
| **Confidence** | 0.97 |
| **Citations** | 89 FR 106064 · 90 FR 10592 |

**The point to land:** FDA delayed the rule's *effective* date. A normal
person — and a normal chatbot — slides the deadline forward too. It did not
move; the prose quotes FDA saying *"the compliance date remains unchanged at
this time."*

Then: **"Naive RAG scores 4 out of 20 on this question set. This scores
18."** That is the product.

Now the cache beat — and mind the mechanics: **a bypassed ask skips the
cache write too** (SPEC/04 control 1), so the ask you just did stored
nothing. **Untick the bypass box and click the same button again**: this one
is a ~12 s `miss` that populates the cache. **Click a third time** → back in
well under a second, labelled `hit`, with the tier and latency greyed and
labelled as provenance of the *stored* answer — nothing was retrieved for
this request. That is the cost story, told honestly. (To skip the middle
wait on stage, do one un-ticked ask before the show starts.)

## Act 3 — When it refuses to answer (1 min)

Click **"Are we affected? — the question that pauses."** The question carries
no product and no claim, so there is no honest answer for *this* asker. The
page renders **NEEDS HUMAN REVIEW**, the reason, and notes that a resume
capability was minted — without printing the token.

Line: "Below 0.7 confidence it stops and asks a human. In compliance,
confidently wrong is worse than slow."

## Act 4 — Exploring the data (3 min)

Three layers, cheapest to deepest.

**a) Click a citation.** Every citation links to federalregister.gov or
ecfr.gov. "Go read the sentence yourself. If we're wrong, you can prove it."

**b) The corpus** — S3, the `regdelta-core-corpusbucket…` bucket
(`CorpusBucketName` in the stack outputs). Three prefixes: `raw/` (what FDA
published, flat) → `parsed/` (flat) → `chunks/`, which is foldered by CFR
part (`101/` labeling, `74/` color additives, `170/` food additives). A
scheduled poller checks the
Federal Register daily at 12:00 UTC; the corpus grew from 4 documents to 52
on its own.

**c) The amendment graph** — DynamoDB, the `RegistryTable…` table. ~1,270
rows, most of them bookkeeping (chunk pointers, document records). **A
handful of typed edges are the actual product.** Filter `sk` beginning with
`SUPERSEDES`:

```
DOC#2025-03118  SUPERSEDES#2024-29957#effective_date   new_date = 2025-04-28
DOC#2025-03118  CONFIRMS#2024-29957#dates_confirmed    applies_to = "compliance date"
```

Say this slowly — it is the architectural punchline: one document moved the
effective date and confirmed the compliance date, and those are two separate
facts stored as two separate rows. Timeline questions are answered by
*looking up those rows*, never by asking a language model what a paragraph
feels like.

The other edges tell the Red No. 3 story: the order was **stayed**
2025-02-18, the stay was **lifted** 2026-08-05, and both dates were
**confirmed, not moved** (food: 2027-01-15). Type *"When exactly must we stop
using FD&C Red No. 3?"* into the box and watch it get the existing-inventory
safe harbour and the un-moved date right.

## Act 5 (optional) — the infrastructure flip (costs money)

`make up` brings the OpenSearch hot tier online (~20 min; ~$0.24/hr until
`make down`). Ask the same question with bypass on; the tier badge flips to
`aoss` and the cross-tier panel reports **EQUAL** — same citations as sets,
same `real_deadline` exactly. "The answer does not change when the
infrastructure does." `make demo-parity` is the recorded version of the same
claim. Run `make down` when finished.

## Two things not to say

The repo is strict about both, and someone technical will check:

- ❌ "The second tier is hybrid search" / "it's faster" →
  ✅ **"Same algorithm, different infrastructure."** Hybrid measured worse
  than vector-only and is off (ADR-0009); the latency justification was
  measured and retired (ADR-0012).
- ❌ "20 out of 20" → ✅ **"18 out of 20, and the two misses are known
  defects with write-ups"** (`milestones/M07/q12-q15-triage.md`). The honesty
  is part of the pitch.
