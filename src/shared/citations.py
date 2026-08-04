"""Citation helpers. TODO(SPEC/03): enforce 'no citation -> not done'."""
import re

CFR_RE = re.compile(r"\b\d+\s+CFR\s+\d+(?:\.\d+)?(?:\([a-z0-9]+\))*", re.I)
FR_RE = re.compile(r"\b\d+\s+FR\s+\d+\b", re.I)


def extract_citations(text: str) -> list[str]:
    return [*CFR_RE.findall(text), *FR_RE.findall(text)]


def looks_like_citation_query(query: str) -> bool:
    """Used by the S3 Vectors tier to trigger the exact-match assist."""
    return bool(CFR_RE.search(query) or FR_RE.search(query)
                or "red no. 3" in query.lower())
