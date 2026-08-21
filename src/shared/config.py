"""Central config. Model ids and thresholds are values, never literals in
node code (CLAUDE.md rule)."""
import os

REGION = os.environ.get("AWS_REGION", "us-west-2")

# Bedrock model ids. Verified invocable in this account (us-west-2) with
# bedrock-runtime Converse; everything newer is listed by
# list-foundation-models but denied at invoke time:
#   Opus 4.7 / 4.8, Sonnet 5, Opus 5, Fable 5, Haiku 4.5
#     -> AccessDeniedException, agreementAvailability=NOT_AVAILABLE.
# Raise MODEL_VERDICT to Opus 4.7 once account model access is granted.
# MODEL_VERDICT is provisional — SPEC/03 pins the verdict model.
MODEL_FAST = os.environ.get("MODEL_FAST", "us.anthropic.claude-sonnet-4-6")
MODEL_VERDICT = os.environ.get("MODEL_VERDICT", "us.anthropic.claude-opus-4-6-v1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")
EMBED_DIM = 1024

CONFIDENCE_HITL_THRESHOLD = float(os.environ.get("HITL_THRESHOLD", "0.7"))

# ------------------------------------------------------------- agent graph (03)
# Bedrock prompt caching for the static system preamble (SPEC/03 "Model
# policy"). On by default because the preamble is identical across every
# question in a golden run, so a 10-question run reads the cache nine times.
# `nodes._converse` falls open if the model rejects the cachePoint block —
# an unsupported optimisation must not block a measurement.
PROMPT_CACHE = os.environ.get("PROMPT_CACHE", "1") == "1"

# How many cross-referenced CFR sections the crossref agent will resolve, and
# how many chunk ids it takes per citation. A bound rather than a tuning knob:
# "as defined in §" chains can fan out, and an unbounded expansion would crowd
# the verdict prompt with sections nobody asked about.
CROSSREF_MAX = int(os.environ.get("CROSSREF_MAX", "4"))

SSM_SEARCH_ENDPOINT = "/regdelta/search/endpoint"

# ----------------------------------------------------------- retrieval (02)
# Ranking knobs, here rather than inline so both tiers read the same numbers
# (CLAUDE.md: thresholds are values, never literals in node code).
#
# RETRIEVAL_PER_DOC_CAP — how many of the 8 page slots one document may take
# before every other candidate has been considered. Deferred candidates
# back-fill, so this changes the ORDER of a full page, never its length.
#
# Measured, and worth recording in full because it is NOT monotonic:
# cap 3 -> 9/9 probes, 4 -> 8/9, 5 -> 9/9, 6 -> 7/9, 8 -> 7/9. A value that
# fails between two passing values means nine probes cannot robustly determine
# this constant.
#
# STALE (ADR-0009 fact 2): that row is Tier A measured BEFORE 7d65a07, which
# deleted the top-N-distinct-documents heuristic, its window bound, its
# per-document chunk cap and the grouped-vs-interleaved ordering question. It
# describes a retrieval path that no longer exists and must not be compared
# against a live Tier B row. Tier B at 11489e5: 3 -> 7/9, 4 -> 8/9, 5 -> 7/9 —
# non-monotonic there too, which is what the argument actually rests on.
# Re-sweeping Tier A costs nothing and would settle it. The MECHANISM (one document may not crowd the page) is
# load-bearing and demonstrable — removing it entirely drops two probes — but
# the exact bound is a design judgement the probe set cannot settle. It is the
# softest number in M02 and the first thing to re-examine if a probe regresses.
#
# RETRIEVAL_ASSIST_WEIGHT — the structural lane's weight in RRF, relative to
# the relevance lane's 1.0. Kept at parity after measurement: down-weighting
# it is the intuitive move and measured strictly worse (1.0 -> 8/9 probes,
# 0.8 -> 7/9, 0.5 -> 5/9), because discounting the lane only re-buries the
# DATES paragraphs it exists to surface. The knob stays because the mechanism
# is real and M03 may want it; the default records what the measurement said.
#
# RETRIEVAL_STRUCTURAL_KINDS — the chunk kinds the structural lane searches.
# These are the paragraphs that state what a document DOES: its DATES block
# and its amendatory instructions. They carry the deadlines and the CFR edits,
# they are short, and every relevance signal under-ranks them for a verbose
# question — which is the entire reason the lane exists. `summary` is
# deliberately out: it is context, not an operative provision, and including
# it triples the lane without adding an answer.
#
# RETRIEVAL_LEXICAL_LANE — whether Tier B fuses a BM25 lane into its relevance
# lane. DEFAULT OFF per ADR-0009 Ruling 3, resolved as (a). Measured: with the
# lane on, Tier B scores 7/9 against Tier A's 9/9, and the one chunk it loses
# (`2025-03118#0003`, which states "the compliance date remains unchanged at
# this time") is ranked 14th by BM25 on r03 and not returned at all on r01,
# because BM25 over verbose regulatory prose prefers shorter chunks that repeat
# the query's terms without answering it. The only weight at which Tier B passes
# criterion 1 is 0.05, where the lane has stopped affecting the outcome.
#
# The flag exists rather than the lane being deleted because the ruling is
# REVERSIBLE ON A NAMED CONDITION: author a probe the lexical lane wins — an
# expected_chunk_ids member BM25 places in the top-8 and the vector lane does
# not — and this default flips back. Nine probes can witness a counterexample;
# they cannot establish that BM25 never helps, and the ruling claims only the
# former. Off, Tier B's relevance lane is pure kNN, which makes it the same
# algorithm as Tier A on different infrastructure — that is the honest reading.
# Tier B's remaining CANDIDATE justification is latency, and it is UNMEASURED:
# the only proxy in the repo (whole-run `wall_s`) has AOSS slower in every
# recorded pair, 11.6 vs 6.7 at b16f596. SPEC/04 homes the criterion. Do not
# narrate "faster" before it passes, and do not say "concurrent load" at all —
# that is M06's and was struck from the spec (pm-spec-reviewer B1, B3).
# (An earlier version of this comment claimed the flag-off path had to
# avoid single-lane RRF because it "re-scores by rank". That was false — RRF over
# one lane is rank-preserving and truncating, so it equals slicing — and
# aoss_tier.py now has one code path. Engineering review caught the claim.)
RETRIEVAL_LEXICAL_LANE = os.environ.get("RETRIEVAL_LEXICAL_LANE", "0") == "1"
RETRIEVAL_STRUCTURAL_KINDS = tuple(
    k for k in os.environ.get("RETRIEVAL_STRUCTURAL_KINDS",
                              "dates,amdpar").split(",") if k)
