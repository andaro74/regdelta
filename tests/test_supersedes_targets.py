"""Security review HIGH-1, item 2: a SUPERSEDES target must EXIST.

`_resolve_fr_citation` used to return any target matching the document-number
SHAPE without checking it was real, so a model-emitted (or injected)
"2024-99999" became an edge key in the amendment graph — the store CLAUDE.md
designates as authoritative for timeline answers.

These tests pin the verification and, just as importantly, pin that an
UNRESOLVED target still raises. M01 journal finding 3 depends on that: SQS
does not preserve order, so the delay rule can legitimately arrive before
the rule it supersedes, and raising is what makes the retry correct. A
verification that swallowed failures would silently re-break it.
"""
import json
import urllib.error

import pytest
from conftest import FIXTURES  # noqa: F401  (path setup)

from ingestion import processor


class _FakeTable:
    """Minimal DynamoDB Table stand-in: get_item over a dict of pk/sk."""

    def __init__(self, items=None):
        self.items = items or {}

    def get_item(self, Key):
        hit = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": hit} if hit else {}


@pytest.fixture
def registry(monkeypatch):
    table = _FakeTable()
    monkeypatch.setattr(processor, "_client",
                        lambda name: table if name == "registry" else None)
    return table


def _no_network(monkeypatch):
    def boom(url):
        raise AssertionError(f"unexpected fetch: {url}")
    monkeypatch.setattr(processor, "_get", boom)


def test_doc_number_already_in_registry_resolves_without_a_fetch(registry, monkeypatch):
    registry.items[("DOC#2024-29957", "META")] = {"pk": "DOC#2024-29957"}
    _no_network(monkeypatch)
    assert processor._resolve_fr_citation("2024-29957") == "2024-29957"


def test_unknown_doc_number_is_confirmed_against_the_fr_api(registry, monkeypatch):
    seen = []

    def fake_get(url):
        seen.append(url)
        return json.dumps({"document_number": "2024-29957"}).encode()

    monkeypatch.setattr(processor, "_get", fake_get)
    assert processor._resolve_fr_citation("2024-29957") == "2024-29957"
    assert "2024-29957.json" in seen[0]


def test_shape_valid_but_nonexistent_doc_number_is_rejected(registry, monkeypatch):
    """The injection payload's target. Shape alone must not make an edge."""
    def fake_get(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(processor, "_get", fake_get)
    with pytest.raises(ValueError, match="not a real FR document"):
        processor._resolve_fr_citation("2024-99999")


def test_fr_api_returning_a_different_document_is_rejected(registry, monkeypatch):
    monkeypatch.setattr(processor, "_get",
                        lambda url: json.dumps({"document_number": "2024-11111"}).encode())
    with pytest.raises(ValueError, match="did not confirm"):
        processor._resolve_fr_citation("2024-99999")


def test_transient_fr_api_error_propagates_for_sqs_retry(registry, monkeypatch):
    """A 503 must NOT be turned into 'target is fake' — that would DLQ a
    real document on a blip. Only 404 is a rejection."""
    def fake_get(url):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(processor, "_get", fake_get)
    with pytest.raises(urllib.error.HTTPError):
        processor._resolve_fr_citation("2024-99999")


def test_unresolvable_citation_still_raises(registry, monkeypatch):
    """M01 finding 3: the ordering race relies on this raising so SQS retries."""
    monkeypatch.setattr(processor, "_get",
                        lambda url: json.dumps({"results": []}).encode())
    with pytest.raises(ValueError, match="cannot resolve supersedes target"):
        processor._resolve_fr_citation("89 FR 106064")


def test_citation_resolves_via_registry_on_retry(registry, monkeypatch):
    """The observed production path: first attempt raised, the healthy rule
    landed, the retry resolved from the registry."""
    registry.items[("FRCITE#89 FR 106064", "DOC")] = {"doc_number": "2024-29957"}
    _no_network(monkeypatch)
    assert processor._resolve_fr_citation("89 FR 106064") == "2024-29957"


def test_doc_number_is_url_quoted_before_the_fetch(registry, monkeypatch):
    """A target is model-controlled text; it must not shape the request path.
    (_DOC_NUMBER_RE gates this branch, so this pins the defense in depth.)"""
    seen = []
    monkeypatch.setattr(processor, "_get",
                        lambda url: (seen.append(url),
                                     json.dumps({"document_number": "2024-1234"}).encode())[1])
    processor._resolve_fr_citation("2024-1234")
    assert seen[0].endswith("/documents/2024-1234.json")
