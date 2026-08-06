"""Central config. Model ids and thresholds are values, never literals in
node code (CLAUDE.md rule)."""
import os

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bedrock model ids (inference profiles verified available in-account).
# MODEL_VERDICT is provisional — SPEC/03 pins the verdict model.
MODEL_FAST = os.environ.get("MODEL_FAST", "us.anthropic.claude-sonnet-5")
MODEL_VERDICT = os.environ.get("MODEL_VERDICT", "us.anthropic.claude-opus-5")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")
EMBED_DIM = 1024

CONFIDENCE_HITL_THRESHOLD = float(os.environ.get("HITL_THRESHOLD", "0.7"))

SSM_SEARCH_ENDPOINT = "/regdelta/search/endpoint"
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

# Chunking (SPEC/01): pack whole CFR paragraphs, never split mid-paragraph.
CHUNK_MAX_CHARS = int(os.environ.get("CHUNK_MAX_CHARS", "2400"))
CHUNK_BREAK_CHARS = int(os.environ.get("CHUNK_BREAK_CHARS", "600"))