RETRIEVAL_PER_DOC_CAP = int(os.environ.get("RETRIEVAL_PER_DOC_CAP", "3"))
RETRIEVAL_ASSIST_WEIGHT = float(os.environ.get("RETRIEVAL_ASSIST_WEIGHT", "1.0"))
CORPUS_BUCKET = os.environ.get("CORPUS_BUCKET", "")
REGISTRY_TABLE = os.environ.get("REGISTRY_TABLE", "")
STATE_TABLE = os.environ.get("STATE_TABLE", "")
VECTOR_BUCKET = os.environ.get("VECTOR_BUCKET", "")
VECTOR_INDEX = os.environ.get("VECTOR_INDEX", "chunks")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
SEMANTIC_CACHE = os.environ.get("SEMANTIC_CACHE", "0") == "1"
RERANK = os.environ.get("RERANK", "0") == "1"

# ------------------------------------------------------- spend (SPEC/06)
# WHAT A TOKEN COSTS IN THIS ACCOUNT, in dollars per million. SPEC/06's
# dashboard shows "Bedrock cost/query" and `loadtest/budget.py` refuses a run
# that would exceed its ceiling; both need a price, and a price hardcoded at
# either call site is a number nobody can trace.
#
# MEASURED, NOT QUOTED FROM A PRICE LIST. Cost Explorer, `UnblendedCost` divided
# by `UsageQuantity` per usage type, for the services "Claude <model> (Amazon
# Bedrock Edition)" and "Amazon Bedrock", on 2026-08-19 and 2026-08-20 — two
# days that agree to the cent. That matters because Bedrock's marketplace rate
# is NOT the first-party API list price: Opus 4.6 lists at $5.00/$25.00 and
# bills here at $5.50/$27.50, 10% higher. A budget guard built on the list price
# would under-count by 10% and quietly overshoot its ceiling.
#
# Keys are the model ids above, so a model swap cannot leave a stale rate
# behind: `budget.py` raises on a model it has no rate for rather than costing
# it at zero, which is the failure mode that matters — an unpriced model is
# free in every arithmetic that does not check.
#
# Re-derive with:
#   aws ce get-cost-and-usage --time-period Start=<d> End=<d+1> --granularity DAILY \
#     --metrics UnblendedCost UsageQuantity --region us-east-1 \
#     --filter '{"Dimensions":{"Key":"SERVICE","Values":["Claude Opus 4.6 (Amazon Bedrock Edition)"]}}' \
#     --group-by Type=DIMENSION,Key=USAGE_TYPE
BEDROCK_RATES_USD_PER_MTOK = {
    "us.anthropic.claude-opus-4-6-v1": {"input": 5.50, "output": 27.50},
    "us.anthropic.claude-sonnet-4-6": {"input": 3.30, "output": 16.50},
    "us.anthropic.claude-haiku-4-5": {"input": 1.10, "output": 5.50},
    "amazon.titan-embed-text-v2:0": {"input": 0.0199, "output": 0.0},
}

