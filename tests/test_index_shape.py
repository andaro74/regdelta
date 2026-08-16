"""One definition of what an indexed chunk carries.

Three writers store it (processor._put_vectors, retrieval.reindex,
retrieval.rebuild_s3v) and one reader reconstructs it (Chunk.from_metadata).
Every one of them used to hand-maintain its own key list, and all three
dropped `kind` — the field naming a chunk as the DATES or amendatory-
instructions paragraph. Retrieval then rebuilt that fact out of a DynamoDB
citations GSI, because the field it needed existed in the corpus and was
discarded at index time.

A key one writer emits and another drops has no failure mode of its own: the
filter that should match returns nothing, and it reads as a retrieval miss.
"""

import pytest

from shared import models
from shared.models import Chunk, Filters
from shared.validate import ValidationError

RECORD = {
    "chunk_id": "2025-00830#0000",
    "text": "DATES: This order is effective January 15, 2027, except…",
    "citation_path": "90 FR 4628",
    "kind": "dates",
    "doc_type": "order",
    "cfr_title": "21",
    "cfr_part": "74",
    "fr_doc_number": "2025-00830",
    "pub_date": "2025-01-16",
    "effective_date": "2027-01-15",
    "compliance_date": None,
    "embedding": [0.1] * 4,
}


def test_the_jsonl_text_field_is_renamed_once():
    md = models.to_index_metadata(RECORD)
    assert md["chunk_text"] == RECORD["text"]
    assert "text" not in md


def test_kind_is_carried_into_the_index():
    """The whole point. It was in the corpus JSONL from M01 and no index had
    it, so 'which paragraph states what this document does' had to be
    reconstructed through a citations GSI."""
    assert models.to_index_metadata(RECORD)["kind"] == "dates"


def test_empty_values_are_omitted_not_stored_as_null():
    """ADR-0006 falling out of the mapping rather than being re-implemented on
    top of it: AOSS types the date fields as `date`, and a range query
    excludes documents that LACK the field. An explicit null would be accepted
    and would not obviously break anything."""
    md = models.to_index_metadata(RECORD)
    assert "compliance_date" not in md
    assert md["effective_date"] == "2027-01-15"


def test_the_reader_round_trips_every_key_the_writer_stores():
    """from_metadata is the only reader. A key it forgets is a Chunk field
    that silently arrives as None — and router._finish then drops the chunk
    for 'not matching' a filter value that was never fetched."""
    chunk = Chunk.from_metadata(RECORD["chunk_id"],
                                models.to_index_metadata(RECORD))
    assert chunk.kind == "dates"
    assert chunk.text.startswith("DATES:")
    assert chunk.citation_path == "90 FR 4628"
    assert chunk.doc_type == "order"
    assert chunk.effective_date == "2027-01-15"
    assert chunk.compliance_date is None
    for key in models.INDEX_METADATA_KEYS:
        attr = "text" if key == "chunk_text" else key
        assert hasattr(chunk, attr), f"Chunk cannot hold indexed key {key!r}"


def test_the_aoss_mapping_covers_every_indexed_key():
    """A key stored but unmapped is dynamically typed by OpenSearch — a date
    could land as `text` and its range queries would silently match nothing."""
    from retrieval import aoss_client
    mapped = set(aoss_client.INDEX_MAPPING["mappings"]["properties"])
    assert set(models.INDEX_METADATA_KEYS) <= mapped, \
        set(models.INDEX_METADATA_KEYS) - mapped


def test_the_aoss_source_list_is_derived_from_the_index_shape():
    from retrieval import aoss_tier
    assert set(models.INDEX_METADATA_KEYS) <= set(aoss_tier._SOURCE_FIELDS)
    assert "chunk_id" in aoss_tier._SOURCE_FIELDS


def test_all_three_writers_use_the_shared_definition():
    """The guard against the list being re-forked. Hand-synced copies of the
    same key list is the _EDGE_PREDICATE drift of M01c, and that one was found
    only after the writes had landed."""
    import inspect

    from ingestion import processor
    from retrieval import rebuild_s3v, reindex
    for mod in (processor, reindex, rebuild_s3v):
        assert "to_index_metadata" in inspect.getsource(mod), mod.__name__


def test_the_aoss_document_adds_only_the_id_and_the_vector():
    from retrieval import reindex
    doc = reindex._document(RECORD)
    assert set(doc) - set(models.to_index_metadata(RECORD)) == {
        "chunk_id", "embedding"}


