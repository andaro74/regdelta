"""CFR-structure-aware chunker (SPEC/01).

Splits regulatory text on CFR paragraph-marker boundaries — §, (a), (1),
(i), (A) — never mid-paragraph. Every chunk carries a full citation_path
(e.g. "21 CFR 101.65(d)(2)"). Input is the normalized parsed_doc produced
by processor.parse_fr_xml / processor.parse_ecfr_xml.
"""
import re

from shared import config

# Leading paragraph markers: "(d)(2)(i) text..." -> ["d", "2", "i"]
_MARKER_RE = re.compile(r"^\s*\(([a-zA-Z0-9]{1,4})\)")

_ROMAN_CHARS = set("ivxlcdm")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(tok: str) -> int | None:
    tok = tok.lower()
    if not tok or any(ch not in _ROMAN_VALUES for ch in tok):
        return None
    total = 0
    for i, ch in enumerate(tok):
        v = _ROMAN_VALUES[ch]
        nxt = _ROMAN_VALUES[tok[i + 1]] if i + 1 < len(tok) else 0
        total += -v if nxt > v else v
    return total


def _leading_markers(text: str) -> list[str]:
    markers, pos = [], 0
    while True:
        m = _MARKER_RE.match(text[pos:])
        if not m:
            return markers
        markers.append(m.group(1))
        pos += m.end()


def _classify_first(tok: str, stack: list[str]) -> int:
    """Depth (1-based) of the first marker in a leading group, given the
    current paragraph path `stack`. CFR order: (a) → (1) → (i) → (A)."""
    if tok.isdigit():
        return 2
    if tok.islower():
        if set(tok) <= _ROMAN_CHARS:
            # Ambiguous: alpha level 1 ("(i)" after "(h)") vs roman level 3.
            prev1 = stack[0] if stack else None
            alpha_next = (prev1 and len(tok) == 1 and len(prev1) == 1
                          and ord(tok) == ord(prev1) + 1)
            if len(stack) >= 2:
                # Inside (x)(n): roman wins when it starts or continues the
                # roman sequence; only a clean alpha continuation escapes.
                prev3 = stack[2] if len(stack) >= 3 else None
                r_prev = _roman_to_int(prev3) if prev3 else None
                r_tok = _roman_to_int(tok)
                if tok == "i" or (r_prev is not None and r_tok == r_prev + 1):
                    return 3
                return 1 if alpha_next else 3
            return 1
        return 1
    # Uppercase: (A) level 4 (upper-roman deeper levels are out of scope).
    return 4


def _paragraph_path(text: str, stack: list[str]) -> list[str]:
    """Return the new marker path after seeing this paragraph."""
    markers = _leading_markers(text)
    if not markers:
        return stack  # continuation paragraph — inherits current path
    depth = _classify_first(markers[0], stack)
    path = [*stack[: depth - 1], markers[0]]
    for tok in markers[1:]:
        path.append(tok)
    return path


def _citation(section_cite: str, path: list[str]) -> str:
    return section_cite + "".join(f"({p})" for p in path)


def _common_prefix(paths: list[list[str]]) -> list[str]:
    if not paths:
        return []
    prefix = list(paths[0])
    for p in paths[1:]:
        i = 0
        while i < len(prefix) and i < len(p) and prefix[i] == p[i]:
            i += 1
        prefix = prefix[:i]
    return prefix


def chunk(parsed_doc: dict) -> list[dict]:
    """parsed_doc -> list of chunk dicts (no embeddings; processor adds
    those plus doc-level metadata)."""
    out: list[dict] = []
    doc_id = parsed_doc["doc_id"]

    def emit(text: str, citation_path: str, kind: str, cfr_section: str | None = None):
        out.append({
            "chunk_id": f"{doc_id}#{len(out):04d}",
            "doc_id": doc_id,
            "text": text.strip(),
            "citation_path": citation_path,
            "kind": kind,
            "fr_doc_number": parsed_doc.get("fr_doc_number"),
            "cfr_title": parsed_doc.get("cfr_title"),
            "cfr_part": parsed_doc.get("cfr_part"),
            "cfr_section": cfr_section,
        })

    fr_cite = parsed_doc.get("fr_citation") or parsed_doc.get("fr_doc_number") or doc_id

    # DATES paragraph is the single highest-value chunk in an FR doc.
    if parsed_doc.get("dates_text"):
        emit(parsed_doc["dates_text"], fr_cite, "dates")

    if parsed_doc.get("summary"):
        emit(parsed_doc["summary"], fr_cite, "summary")

    # Amendatory instructions, kept together (they are short imperatives).
    if parsed_doc.get("amdpars"):
        emit("Amendatory instructions:\n" + "\n".join(parsed_doc["amdpars"]),
             fr_cite, "amdpar")

    # Preamble prose: pack paragraphs under their heading.
    buf: list[str] = []
    buf_heading: str | None = None

    def flush_preamble():
        nonlocal buf
        if buf:
            cite = f"{fr_cite} ({buf_heading})" if buf_heading else fr_cite
            emit("\n".join(buf), cite, "preamble")
        buf = []

    for block in parsed_doc.get("preamble", []):
        heading, text = block.get("heading"), block["text"]
        if heading != buf_heading or sum(len(t) for t in buf) + len(text) > config.CHUNK_MAX_CHARS:
            flush_preamble()
            buf_heading = heading
            if heading:
                buf.append(heading)
        buf.append(text)
    flush_preamble()

    # Regulatory text: marker-aware packing, never splitting a paragraph.
    for sec in parsed_doc.get("regtext_sections", []):
        sec_cite = f"{sec['cfr_title']} CFR {sec['section']}"
        header = f"§ {sec['section']} {sec.get('subject', '')}".strip()
        stack: list[str] = []
        cur: list[str] = [header]
        cur_paths: list[list[str]] = []
        cur_len = len(header)

        # sec_cite/sec/header bound as defaults, not captured: the closure is
        # defined inside the loop, so a free variable would resolve at CALL
        # time. Every call today happens in the same iteration, making this
        # latent rather than live — but deferring one call (collecting these
        # to flush later, say) would silently attribute every chunk to the
        # LAST section. Binding costs nothing and removes the trap. [B023]
        def flush_sec(sec_cite=sec_cite, sec=sec, header=header):
            nonlocal cur, cur_paths, cur_len
            if cur_paths:
                emit("\n".join(cur), _citation(sec_cite, _common_prefix(cur_paths)),
                     "regtext", sec["section"])
            # every chunk re-carries the section header for retrieval context
            cur, cur_paths, cur_len = [header], [], len(header)

        for para in sec["paragraphs"]:
            new_path = _paragraph_path(para, stack)
            starts_level1 = bool(_leading_markers(para)) and len(new_path) == 1
            over = cur_len + len(para) > config.CHUNK_MAX_CHARS and cur_len > 0 and cur_paths
            at_break = starts_level1 and cur_len >= config.CHUNK_BREAK_CHARS
            if over or at_break:
                flush_sec()
            stack = new_path
            cur.append(para)
            cur_paths.append(list(new_path))
            cur_len += len(para)
        flush_sec()

    return out
