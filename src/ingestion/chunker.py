"""CFR-structure-aware chunker (SPEC/01). TODO: split on §/(a)/(1)/(i)
boundaries, never mid-paragraph; every chunk carries full citation_path.
Unit tests: tests/test_chunker.py against tests/fixtures/*.xml."""


def chunk(parsed_doc: dict) -> list[dict]:
    raise NotImplementedError("SPEC/01")
