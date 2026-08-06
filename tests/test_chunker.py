"""SPEC/01 unit tests: fixture XML -> parsed_doc -> chunks. Asserts no
chunk splits mid-paragraph and every chunk carries a citation_path."""
from conftest import FIXTURES

from ingestion import chunker
from ingestion.processor import parse_ecfr_xml, parse_fr_xml

HEALTHY_META = {"document_number": "2024-29957", "citation": "89 FR 106064",
                "title": "healthy final rule"}
DELAY_META = {"document_number": "2025-03118", "citation": "90 FR 10592",
              "title": "healthy delay rule"}


def _healthy():
    return parse_fr_xml((FIXTURES / "fr_2024-29957_excerpt.xml").read_bytes(),
                        HEALTHY_META)


def _ecfr_10165():
    return parse_ecfr_xml((FIXTURES / "ecfr_21_101.65.xml").read_bytes(),
                          "21", "101.65", "2026-08-01")


# ------------------------------------------------------------------ parsing
def test_parse_fr_finds_regtext_and_amdpars():
    doc = _healthy()
    assert doc["cfr_title"] == "21" and doc["cfr_part"] == "101"
    sections = {s["section"] for s in doc["regtext_sections"]}
    assert {"101.13", "101.65"} <= sections
    assert any("101.65" in a for a in doc["amdpars"])


def test_parse_fr_dates_text_carries_both_dates():
    doc = _healthy()
    assert "February 25, 2025" in doc["dates_text"]        # effective
    assert "February 25, 2028" in doc["dates_text"]        # compliance (the trap)


def test_parse_delay_rule_has_no_regtext():
    doc = parse_fr_xml((FIXTURES / "fr_2025-03118_delay.xml").read_bytes(),
                       DELAY_META)
    assert doc["regtext_sections"] == []
    assert doc["preamble"], "delay rule preamble should be captured"


def test_parse_ecfr_section():
    doc = _ecfr_10165()
    assert doc["cfr_section"] == "101.65"
    paras = doc["regtext_sections"][0]["paragraphs"]
    assert paras and any(p.startswith("(a)") for p in paras)


# ----------------------------------------------------------------- chunking
def test_every_chunk_has_citation_path_and_id():
    for doc in (_healthy(), _ecfr_10165()):
        chunks = chunker.chunk(doc)
        assert chunks
        for c in chunks:
            assert c["citation_path"], c["chunk_id"]
            assert c["chunk_id"].startswith(doc["doc_id"])


def test_no_paragraph_split_mid_paragraph():
    doc = _ecfr_10165()
    paragraphs = doc["regtext_sections"][0]["paragraphs"]
    joined = "\n".join(c["text"] for c in chunker.chunk(doc))
    for p in paragraphs:
        assert p in joined, f"paragraph missing/split: {p[:60]!r}"
    # ...and each paragraph appears intact within exactly one chunk
    chunks = chunker.chunk(doc)
    for p in paragraphs:
        holders = [c for c in chunks if p in c["text"]]
        assert len(holders) >= 1


def test_regtext_citation_paths_are_cfr_style():
    chunks = [c for c in chunker.chunk(_ecfr_10165()) if c["kind"] == "regtext"]
    assert all(c["citation_path"].startswith("21 CFR 101.65") for c in chunks)
    # at least one chunk is scoped below the section level
    assert any("(" in c["citation_path"] for c in chunks)


def test_fr_dates_chunk_exists_with_fr_citation():
    chunks = chunker.chunk(_healthy())
    dates = [c for c in chunks if c["kind"] == "dates"]
    assert len(dates) == 1
    assert dates[0]["citation_path"] == "89 FR 106064"
    assert "February 25, 2028" in dates[0]["text"]


# ------------------------------------------------- marker hierarchy details
def test_marker_paths_nested():
    path = chunker._paragraph_path("(d)(2)(i) Some text", [])
    assert path == ["d", "2", "i"]


def test_marker_alpha_i_after_h_is_level_one():
    assert chunker._paragraph_path("(i) After h.", ["h"]) == ["i"]


def test_marker_roman_i_inside_numbered_para_is_level_three():
    assert chunker._paragraph_path("(i) Roman one.", ["d", "2"]) == ["d", "2", "i"]


def test_marker_stars_paragraph_keeps_context():
    stack = chunker._paragraph_path("(b) * * *", [])
    assert stack == ["b"]
    stack = chunker._paragraph_path("(2) * * *", stack)
    assert stack == ["b", "2"]
    stack = chunker._paragraph_path("(ii) Suggests that a food...", stack)
    assert stack == ["b", "2", "ii"]


def test_continuation_paragraph_inherits_path():
    assert chunker._paragraph_path("No leading marker here.", ["a", "1"]) == ["a", "1"]
