"""The four M01 security deferrals, closed at M02 pre-work.

One test class per deferral, named for the harm rather than the function, so a
failure says what became reachable again:

  1. ids reaching S3 object keys and DynamoDB partition/sort keys
  2. fetch URLs with no scheme/host allowlist (SSRF)
  3. unbounded response and chunk counts
  4. unvalidated dates and doc_type reaching SPEC/02 retrieval filters

The negative cases are the point. A validator that accepts the real corpus
proves nothing on its own — M01's finding 2 was exactly a test that passed
while the data it should have covered was silently absent.
"""
import json
import urllib.error
import urllib.request

import pytest
from conftest import FIXTURES

from ingestion import metadata, processor
from shared import config, fetch, validate

# --------------------------------------------------------------------------
# 1. Ids that become storage keys
# --------------------------------------------------------------------------

# `/` and `..` are legal characters in an S3 key, so these do not error at the
# API — they write to a *different* object than intended, including over
# another document's chunks. `#` forges the registry's composite-key layout.
HOSTILE_IDS = [
    "../../etc/passwd",
    "2024-29957/../2025-03118",
    "2024-29957#META",
    "DOC#2024-29957",
    "2024-29957\n2025-03118",
    "2024-29957 ",
    " 2024-29957",
    "2024-29957/",
    "",
    "*",
    "2024-29957%2F..%2F",
]


@pytest.mark.parametrize("value", HOSTILE_IDS)
def test_doc_number_rejects_key_hostile_input(value):
    with pytest.raises(validate.ValidationError):
        validate.doc_number(value)


@pytest.mark.parametrize("value", ["2024-29957", "2025-03118", "05-1234"])
def test_doc_number_accepts_real_fr_numbers(value):
    assert validate.doc_number(value) == value


def test_doc_number_rejects_non_strings():
    for value in (None, 20242995, ["2024-29957"], {"a": 1}):
        with pytest.raises(validate.ValidationError):
            validate.doc_number(value)


@pytest.mark.parametrize("value", ["21/../22", "21#", "abc", "", "210"])
def test_cfr_title_rejects_bad_input(value):
    with pytest.raises(validate.ValidationError):
        validate.cfr_title(value)


@pytest.mark.parametrize("value", ["101.65", "74.303", "101.13", "101"])
def test_cfr_section_accepts_real_sections(value):
    assert validate.cfr_section(value) == value


@pytest.mark.parametrize("value", ["101.65/../74.303", "101.65#", "../101",
                                   "101.65 ", "", "101.65;drop"])
def test_cfr_section_rejects_bad_input(value):
    with pytest.raises(validate.ValidationError):
        validate.cfr_section(value)


@pytest.mark.parametrize("value", ["89 FR 106064", "90 FR 10592", "90 FR 4628"])
def test_fr_citation_accepts_real_citations(value):
    assert validate.fr_citation(value) == value


@pytest.mark.parametrize("value", ["89 FR 106064#DOC", "89 FR", "FR 106064",
                                   "89 fr 106064", "", "89 FR 106064 extra"])
def test_fr_citation_rejects_key_hostile_input(value):
    with pytest.raises(validate.ValidationError):
        validate.fr_citation(value)


def test_ingest_fr_doc_rejects_hostile_id_before_touching_aws():
    """Validation must precede the first client call.

    If the id were validated after `_client("registry")`, a malformed message
    would still open a connection and — worse — the traversal would already be
    embedded in the GetItem key used for the idempotency check.
    """
    def explode(_name):
        raise AssertionError("validation must run before any AWS client is built")

    original, processor._client = processor._client, explode
    try:
        with pytest.raises(validate.ValidationError):
            processor.ingest_fr_doc({"document_number": "../../etc/passwd"})
    finally:
        processor._client = original


