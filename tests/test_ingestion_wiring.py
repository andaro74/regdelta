"""Tests that the hardening is WIRED IN, not merely present.

Engineering review of the first pass made the case bluntly: revert
`processor._get` to `urllib.request.urlopen` and all 160 tests still passed.
Every validator and cap was covered in isolation and none at the seam where it
was actually connected, so the suite proved the helpers worked while saying
nothing about whether the ingestion path used them.

Each test here fails if a specific call site is unwired, and says which.
"""
import json

import pytest
from conftest import FIXTURES

from ingestion import chunker, metadata, poller, processor
from shared import config, fetch, validate


class _FakeTable:
    def __init__(self, items=None):
        self.items = items or {}
        self.written = []

    def get_item(self, Key):
        hit = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": hit} if hit else {}

    def put_item(self, Item):
        self.written.append(Item)

    def batch_writer(self):
        return _FakeBatch(self)


class _FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def put_item(self, Item):
        self.table.written.append(Item)


# --------------------------------------------------------------------------
# The fetch allowlist is actually on the ingestion path
# --------------------------------------------------------------------------

def test_processor_get_enforces_the_allowlist():
    """Fails if `processor._get` is ever reverted to a bare urlopen."""
    with pytest.raises(fetch.FetchNotAllowedError):
        processor._get("http://169.254.169.254/latest/meta-data/")


def test_processor_get_enforces_the_scheme():
    with pytest.raises(fetch.FetchNotAllowedError):
        processor._get("file:///etc/hosts")


def test_poller_uses_the_guarded_fetch(monkeypatch):
    """The poller imports `get_json` from shared.fetch; if that ever becomes a
    local urlopen helper again, this fails."""
    monkeypatch.setattr(config, "FR_API", "https://attacker.example/api/v1")
    with pytest.raises(fetch.FetchNotAllowedError):
        poller._new_fr_docs("2026-01-01")


def test_allowlist_redirect_handler_is_installed_in_the_opener():
    """`redirect_request` being correct is worthless if the opener never
    dispatches to it — which is exactly what `build_opener()` got wrong in the
    first version of this branch."""
    types = {type(h).__name__ for h in fetch._opener.handlers}
    assert "_AllowlistRedirectHandler" in types
    # A second, unguarded HTTPRedirectHandler would win or race.
    plain = [h for h in fetch._opener.handlers
             if type(h).__name__ == "HTTPRedirectHandler"]
    assert plain == []


# --------------------------------------------------------------------------
# The chunk cap runs BEFORE the spend it exists to bound
# --------------------------------------------------------------------------

def test_chunk_cap_runs_before_embed(monkeypatch):
    """The cap's whole purpose is bounding embed(), which is one Bedrock call
    per chunk. Testing `_capped` alone does not show it runs first."""
    table = _FakeTable()
    monkeypatch.setattr(processor, "_client",
                        lambda name: table if name == "registry" else None)
    monkeypatch.setattr(processor, "_get", lambda url: json.dumps({
        "document_number": "2024-29957", "citation": "89 FR 106064",
        "full_text_xml_url": "https://www.federalregister.gov/x.xml",
        "publication_date": "2024-12-27",
    }).encode())
    monkeypatch.setattr(processor, "parse_fr_xml",
                        lambda raw, meta: {"doc_id": "2024-29957",
                                           "cfr_part": "101"})
    monkeypatch.setattr(metadata, "extract", lambda parsed: {
        "doc_type": "final_rule", "effective_dates": [], "compliance_dates": [],
        "affected_cfr": [], "amendatory_instructions": [], "supersedes": [],
        "binding": True, "publication_date": "2024-12-27"})
    monkeypatch.setattr(chunker, "chunk", lambda parsed: [
        {"text": "x"} for _ in range(config.MAX_CHUNKS_PER_DOC + 1)])

    def no_embed(texts):
        raise AssertionError("embed() ran before the chunk cap was checked")

    monkeypatch.setattr(processor, "embed", no_embed)
    with pytest.raises(ValueError, match="MAX_CHUNKS_PER_DOC"):
        processor.ingest_fr_doc({"document_number": "2024-29957"})


# --------------------------------------------------------------------------
# Nothing is written before validation can reject the document
# --------------------------------------------------------------------------