# THE ACCOUNT'S NON-ADJUSTABLE DAILY TOKEN CEILINGS, per model id.
#
# `aws service-quotas list-service-quotas --service-code bedrock`, quota
# `L-ED2BADF9` and its per-model siblings, every one reporting
# `Adjustable: false`. These are not budget preferences — AWS will not raise
# them on request — and they are the reason SPEC/06's 500-concurrent-user
# profile cannot run here: at 5,881.8 Opus tokens per uncached /query, 2,592,000
# is 440 queries for the whole day, and the profile spends that in 13.6 seconds.
# See milestones/M06/spec06-disposition-amendment.md.
#
# Carried in code rather than in prose so `loadtest/budget.py` can refuse a plan
# that exceeds them, which is a different refusal from exceeding the dollar
# ceiling: a run can be well inside its budget and still be impossible.
BEDROCK_DAILY_TOKEN_CAP = {
    "us.anthropic.claude-opus-4-6-v1": 2_592_000,
    "us.anthropic.claude-sonnet-4-6": 10_800_000,
    "us.anthropic.claude-haiku-4-5": 27_000_000,
}

# On-demand requests per minute for Titan Text Embeddings V2, also
# `Adjustable: false`. Every retrieval embeds, so this is the hard ceiling on
# any retrieval-concurrency profile: 100 calls per second, whatever drives them.
TITAN_EMBED_RPM_CAP = 6_000

# HTTP connections the retrieval path may hold open per client, and it is a
# measurement-validity number rather than a performance one. botocore defaults
# to 10; SPEC/06's disposition drives 90 retrieval calls per second, which is
# ~32 in flight on Tier A and ~80 on Tier B. Above the pool size the excess
# calls BLOCK in urllib3 — inside `router.retrieve()`, which is the interval
# the disposition's p95 is defined over — so the comparison would have been
# between two queues in this process rather than between two search backends.
# 128 covers the top step on the slower tier with room to spare; connections
# are created lazily, so a query Lambda serving one request still opens one.
RETRIEVAL_POOL_SIZE = int(os.environ.get("RETRIEVAL_POOL_SIZE", "128"))

# The dollar ceiling a load run may not cross. Approved by the human seat at
# M06 open. `loadtest/budget.py` refuses BEFORE spending anything if the plan
# exceeds it.
#
# It does NOT abort mid-run. This comment used to say it did — "the second is
# the one that matters" — and `loadtest.budget.Meter`, the thing that would
# have done it, has no caller outside its own tests. Corrected rather than
# implemented, because for THIS run a per-call meter is the wrong instrument:
# the disposition's Bedrock cost is three cents of a twenty-three-cent run, the
# rest is Lambda-seconds and OCU-hours that a token meter cannot express, and
# the control that actually bounds a runaway is the load driver's IAM grant —
# Titan embeddings and no other model. eng-code-reviewer, M06.
LOADTEST_BUDGET_USD = float(os.environ.get("LOADTEST_BUDGET_USD", "20.00"))