def test_ingest_cfr_section_rejects_hostile_title_section_date():
    def explode(_name):
        raise AssertionError("validation must run before any AWS client is built")

    original, processor._client = processor._client, explode
    try:
        for msg in (
            {"title": "21/..", "section": "101.65", "date": "2024-12-01"},
            {"title": "21", "section": "../101.65", "date": "2024-12-01"},
            {"title": "21", "section": "101.65", "date": "2024-12-01/../"},
            {"title": "21", "section": "101.65", "date": "not-a-date"},
        ):
            with pytest.raises(validate.ValidationError):
                processor.ingest_cfr_section(msg)
    finally:
        processor._client = original


def test_parse_fr_xml_validates_the_response_document_number():
    """The id the response returned is not the id the caller requested.

    `doc_id` becomes the chunk_id prefix, so it reaches vector keys and CHUNK#
    sort keys even though the caller already validated its own input.
    """
    raw = (FIXTURES / "fr_2025-03118_delay.xml").read_bytes()
    with pytest.raises(validate.ValidationError):
        processor.parse_fr_xml(raw, {"document_number": "../../evil",
                                     "citation": "90 FR 10592"})


# --------------------------------------------------------------------------
# 2. Fetch allowlist (SSRF)
# --------------------------------------------------------------------------

BLOCKED_URLS = [
    # Scheme
    "http://www.ecfr.gov/api/versioner/v1/full/2024-12-01/title-21.xml",
    "file:///proc/self/environ",
    "ftp://www.ecfr.gov/x",
    "gopher://www.ecfr.gov/x",
    # Cloud metadata — the reason the execution role makes this urgent
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "https://169.254.169.254/latest/meta-data/",
    # Internal
    "https://localhost/x",
    "https://127.0.0.1/x",
    "https://10.0.0.5/x",
    # Suffix lookalike — what a `startswith`/`endswith` check would let through
    "https://www.ecfr.gov.attacker.example/x",
    "https://wwwXecfr.gov/x",
    "https://notwww.ecfr.gov/x",
    # Userinfo — hostname is attacker.example, not www.ecfr.gov
    "https://www.ecfr.gov@attacker.example/x",
    "https://www.federalregister.gov:pass@attacker.example/x",
    # Allowlisted host present only in the query/fragment
    "https://attacker.example/?u=https://www.ecfr.gov/x",
    "https://attacker.example/#www.federalregister.gov",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_check_url_blocks(url):
    with pytest.raises(fetch.FetchNotAllowedError):
        fetch.check_url(url)


@pytest.mark.parametrize("url", [
    "https://www.federalregister.gov/api/v1/documents/2024-29957.json",
    "https://www.ecfr.gov/api/versioner/v1/full/2024-12-01/title-21.xml?part=101",
    "HTTPS://WWW.ECFR.GOV/api/versioner/v1/versions/title-21.json",
])
def test_check_url_allows_the_real_apis(url):
    assert fetch.check_url(url) == url


def test_check_url_rejects_non_urls():
    for value in (None, "", 42, "not a url"):
        with pytest.raises(fetch.FetchNotAllowedError):
            fetch.check_url(value)


def test_config_apis_are_on_their_own_allowlist():
    """Guards against an allowlist that silently excludes the real endpoints —
    which would fail closed, but fail every ingest."""
    assert fetch.check_url(config.FR_API + "/documents.json")
    assert fetch.check_url(config.ECFR_API + "/versions/title-21.json")


def test_redirect_off_allowlist_raises_instead_of_following():
    """A 302 is a second fetch. An allowlisted first hop proves nothing."""
    handler = fetch._AllowlistRedirectHandler()
    with pytest.raises(fetch.FetchNotAllowedError):
        handler.redirect_request(
            None, None, 302, "Found", {},
            "http://169.254.169.254/latest/meta-data/")


def test_opener_carries_no_handler_but_https():
    """Defence in depth behind the scheme check.

    This test found a real bug: `build_opener()` ADDS to the default handler
    set rather than replacing it, so the first version of this module still had
    FileHandler, FTPHandler and plain HTTPHandler installed while its comment
    claimed otherwise. Only `check_url` was standing between `file:///` and a
    live handler.
    """
    names = {type(h).__name__ for h in fetch._opener.handlers}
    assert "FileHandler" not in names
    assert "FTPHandler" not in names
    assert "DataHandler" not in names
    assert "HTTPHandler" not in names      # plain http, not HTTPSHandler
    assert "ProxyHandler" not in names     # https_proxy must not reroute fetches
    assert "HTTPSHandler" in names


def test_non_https_scheme_has_no_handler_even_if_check_url_is_bypassed():
    """Belt and braces: call the opener directly, past `check_url`."""
    with pytest.raises(urllib.error.URLError):
        fetch._opener.open(urllib.request.Request("file:///etc/hosts"))


# --------------------------------------------------------------------------
# 3. Size and chunk caps
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self, n=None):
        return self._body[:n] if n is not None else self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_get_bytes_refuses_an_oversized_body(monkeypatch):
    """Refused, not truncated: a half-read XML document parses into a document
    with paragraphs missing and no error anywhere."""
    monkeypatch.setattr(fetch._opener, "open",
                        lambda req, timeout=None: _FakeResponse(b"x" * 5000))
    with pytest.raises(fetch.ResponseTooLargeError):
        fetch.get_bytes("https://www.ecfr.gov/x", max_bytes=1000)


