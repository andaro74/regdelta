"""Validators for every id, date and enum that crosses a trust boundary.

Deferred at M01 close and closed here (security review MEDIUM-1/MEDIUM-2).
Two distinct harms, which is why this is not one loose "sanitize" helper:

1. **Ids become storage keys.** `document_number` and the CFR title/section
   land in S3 object keys (`raw/{id}.xml`, `chunks/{part}/{id}.jsonl`) and in
   DynamoDB partition/sort keys (`DOC#{id}`, `CFR#{t}#{s}`, `VERSION#{date}`).
   S3 keys are not paths but `..` and `/` are legal characters in them, so an
   unvalidated id writes to a *different* key than intended — including over
   another document's chunks. In DynamoDB a `#` inside an id forges the
   composite-key structure the registry's whole layout depends on.

2. **Dates and doc_type become retrieval filters.** SPEC/02's contract filters
   on doc_type and on pub/effective/compliance date ranges. A malformed date
   breaks range comparison; an out-of-enum doc_type silently matches nothing,
   so the document disappears from exactly the queries meant to find it. That
   failure is invisible — no error, just an empty result — which is why it is
   validated at ingest rather than tolerated at query time.

Reject, never coerce. A repaired id would write to a key nobody asked for,
and a repaired date would be an invented regulatory deadline. Raising fails
the SQS message, which retries and then lands in the DLQ where it is visible.
"""
import datetime as dt
import re

from shared import config


class ValidationError(ValueError):
    """Untrusted input failed a boundary check. Fails the message on purpose."""


# EVERY pattern here is re.ASCII and anchored \A...\Z.
#
# re.ASCII is load-bearing, not tidiness. In a str pattern `\d` means Unicode
# category Nd, so `\d{4}-\d{5}` accepted document numbers written in
# Arabic-Indic, Devanagari or fullwidth digits — all of which reached vector
# keys and CHUNK# sort keys through parse_fr_xml's doc_id. They carry no `/`,
# `..` or `#`, so nothing was overwritten, but the module header claimed no
# separators survive and that was false for these. Found by security review of
# this branch; the literal payloads are in tests/test_input_validation.py
# (UNICODE_DIGIT_IDS).
#
# \Z is Python's absolute end-of-string. `$` would be the bug — it matches
# before a trailing newline, so "2024-29957\n" would pass.
_ASCII = re.ASCII

# FR document numbers. Modern ones are "2024-29957"; the FR API also returns
# "05-1234", "94-30245", and letter-prefixed numbers for roughly 1994-2011
# ("E9-12345", "X05-1234", "C1-2011-1234"). The demo corpus is 2024-2025, but
# a supersedes target naming an older rule is exactly the case that must
# resolve rather than DLQ, so the prefixed forms are accepted.
_DOC_NUMBER_RE = re.compile(r"\A[A-Z]{0,2}[0-9]{1,4}(?:-[0-9]{4})?-[0-9]{3,6}\Z",
                            _ASCII)

# CFR title is a small integer ("21"). Part/section is "101.65" or "74.303";
# a bare part ("101") is also valid input to the versioner.
_CFR_TITLE_RE = re.compile(r"\A[0-9]{1,2}\Z", _ASCII)
_CFR_SECTION_RE = re.compile(r"\A[0-9]{1,4}(?:\.[0-9]{1,4}[a-z]?)?\Z", _ASCII)

# Part alone — the S3 key segment in chunks/<part>/<doc_id>.jsonl.
_CFR_PART_RE = re.compile(r"\A[0-9]{1,4}\Z", _ASCII)

_ISO_DATE_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", _ASCII)


def is_doc_number(value: object) -> bool:
    """Shape test only. Callers that need to branch on "does this look like a
    document number vs an FR citation" use this; it says nothing about whether
    the document exists (see processor._resolve_fr_citation, which is the
    whole point of that distinction)."""
    return isinstance(value, str) and bool(_DOC_NUMBER_RE.match(value))


