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


# Bare "§ 101.13" — a section with no title, which is how Federal Register
# preambles and amendatory instructions actually write cross-references.
BARE_SECTION_RE = re.compile(r"§{1,2}\s*(\d{2,3}\.\d+(?:\([a-z0-9]+\))*)")


def extract_section_refs(text: str, default_title: str = "21") -> list[str]:
    """CFR sections a passage points at, INCLUDING the bare `§ NNN.NN` form.

    Deliberately separate from `extract_citations` rather than a widening of
    `CFR_RE`. That regex requires a title number, and `query_citation_ids`
    runs `extract_citations` over every incoming QUERY — which is M02's
    measured retrieval path, 9/9 at recall 1.0. Loosening a shared regex to fix
    a graph-layer defect would silently change what M02 measured, and this repo
    has a standing rule against exactly that trade.

    The default title is a scoping assumption, stated rather than hidden: this
    corpus is FDA food labeling, so a bare section reference in it means 21 CFR.
    A passage that means 9 CFR writes the title, and `extract_citations` already
    catches that form.

    Why this matters: q14 asks which section a 'healthy' claim must also
    satisfy. The retrieved page says "§ 101.13" and "§ 101.65" — bare — so the
    title-requiring regex found no CFR citation at all on a page that names two.
    """
    titled = extract_citations(text)
    bare = [f"{default_title} CFR {s}" for s in BARE_SECTION_RE.findall(text)]
    return list(dict.fromkeys(titled + bare))


def section_of(cite: str) -> tuple[str, str] | None:
    """('21', '101.65') from any citation naming a 21 CFR section, else None.

    Paragraph suffixes are dropped: the caller wants the SECTION, because the
    registry partitions eCFR text by section and a cross-reference to
    § 101.65(a) is a cross-reference to § 101.65.
    """
    m = CFR_RE.search(cite)
    if not m:
        return None
    return m.group(1), m.group(2).split("(")[0]


def looks_like_citation_query(query: str) -> bool:
    """Used by the S3 Vectors tier to trigger the exact-match assist."""
    return bool(CFR_RE.search(query) or FR_RE.search(query)
                or "red no. 3" in query.lower())