def test_get_bytes_allows_a_body_at_exactly_the_cap(monkeypatch):
    monkeypatch.setattr(fetch._opener, "open",
                        lambda req, timeout=None: _FakeResponse(b"x" * 1000))
    assert len(fetch.get_bytes("https://www.ecfr.gov/x", max_bytes=1000)) == 1000


def test_get_bytes_checks_the_allowlist_before_opening(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("allowlist must be checked before the connection")

    monkeypatch.setattr(fetch._opener, "open", explode)
    with pytest.raises(fetch.FetchNotAllowedError):
        fetch.get_bytes("http://169.254.169.254/")


def test_capped_refuses_rather_than_truncates():
    """The cap bounds embed() spend, which is one Bedrock call per chunk."""
    chunks = [{"text": "x"} for _ in range(config.MAX_CHUNKS_PER_DOC + 1)]
    with pytest.raises(ValueError, match="MAX_CHUNKS_PER_DOC"):
        processor._capped(chunks, "2024-29957")


def test_capped_passes_a_document_at_the_cap():
    chunks = [{"text": "x"} for _ in range(config.MAX_CHUNKS_PER_DOC)]
    assert processor._capped(chunks, "2024-29957") is chunks


def test_chunk_cap_leaves_headroom_over_the_largest_demo_doc():
    """389 chunks is the healthy final rule at M01 close. If the cap ever
    drops near that, the demo corpus itself starts DLQ-ing."""
    assert config.MAX_CHUNKS_PER_DOC > 389 * 2


# --------------------------------------------------------------------------
# 4. Dates and doc_type reaching SPEC/02 retrieval filters
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "2024-13-01",   # month 13 — shape-valid, not a date
    "2024-02-30",   # day out of range for the month
    "2024-1-1",     # not zero-padded, breaks lexicographic range compare
    "12/19/2024",   # US format
    "2024-12-19T00:00:00Z",
    "December 19, 2024",
    "0001-01-01",   # hallucination artifact inside a range filter
    "9999-12-31",
    "",
    "null",
    "TBD",
])
def test_iso_date_rejects_unfilterable_values(value):
    with pytest.raises(validate.ValidationError):
        validate.iso_date(value)


@pytest.mark.parametrize("value", ["2024-12-27", "2025-04-28", "2028-02-25",
                                   "2027-01-15", "2028-01-18"])
def test_iso_date_accepts_the_demo_ground_truth(value):
    assert validate.iso_date(value) == value


def test_optional_iso_date_distinguishes_absent_from_malformed():
    """Absent and malformed are different facts. Collapsing a bad date to None
    would hide a parse failure inside a legitimately empty field."""
    assert validate.optional_iso_date(None) is None
    assert validate.optional_iso_date("") is None
    with pytest.raises(validate.ValidationError):
        validate.optional_iso_date("not-a-date")


def test_version_date_allows_only_the_current_sentinel():
    assert validate.version_date("current") == "current"
    assert validate.version_date("2024-12-01") == "2024-12-01"
    for value in ("latest", "CURRENT", "current/../", "now"):
        with pytest.raises(validate.ValidationError):
            validate.version_date(value)