# ------------------------------------------------------------- graph (03)
# LangSmith tracing is FORCED OFF, and this is a data-egress control rather
# than a preference. `langgraph` pulls `langsmith` transitively (M03), and
# langsmith uploads prompts, inputs and outputs to a third-party SaaS endpoint
# when LANGSMITH_TRACING or LANGCHAIN_TRACING_V2 is truthy. For this product
# those payloads are the worst possible thing to leak by accident: the company
# profile a user submits (revenue tier, product lines) plus the regulatory
# analysis derived from it.
#
# It is off by default upstream, so this changes nothing today. It exists
# because the failure mode is a single environment variable — one `export
# LANGSMITH_TRACING=1` in a shell, one leftover value in a Lambda config — and
# nothing in the code would report it. Same reasoning as pinning versions:
# defaults are not decisions until they are written down. Setting the variables
# rather than reading them means an inherited value is overridden, not detected.
#
# Deliberately NOT configurable. If tracing is ever wanted, that is a decision
# about sending customer data to a third party, and it belongs in an ADR and a
# spec — not in an env var that already exists.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_OTEL_ENABLED"] = "false"

# ---------------------------------------------------------------- ingestion
FR_API = "https://www.federalregister.gov/api/v1"
ECFR_API = "https://www.ecfr.gov/api/versioner/v1"
FR_AGENCY_SLUG = "food-and-drug-administration"
FR_DOC_TYPES = ("RULE", "PRORULE", "NOTICE")

# ------------------------------------------------------- poller scope (SPEC/01)
# FDA is one agency publishing for food, drugs, devices, veterinary medicine and
# tobacco, so "agency = FDA" is not a subject filter. Unfiltered, the poller
# ingested a digital breast tomosynthesis reclassification, three more device
# reclassifications and a run of drug user-fee notices into a food-labeling
# corpus — 30 documents in two weeks, competing for the eight retrieval slots
# every answer gets.
#
# THE DISCRIMINATOR IS THE CFR REFERENCE, and it was chosen by measurement
# rather than taste. Against the 49 documents in the corpus on 2026-08-15:
#
#   21 CFR part <= 199   ->  the 6 documents this product is actually about
#                            (101 healthy rule + its delay, 74 Red No. 3 + the
#                            stay lift, 170/570 GRAS, 117 RTE food guide)
#   21 CFR part >= 200   ->  the 5 device documents, all of them
#
# TOPICS WERE TRIED AND ARE WRONG. The Red No. 3 order's topics are
# ['Color additives', 'Cosmetics', 'Drugs'] — no "Food labeling" anywhere — so
# a topic allowlist would drop the document half the golden set is about.
FR_FOOD_CFR_TITLE = 21
# Title 21 splits cleanly at 200: parts 1-199 are food (70-82 colour additives,
# 100-169 labelling and standards, 170-199 food additives); 200+ are drugs,
# 500s veterinary, 800s devices, 1100+ tobacco.
FR_FOOD_CFR_MAX_PART = int(os.environ.get("FR_FOOD_CFR_MAX_PART", "199"))

# What to do with a document that cites NO CFR part at all — 38 of the 49, and
# unfilterable by any other structured field: they carry no topics either (all
# 26 sampled were empty), so only the title distinguishes "Food Safety
# Modernization Act Third-Party Certification" from "Prescription Drug User Fee
# Rates", and title matching is not a scope rule.
#
# Default EXCLUDE. A document citing no CFR part amends no regulation, so it
# cannot be the subject of "what changed and what is the deadline" — this
# product's whole question. That is a scope judgement, which is why it is a
# flag and not an assumption: POLL_REQUIRE_CFR=0 restores the old behaviour and
# takes the drug and device fee notices back with it.
POLL_REQUIRE_CFR = os.environ.get("POLL_REQUIRE_CFR", "1") == "1"
POLL_LOOKBACK_DAYS = int(os.environ.get("POLL_LOOKBACK_DAYS", "7"))

# ------------------------------------------------- ingestion input hardening
# The four items deferred at M01 close (security review MEDIUM/LOW). Every
# value below is a boundary on data this system does not author: FR/eCFR API
# responses, and model output derived from them.

# Fetch allowlist. Only these hosts, only https. Both the FR document JSON
# and the eCFR XML arrive from responses that then name the NEXT url to fetch
# (`next_page_url`, `full_text_xml_url`) — so the fetch target is attacker-
# reachable if either API is spoofed or compromised, and redirects are
# followed by default. Without a host check that is a straight SSRF into the
# Lambda's network position, including the IMDS endpoint.
ALLOWED_FETCH_HOSTS = frozenset({"www.federalregister.gov", "www.ecfr.gov"})
ALLOWED_FETCH_SCHEMES = frozenset({"https"})