def _stub_ingest(monkeypatch, table, *, doc_meta, chunks=1):
    monkeypatch.setattr(processor, "_client",
                        lambda name: table if name == "registry" else None)
    monkeypatch.setattr(processor, "_get", lambda url: json.dumps(doc_meta).encode()
                        if "documents/" in url else b"<RULE/>")
    monkeypatch.setattr(processor, "parse_fr_xml",
                        lambda raw, meta: {"doc_id": doc_meta["document_number"],
                                           "cfr_part": "101"})
    monkeypatch.setattr(metadata, "extract", lambda parsed: {
        "doc_type": "final_rule", "effective_dates": [], "compliance_dates": [],
        "affected_cfr": [], "amendatory_instructions": [], "supersedes": [],
        "binding": True, "publication_date": "2024-12-27"})
    monkeypatch.setattr(chunker, "chunk",
                        lambda parsed: [{"text": "x"} for _ in range(chunks)])
    monkeypatch.setattr(processor, "embed",
                        lambda texts: [[0.0] * config.EMBED_DIM for _ in texts])


def test_bad_citation_is_rejected_before_the_corpus_and_vector_writes(monkeypatch):
    """A citation validated after `_write_corpus`/`_put_vectors` leaves chunks
    retrievable and citable with no registry record — the "partial document
    answers with citations" state `_capped` refuses. This pins the ordering."""
    table = _FakeTable()
    _stub_ingest(monkeypatch, table, doc_meta={
        "document_number": "2024-29957",
        "citation": "89 FR 106064#DOC",          # forges the composite key
        "full_text_xml_url": "https://www.federalregister.gov/x.xml",
        "publication_date": "2024-12-27",
    })

    def no_write(*a, **k):
        raise AssertionError("corpus write ran before the citation was validated")

    def no_vectors(*a, **k):
        raise AssertionError("vector write ran before the citation was validated")

    monkeypatch.setattr(processor, "_write_corpus", no_write)
    monkeypatch.setattr(processor, "_put_vectors", no_vectors)
    with pytest.raises(validate.ValidationError, match="citation"):
        processor.ingest_fr_doc({"document_number": "2024-29957"})


def test_response_for_a_different_document_is_refused(monkeypatch):
    """Well-formed but not the document we asked for. Without this check the
    chunk_ids, vector keys and fr_doc_number filter attribute one document's
    text to another, producing confidently wrong citations."""
    table = _FakeTable()
    _stub_ingest(monkeypatch, table, doc_meta={
        "document_number": "2025-03118",         # asked for 2024-29957
        "citation": "90 FR 10592",
        "full_text_xml_url": "https://www.federalregister.gov/x.xml",
        "publication_date": "2025-02-25",
    })
    with pytest.raises(ValueError, match="refusing to attribute"):
        processor.ingest_fr_doc({"document_number": "2024-29957"})


# --------------------------------------------------------------------------
# Resolved supersedes targets reach a sort key, so they are validated too
# --------------------------------------------------------------------------

def test_registry_resolved_doc_number_is_validated(monkeypatch):
    """`SUPERSEDES#<doc_number>` is a sort key on the amendment graph."""
    table = _FakeTable({("FRCITE#89 FR 106064", "DOC"):
                        {"doc_number": "2024-1#META#forged"}})
    monkeypatch.setattr(processor, "_client",
                        lambda name: table if name == "registry" else None)
    with pytest.raises(validate.ValidationError, match="registry doc_number"):
        processor._resolve_fr_citation("89 FR 106064")


def test_search_resolved_doc_number_is_validated(monkeypatch):
    table = _FakeTable()
    monkeypatch.setattr(processor, "_client",
                        lambda name: table if name == "registry" else None)
    monkeypatch.setattr(processor, "_get", lambda url: json.dumps({
        "results": [{"citation": "89 FR 106064",
                     "document_number": "2024-1#META#forged"}]}).encode())
    with pytest.raises(validate.ValidationError,
                       match="FR search result document_number"):
        processor._resolve_fr_citation("89 FR 106064")


def test_malformed_supersedes_target_is_rejected_before_any_lookup(monkeypatch):
    def explode(_name):
        raise AssertionError("target must be validated before the registry read")

    monkeypatch.setattr(processor, "_client", explode)
    with pytest.raises(validate.ValidationError, match="supersedes target"):
        processor._resolve_fr_citation("89 FR 106064#DOC")


# --------------------------------------------------------------------------
# Version dates: one policy, no invented value
# --------------------------------------------------------------------------

def test_latest_version_date_never_fabricates_today(monkeypatch):
    """It used to return today's date when eCFR returned nothing usable, and
    that invented value became the URL path, the S3 key, the VERSION# sort key
    and the version_date retrieval filter."""
    monkeypatch.setattr(processor, "_get",
                        lambda url: json.dumps({"content_versions": []}).encode())
    with pytest.raises(ValueError, match="no usable content_versions"):
        processor.latest_version_date("21", "101.65")


def test_latest_version_date_skips_bad_entries_but_keeps_good_ones(monkeypatch):
    monkeypatch.setattr(processor, "_get", lambda url: json.dumps({
        "content_versions": [{"date": "2024-12-01"},
                             {"date": "not-a-date"},
                             {"date": "2025-01-01"}]}).encode())
    assert processor.latest_version_date("21", "101.65") == "2025-01-01"