def doc_number(value: object, *, field: str = "document_number") -> str:
    """FR document number safe for an S3 key and a DynamoDB partition key."""
    if not is_doc_number(value):
        raise ValidationError(f"{field} is not an FR document number: {value!r}")
    return value


def cfr_title(value: object, *, field: str = "title") -> str:
    if not isinstance(value, str) or not _CFR_TITLE_RE.match(value):
        raise ValidationError(f"{field} is not a CFR title: {value!r}")
    return value


def cfr_section(value: object, *, field: str = "section") -> str:
    if not isinstance(value, str) or not _CFR_SECTION_RE.match(value):
        raise ValidationError(f"{field} is not a CFR section: {value!r}")
    return value


def cfr_part(value: object, *, field: str = "cfr_part") -> str:
    """Part number used as the `chunks/<part>/` S3 key segment.

    On the FR path this comes from a parsing regex in processor.parse_fr_xml
    rather than from any validator — so it was constrained to digits only
    incidentally, with the same Unicode-\\d gap and no length bound. It is the
    one key component the first pass of this branch missed.
    """
    if not isinstance(value, str) or not _CFR_PART_RE.match(value):
        raise ValidationError(f"{field} is not a CFR part: {value!r}")
    return value


def iso_date(value: object, *, field: str = "date") -> str:
    """A real calendar date in ISO form, inside the plausibility window.

    The regex alone would accept 2024-13-45; `fromisoformat` is what makes
    this a date rather than a shape. The year window catches the parse and
    hallucination artifacts (0001-01-01, 9999-12-31) that would otherwise sit
    in a range filter looking like data.
    """
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise ValidationError(f"{field} is not an ISO date (YYYY-MM-DD): {value!r}")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as e:
        raise ValidationError(f"{field} is not a real calendar date: {value!r}") from e
    if not config.MIN_DOC_YEAR <= parsed.year <= config.MAX_DOC_YEAR:
        raise ValidationError(
            f"{field} year {parsed.year} is outside "
            f"{config.MIN_DOC_YEAR}..{config.MAX_DOC_YEAR}: {value!r}")
    return value


def version_date(value: object, *, field: str = "date") -> str:
    """An eCFR version date, or the literal "current".

    "current" is the caller's own sentinel (config.TRACKED_CFR_SECTIONS uses
    it) and is resolved against the versioner before it reaches any key, so it
    is allowed through here and nowhere else.
    """
    if value == "current":
        return "current"
    return iso_date(value, field=field)


def optional_iso_date(value: object, *, field: str = "date") -> str | None:
    """`None` passes through; anything else must be a valid date.

    Absent and malformed are different facts. Several dates legitimately do
    not exist (an eCFR snapshot has no compliance date), and collapsing a bad
    value to None would hide a parse failure inside a normal-looking gap.
    """
    if value is None or value == "":
        return None
    return iso_date(value, field=field)


# "89 FR 106064" — volume, "FR", page. Becomes the FRCITE#<citation>
# partition key.
#
# A literal single space, not `\s+`: `\s` matches \n, \r, \t, \x0b, \x0c and
# (without re.ASCII) NBSP, so "89\nFR\n106064" passed while the comment here
# claimed control characters could not survive. That value writes a partition
# key no lookup can ever match, so supersedes resolution would fall through to
# the API path forever without erroring. Found by security review.
_FR_CITATION_RE = re.compile(r"\A[0-9]{1,4} FR [0-9]{1,7}\Z", _ASCII)


def fr_citation(value: object, *, field: str = "citation") -> str:
    if not isinstance(value, str) or not _FR_CITATION_RE.match(value):
        raise ValidationError(f"{field} is not an FR citation: {value!r}")
    return value


def doc_type(value: object, *, field: str = "doc_type") -> str:
    """One of config.DOC_TYPES — the doc_type filter's domain in SPEC/02."""
    if not isinstance(value, str) or value not in config.DOC_TYPES:
        raise ValidationError(
            f"{field} is not one of {sorted(config.DOC_TYPES)}: {value!r}")
    return value