# Response size cap. `r.read()` was unbounded, so one oversized (or hostile)
# response could exhaust Lambda memory before anything validated it.
#
# 8 MiB, lowered from 24 MiB. The cap bounds the *source* bytes, not memory:
# ET.fromstring builds a tree several times the source size, then chunks, then
# embeddings — all inside a 1024 MB processor (infra/core/core_stack.py:140).
# libexpat's billion-laughs guard is active but only caps amplification at
# ~100x above an 8 MiB threshold, so a 24 MiB source was not bounded to 24 MiB
# of parsed text. Flagged by security review of this branch.
#
# 8 MiB is sized off the real corpus, not off the hazard: the largest demo
# document is the "healthy" final rule at 389 chunks (~930 KB of chunk text,
# a few MB of raw FR XML). That is several times headroom while keeping the
# parsed tree comfortably inside the function. Raise this only together with
# memory_size, and only against a document that actually needs it.
MAX_FETCH_BYTES = int(os.environ.get("MAX_FETCH_BYTES", str(8 * 1024 * 1024)))

# Chunk cap. embed() issues one Bedrock call per chunk, so chunk count is a
# direct spend multiplier on a number derived from fetched document length.
# The largest real demo doc is 389 chunks; 2000 is ~5x headroom and still
# bounds the blast radius. Exceeding it fails the message rather than
# truncating — a partial document in the index is a wrong answer with a
# citation, which is worse than a DLQ entry.
MAX_CHUNKS_PER_DOC = int(os.environ.get("MAX_CHUNKS_PER_DOC", "2000"))

# Pagination cap. `next_page_url` is response-controlled and the host
# allowlist bounds where the poller goes, not how many times — a
# self-referencing page would loop until the Lambda timeout. 100 pages x 100
# per_page is 10k documents, far past any real FDA week.
MAX_POLL_PAGES = int(os.environ.get("MAX_POLL_PAGES", "100"))

# doc_type is a filter key in the SPEC/02 retrieval contract. An out-of-enum
# value does not error — it silently matches no filter, so the document
# becomes invisible to exactly the queries that should find it. The prompt in
# metadata.py lists these; nothing enforced them until now.
DOC_TYPES = frozenset({
    "final_rule", "delay_notice", "order", "proposed_rule", "notice",
    "guidance", "cfr_section",
})

# Plausibility window for extracted dates. Not correctness — a date outside
# this range is a parse or hallucination artifact, not a regulatory deadline.
# Compliance dates run years out (Red No. 3 drugs: 2028), so the upper bound
# is generous.
MIN_DOC_YEAR = int(os.environ.get("MIN_DOC_YEAR", "1990"))
MAX_DOC_YEAR = int(os.environ.get("MAX_DOC_YEAR", "2100"))

# Demo corpus (SPEC/01): FR doc numbers verified against the live FR API.
#   2024-29957  "healthy" final rule            (89 FR 106064, pub 2024-12-27)
#   2025-03118  effective-date delay rule       (90 FR 10592,  pub 2025-02-25)
#   2025-00830  Red No. 3 revocation order      (90 FR 4628,   pub 2025-01-16)
BACKFILL_FR_DOCS = ("2024-29957", "2025-03118", "2025-00830")

# Tracked CFR sections: (title, section, [backfill version dates]).
# "current" resolves to the latest amendment date from the eCFR versioner,
# which keeps re-runs idempotent. The dated entries are pre-amendment
# baselines so point-in-time questions have text to cite.
TRACKED_CFR_SECTIONS = (
    ("21", "101.65", ("2024-12-01", "current")),
    ("21", "101.13", ("current",)),
    ("21", "74.303", ("2025-01-01", "current")),
)

# ----------------------------------------------------------- baseline (00b)
# The control's knobs. Frozen at close of M00b — changing either invalidates
# every delta measured against the baseline scorecard (ADR-0002). These are
# deliberately NOT env-overridable: MODEL_VERDICT moves when SPEC/03 pins the
# verdict model or when Opus 4.7 access lands, and the control must not move
# with it or the recorded numbers stop being comparable.
NAIVE_TOP_K = 8
NAIVE_MODEL = "us.anthropic.claude-opus-4-6-v1"

# Chunking (SPEC/01): pack whole CFR paragraphs, never split mid-paragraph.
CHUNK_MAX_CHARS = int(os.environ.get("CHUNK_MAX_CHARS", "2400"))
CHUNK_BREAK_CHARS = int(os.environ.get("CHUNK_BREAK_CHARS", "600"))