@pytest.mark.parametrize("value", sorted(config.DOC_TYPES))
def test_doc_type_accepts_the_enum(value):
    assert validate.doc_type(value) == value


@pytest.mark.parametrize("value", ["final rule", "Final_Rule", "rule",
                                   "final_rule ", "", "unknown", None])
def test_doc_type_rejects_values_that_match_no_filter(value):
    """The dangerous direction: an out-of-enum doc_type does not error at query
    time, it matches nothing — so the document vanishes from exactly the
    queries meant to find it."""
    with pytest.raises(validate.ValidationError):
        validate.doc_type(value)


def _model_output(**overrides):
    base = {
        "doc_type": "delay_notice",
        "publication_date": "2025-02-25",
        "effective_dates": [{"date": "2025-04-28", "applies_to": "healthy rule"}],
        "compliance_dates": [],
        "affected_cfr": ["21 CFR 101.65"],
        "amendatory_instructions": [],
        "supersedes": [],
        "binding": True,
    }
    base.update(overrides)
    return json.dumps(base)


def _delay_doc():
    return processor.parse_fr_xml(
        (FIXTURES / "fr_2025-03118_delay.xml").read_bytes(),
        {"document_number": "2025-03118", "citation": "90 FR 10592"})


def test_normalize_rejects_out_of_enum_doc_type():
    doc = _delay_doc()
    with pytest.raises(validate.ValidationError, match="doc_type"):
        metadata.extract(doc, invoke=lambda p: _model_output(doc_type="delay"))


def test_normalize_rejects_a_malformed_effective_date():
    """Raises rather than dropping. A dropped date ingests as a complete-looking
    document with a missing deadline, and the answer built on it still carries
    citations — the failure this product exists to prevent."""
    doc = _delay_doc()
    with pytest.raises(validate.ValidationError, match="effective_dates"):
        metadata.extract(doc, invoke=lambda p: _model_output(
            effective_dates=[{"date": "April 28, 2025", "applies_to": "x"}]))


def test_normalize_rejects_a_malformed_compliance_date():
    doc = _delay_doc()
    with pytest.raises(validate.ValidationError, match="compliance_dates"):
        metadata.extract(doc, invoke=lambda p: _model_output(
            compliance_dates=[{"date": "2028-02-31", "applies_to": "x"}]))


def test_normalize_rejects_a_malformed_publication_date():
    doc = _delay_doc()
    with pytest.raises(validate.ValidationError, match="publication_date"):
        metadata.extract(doc, invoke=lambda p: _model_output(
            publication_date="2025-02-31"))


def test_normalize_keeps_valid_metadata_intact():
    """The regression guard: hardening must not change what a good document
    extracts to. The effective/compliance distinction is the demo's thesis."""
    doc = _delay_doc()
    meta = metadata.extract(doc, invoke=lambda p: _model_output(
        compliance_dates=[{"date": "2028-02-25", "applies_to": "all parties"}],
        supersedes=[{"target": "89 FR 106064", "scope": "effective_date"}]))
    assert meta["doc_type"] == "delay_notice"
    assert meta["publication_date"] == "2025-02-25"
    assert meta["effective_dates"] == [{"date": "2025-04-28",
                                       "applies_to": "healthy rule"}]
    assert meta["compliance_dates"] == [{"date": "2028-02-25",
                                         "applies_to": "all parties"}]
    assert meta["supersedes"] == [{"target": "89 FR 106064",
                                   "scope": "effective_date"}]


def test_ecfr_extract_doc_type_is_in_the_enum():
    """cfr_section is produced deterministically, with no model call — so it
    would bypass the enum check and only fail later, at filter time."""
    doc = processor.parse_ecfr_xml(
        (FIXTURES / "ecfr_21_101.65.xml").read_bytes(), "21", "101.65",
        "2024-12-01")
    meta = metadata.extract(doc)
    assert meta["doc_type"] in config.DOC_TYPES
    assert validate.doc_type(meta["doc_type"])
