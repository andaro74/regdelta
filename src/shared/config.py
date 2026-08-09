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
# this constant. The MECHANISM (one document may not crowd the page) is
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

# ---------------------------------------------------------------- ingestion
FR_API = "https://www.federalregister.gov/api/v1"
ECFR_API = "https://www.ecfr.gov/api/versioner/v1"
FR_AGENCY_SLUG = "food-and-drug-administration"
FR_DOC_TYPES = ("RULE", "PRORULE", "NOTICE")
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
