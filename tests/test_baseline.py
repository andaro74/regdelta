"""M00b: the control's contract. These tests pin the baseline's SHAPE, not
its answer quality — it is supposed to answer badly (SPEC/00b, ADR-0002).
If a change here starts failing, the control moved and every delta measured
against it is void."""
import inspect

import pytest

from baseline import naive
from shared import config

HITS = [
    {"key": "2024-29957#0000",
     "metadata": {"citation_path": "89 FR 106064",
                  "chunk_text": "Effective February 25, 2025. Compliance "
                                "February 25, 2028."}},
    {"key": "cfr-21-101.65@2025-04-28#0002",
     "metadata": {"citation_path": "21 CFR 101.65(d)",
                  "chunk_text": "Food group equivalent requirements."}},
]


def _answer(question="Did the compliance deadline change?",
            reply="see 21 CFR 101.65", hits=HITS):
    """Returns (response, captured) where captured counts calls — the
    counters are what catch a future 'improvement'."""
    cap = {"searches": 0, "invokes": 0}

    def search(q, k):
        cap["searches"] += 1
        cap["q"], cap["k"] = q, k
        return hits

    def invoke(prompt):
        cap["invokes"] += 1
        cap["prompt"] = prompt
        return reply, "end_turn"

    return naive.answer_naive(question, search=search, invoke=invoke), cap


def test_uses_top_k_from_config_and_passes_question_through():
    _, cap = _answer()
    assert cap["k"] == config.NAIVE_TOP_K == 8
    assert cap["q"] == "Did the compliance deadline change?"


def test_exactly_one_search_and_one_model_call():
    """SPEC/00b: 'one Claude call'. A query-rewrite or rerank pass would be
    the most likely drift, and would make the control smarter than spec."""
    _, cap = _answer()
    assert cap["searches"] == 1
    assert cap["invokes"] == 1


def test_prompt_carries_passages_with_their_citations():
    _, cap = _answer()
    assert "89 FR 106064" in cap["prompt"]
    assert "Compliance February 25, 2028." in cap["prompt"]
    assert "Did the compliance deadline change?" in cap["prompt"]


def test_citations_are_whatever_the_model_emitted():
    resp, _ = _answer(reply="Per 21 CFR 101.65 and 89 FR 106064, no change.")
    assert "21 CFR 101.65" in resp["citations"]
    assert "89 FR 106064" in resp["citations"]


def test_baseline_never_asks_for_human_input():
    """The control has no HITL path — q10 must fail against it. If this ever
    returns pending_review, the baseline has grown a feature it must not
    have."""
    resp, _ = _answer(question="Are we affected by the healthy-claim changes?")
    assert resp["status"] == "answered"
    assert resp["mode"] == "naive"


def test_empty_retrieval_does_not_reach_the_model():
    """Answering with no passages would score the model's parametric memory
    of these regulations instead of naive RAG — the control would be
    measuring the wrong thing."""
    resp, cap = _answer(hits=[])
    assert resp["status"] == "no_context"
    assert cap["invokes"] == 0
    assert resp["answer"] == ""


def test_hit_without_text_is_not_passed_as_an_empty_passage():
    resp, cap = _answer(hits=[{"key": "x#0001", "metadata": {"citation_path": "21 CFR 1.1"}}])
    assert resp["status"] == "no_context"
    assert cap["invokes"] == 0


def test_truncated_answers_are_flagged():
    def invoke(prompt):
        return "partial...", "max_tokens"
    resp = naive.answer_naive("q", search=lambda q, k: HITS, invoke=invoke)
    assert resp["truncated"] is True


def test_scorecard_provenance_pins_model_and_k():
    """The baseline scorecard is permanent; a run that does not say which
    model produced it cannot be reproduced or fairly compared."""
    resp, _ = _answer()
    assert resp["provenance"] == {"model": config.NAIVE_MODEL,
                                  "top_k": config.NAIVE_TOP_K}
    assert config.NAIVE_MODEL == "us.anthropic.claude-opus-4-6-v1"


def test_query_carries_no_metadata_filter():
    """SPEC/00b explicit non-goal. The realistic regression is someone adding
    filter={...} to query_vectors, so assert on the actual call kwargs — the
    signature alone would not catch it."""
    captured = {}

    class FakeS3Vectors:
        def query_vectors(self, **kw):
            captured.update(kw)
            return {"vectors": []}

    class FakeBedrock:
        def invoke_model(self, **kw):
            class Body:
                @staticmethod
                def read():
                    return b'{"embedding": [0.0]}'
            return {"body": Body()}

    naive._clients.clear()
    naive._clients["s3vectors"] = FakeS3Vectors()
    naive._clients["bedrock-runtime"] = FakeBedrock()
    try:
        naive._search("q", 8)
    finally:
        naive._clients.clear()

    assert "filter" not in captured
    assert captured["topK"] == 8
    assert set(captured) == {"vectorBucketName", "indexName", "queryVector",
                             "topK", "returnMetadata", "returnDistance"}


def test_search_seam_takes_no_filters_argument():
    assert list(inspect.signature(naive._search).parameters) == ["question", "k"]


@pytest.mark.parametrize("text,expected", [
    ("governed by 21 CFR § 101.65", "21 CFR 101.65"),
    ("governed by 21 CFR §§ 101.65", "21 CFR 101.65"),
    ("see 21 cfr 101.65", "21 CFR 101.65"),
    ("21 CFR § 101.65(d)(2) applies", "21 CFR 101.65(d)(2)"),
    ("published at 89 fr 106064", "89 FR 106064"),
])
def test_citations_canonicalize_regardless_of_typography(text, expected):
    """M00b/q06: the model wrote '21 CFR § 101.65' and scored as having cited
    nothing. Comparison must be on regulatory identity, not formatting."""
    from shared.citations import extract_citations
    assert expected in extract_citations(text)


def test_part_level_reference_is_not_canonicalized_to_a_section():
    """'21 CFR part 101' is a broader instrument than a section; emitting
    '21 CFR 101' would let it satisfy a section-level citation requirement."""
    from shared.citations import extract_citations
    assert extract_citations("see 21 CFR part 101") == []
