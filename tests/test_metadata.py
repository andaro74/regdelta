"""SPEC/01 metadata-extraction tests. The Bedrock call is injected, so
these exercise prompt construction, JSON parsing, and normalization —
including the supersession-scope semantics the demo hinges on."""
import json

from conftest import FIXTURES

from ingestion import metadata
from ingestion.processor import parse_ecfr_xml, parse_fr_xml

DELAY_META = {"document_number": "2025-03118", "citation": "90 FR 10592"}

DELAY_MODEL_OUTPUT = json.dumps({
    "doc_type": "delay_notice",
    "publication_date": "2025-02-25",
    "effective_dates": [{"date": "2025-04-28", "applies_to": "the healthy final rule"}],
    "compliance_dates": [],
    "affected_cfr": ["21 CFR 101.65"],
    "amendatory_instructions": [],
    "supersedes": [{"target": "89 FR 106064", "scope": "effective_date"}],
    "binding": True,
})


def _delay_doc():
    return parse_fr_xml((FIXTURES / "fr_2025-03118_delay.xml").read_bytes(),
                        DELAY_META)


def test_prompt_carries_dates_and_identity():
    prompts = []
    metadata.extract(_delay_doc(), invoke=lambda p: (prompts.append(p), DELAY_MODEL_OUTPUT)[1])
    prompt = prompts[0]
    assert "2025-03118" in prompt
    assert "90 FR 10592" in prompt
    assert "compliance date" in prompt  # domain rule stated to the model


def test_supersedes_scope_preserved():
    meta = metadata.extract(_delay_doc(), invoke=lambda p: DELAY_MODEL_OUTPUT)
    assert meta["doc_type"] == "delay_notice"
    assert meta["supersedes"] == [{"target": "89 FR 106064",
                                  "scope": "effective_date"}]
    assert meta["effective_dates"][0]["date"] == "2025-04-28"
    assert meta["compliance_dates"] == []


def test_parses_json_wrapped_in_fences_and_prose():
    wrapped = "Here is the metadata:\n```json\n" + DELAY_MODEL_OUTPUT + "\n```\nDone."
    meta = metadata.extract(_delay_doc(), invoke=lambda p: wrapped)
    assert meta["supersedes"][0]["scope"] == "effective_date"


def test_normalization_drops_bad_entries():
    sloppy = json.dumps({
        "doc_type": "final_rule",
        "effective_dates": ["2025-02-25"],                    # bare string ok
        "compliance_dates": [{"date": None}],                 # dropped
        "amendatory_instructions": [
            {"action": "REVISE", "target": "21 CFR 101.65(d)"},   # case-fixed
            {"action": "obliterate", "target": "21 CFR 1.1"},     # invalid action
        ],
        "supersedes": [{"target": "89 FR 106064", "scope": "sideways"}],  # -> full
    })
    meta = metadata.extract(_delay_doc(), invoke=lambda p: sloppy)
    assert meta["effective_dates"] == [{"date": "2025-02-25", "applies_to": ""}]
    assert meta["compliance_dates"] == []
    assert meta["amendatory_instructions"] == [
        {"action": "revise", "target": "21 CFR 101.65(d)"}]
    assert meta["supersedes"][0]["scope"] == "full"


def test_ecfr_sections_skip_the_model():
    doc = parse_ecfr_xml((FIXTURES / "ecfr_21_74.303.xml").read_bytes(),
                         "21", "74.303", "2025-01-01")

    def boom(prompt):
        raise AssertionError("eCFR extraction must not call Claude")

    meta = metadata.extract(doc, invoke=boom)
    assert meta["doc_type"] == "cfr_section"
    assert meta["affected_cfr"] == ["21 CFR 74.303"]