# ------------------------------------------------------------ kind as a filter
def test_kind_is_a_first_class_filter():
    f = Filters.from_dict({"kind": "dates"})
    dates = Chunk.from_metadata("d#0000", models.to_index_metadata(RECORD))
    prose = Chunk.from_metadata(
        "d#0009", models.to_index_metadata({**RECORD, "kind": "preamble"}))
    assert f.matches(dates) is True
    assert f.matches(prose) is False


def test_an_out_of_enum_kind_raises():
    """Same reason doc_type is enum-checked: an out-of-enum keyword filter
    does not error, it matches nothing — so the probe that should have found
    the DATES paragraph comes back empty and reads as a retrieval failure."""
    with pytest.raises(ValidationError, match="kind"):
        Filters.from_dict({"kind": "DATES"})
    with pytest.raises(ValidationError, match="kind"):
        Filters.from_dict({"kind": "dates_paragraph"})


def test_the_kind_vocabulary_matches_what_the_chunker_emits():
    """Read off the chunker, not off a memory of it. If a new kind is added
    there and not here, a filter for it raises as out-of-enum."""
    import inspect
    import re

    from ingestion import chunker
    emitted = set(re.findall(r'emit\([^)]*?,\s*"([a-z]+)"',
                             inspect.getsource(chunker), re.DOTALL))
    assert emitted <= models.CHUNK_KINDS, emitted - models.CHUNK_KINDS


def test_kinds_actually_produced_from_a_real_document_are_all_known():
    """Runs the chunker over a real FR fixture rather than reading its source.

    An earlier version of this test globbed tests/fixtures for *.jsonl, of
    which there are none — so it asserted over an empty set and passed
    vacuously. Checking that a check can fail is the cheapest thing in this
    repo and the easiest to skip.
    """
    from conftest import FIXTURES

    from ingestion.chunker import chunk
    from ingestion.processor import parse_fr_xml

    doc = parse_fr_xml((FIXTURES / "fr_2024-29957_excerpt.xml").read_bytes(),
                       {"document_number": "2024-29957"})
    seen = {c["kind"] for c in chunk(doc)}
    assert seen, "fixture produced no chunks — the test would assert nothing"
    assert seen <= models.CHUNK_KINDS, seen - models.CHUNK_KINDS
    assert "dates" in seen


# --------------------------------------------------------------- rebuild_s3v
@pytest.fixture
def rebuild(monkeypatch):
    """monkeypatch, not bare assignment — these patch module-level names, and
    leaving them patched would make every later test in the session read a
    stubbed corpus depending on collection order."""
    import types

    from retrieval import rebuild_s3v as mod
    monkeypatch.setattr(mod, "_clients",
                        lambda: (types.SimpleNamespace(),
                                 types.SimpleNamespace()))

    def with_records(records):
        monkeypatch.setattr(mod, "iter_chunk_records", lambda *a: iter(records))
        return mod

    return with_records


def test_the_rebuild_refuses_a_chunk_with_no_embedding(rebuild):
    """Skipping it would quietly shrink the index while every downstream count
    still agreed with itself — the chunk stays in the corpus and becomes
    unreachable by search."""
    mod = rebuild([{**RECORD, "embedding": None}])
    with pytest.raises(ValueError, match="no embedding"):
        mod.rebuild(dry_run=True)


def test_the_rebuild_refuses_a_wrong_dimension_embedding(rebuild):
    """A 1024-dim index silently accepting a short vector is not a thing worth
    finding out about at query time."""
    mod = rebuild([{**RECORD, "embedding": [0.1] * 7}])
    with pytest.raises(ValueError, match="7-dim"):
        mod.rebuild(dry_run=True)


def test_an_empty_corpus_is_a_failure_not_a_healthy_rebuild(rebuild):
    mod = rebuild([])
    with pytest.raises(RuntimeError, match="no chunk records"):
        mod.rebuild(dry_run=True)


def test_the_rebuild_never_embeds(rebuild):
    """The architecture rule. Embeddings are computed once at ingest and
    persisted with the chunks; a rebuild that re-embedded would cost a Bedrock
    call per chunk and could produce different vectors than the corpus holds.
    """
    import inspect

    from retrieval import rebuild_s3v
    src = inspect.getsource(rebuild_s3v)
    assert "bedrock" not in src.lower()
    assert "invoke_model" not in src
