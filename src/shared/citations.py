"""Citation helpers. TODO(SPEC/03): enforce 'no citation -> not done'.

extract_citations emits a CANONICAL form ("21 CFR 101.65", "89 FR 106064")
regardless of how the text spelled it, so downstream comparison is on
regulatory identity rather than typography. Models routinely write
"21 CFR § 101.65"; the un-normalized regex scored that as no citation at
all (M00b/q06). Normalization can only reformat a citation the text
already contains — it can never manufacture one, which is why it does not
inflate scores. See milestones/M00b/README.md.

Deliberately NOT matched: part-level references ("21 CFR part 101"). A
part is a broader instrument than a section, and canonicalizing it to
"21 CFR 101" would let it satisfy a section-level requirement.
"""
import re

CFR_RE = re.compile(
    r"\b(\d+)\s+CFR\s*(?:§{1,2}\s*)?(\d+\.\d+(?:\([a-z0-9]+\))*)", re.IGNORECASE)
FR_RE = re.compile(r"\b(\d+)\s+FR\s+(\d+)\b", re.IGNORECASE)


def extract_citations(text: str) -> list[str]:
    return ([f"{title} CFR {section}" for title, section in CFR_RE.findall(text)]
            + [f"{vol} FR {page}" for vol, page in FR_RE.findall(text)])


def looks_like_citation_query(query: str) -> bool:
    """Used by the S3 Vectors tier to trigger the exact-match assist."""
    return bool(CFR_RE.search(query) or FR_RE.search(query)
                or "red no. 3" in query.lower())