def test_poller_and_processor_share_one_version_date_policy():
    """They disagreed: the poller skipped bad entries, the processor raised on
    the first. One malformed entry therefore let the poller enqueue a message
    the processor could never complete — a silent daily DLQ off identical
    data."""
    versions = [{"date": "2024-12-01"}, {"date": "nope"}, {"date": "2025-01-01"}]
    dates, rejected = processor.valid_version_dates(versions)
    assert dates == ["2024-12-01", "2025-01-01"]
    assert len(rejected) == 1
    # The poller must call this exact helper, not its own copy.
    assert poller.processor.valid_version_dates is processor.valid_version_dates


# --------------------------------------------------------------------------
# Poller: reject-and-continue, and the rejections actually surface
# --------------------------------------------------------------------------

def _poller_stub(monkeypatch, results, sent):
    monkeypatch.setattr(poller, "get_json", lambda url: {"results": results})
    monkeypatch.setattr(poller, "_registry_has", lambda pk, sk: False)
    monkeypatch.setattr(poller, "_new_cfr_versions", lambda: [])

    class _Sqs:
        def send_message(self, QueueUrl, MessageBody):
            sent.append(json.loads(MessageBody))

    monkeypatch.setattr(poller, "_client",
                        lambda name: _Sqs() if name == "sqs" else None)


def test_poller_skips_a_malformed_id_and_reports_it(monkeypatch):
    sent = []
    _poller_stub(monkeypatch, [{"document_number": "2024-29957"},
                               {"document_number": "../../etc/passwd"}], sent)
    result = poller.handler({"mode": "daily"}, None)
    assert [m["document_number"] for m in sent] == ["2024-29957"]
    assert result["rejected_count"] == 1
    assert "etc/passwd" in result["rejected"][0]


def test_poller_rejections_do_not_leak_across_invocations(monkeypatch):
    """`_rejected` is module state and Lambda reuses warm containers, so a
    stale list would inflate the next invocation's report."""
    sent = []
    _poller_stub(monkeypatch, [{"document_number": "bad id"}], sent)
    first = poller.handler({"mode": "daily"}, None)
    assert first["rejected_count"] == 1

    _poller_stub(monkeypatch, [{"document_number": "2024-29957"}], sent)
    second = poller.handler({"mode": "daily"}, None)
    assert "rejected" not in second


def test_poller_caps_pagination_on_a_self_referencing_next_page(monkeypatch):
    """`next_page_url` is response-controlled; the host allowlist bounds where,
    not how many times."""
    monkeypatch.setattr(poller, "get_json", lambda url: {
        "results": [], "next_page_url": "https://www.federalregister.gov/loop"})
    monkeypatch.setattr(poller, "_registry_has", lambda pk, sk: False)
    with pytest.raises(ValueError, match="MAX_POLL_PAGES"):
        poller._new_fr_docs("2026-01-01")


def test_backfill_still_enqueues_the_whole_demo_corpus(monkeypatch):
    """The regression guard on the validators: every value in config must pass
    its own validation, or backfill DLQs the demo."""
    sent = []
    _poller_stub(monkeypatch, [], sent)
    result = poller.handler({"mode": "backfill"}, None)
    fr = [m for m in result["messages"] if m["kind"] == "fr_doc"]
    cfr = [m for m in result["messages"] if m["kind"] == "cfr_section"]
    assert sorted(m["document_number"] for m in fr) == sorted(
        config.BACKFILL_FR_DOCS)
    assert len(cfr) == sum(len(d) for _, _, d in config.TRACKED_CFR_SECTIONS)
    assert "rejected" not in result


# --------------------------------------------------------------------------
# The real corpus still passes every validator
# --------------------------------------------------------------------------

def test_every_configured_id_passes_its_validator():
    for d in config.BACKFILL_FR_DOCS:
        assert validate.doc_number(d) == d
    for title, section, dates in config.TRACKED_CFR_SECTIONS:
        assert validate.cfr_title(title) == title
        assert validate.cfr_section(section) == section
        assert validate.cfr_part(section.split(".")[0])
        for d in dates:
            assert validate.version_date(d) == d


def test_real_fr_documents_still_parse_and_extract():
    """End to end on the fixtures, so the hardening cannot quietly break the
    demo corpus it was added to protect."""
    raw = (FIXTURES / "fr_2025-03118_delay.xml").read_bytes()
    parsed = processor.parse_fr_xml(raw, {"document_number": "2025-03118",
                                          "citation": "90 FR 10592"})
    assert parsed["doc_id"] == "2025-03118"
    assert chunker.chunk(parsed)
