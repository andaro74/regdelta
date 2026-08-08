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


# FR document numbers: "2024-29957", also older "05-1234". Anchored, so no
# separators, whitespace, or path characters survive.
_DOC_NUMBER_RE = re.compile(r"\A\d{2,4}-\d{3,6}\Z")

# CFR title is a small integer ("21"). Part/section is "101.65" or "74.303";
# a bare part ("101") is also valid input to the versioner.
_CFR_TITLE_RE = re.compile(r"\A\d{1,2}\Z")
_CFR_SECTION_RE = re.compile(r"\A\d{1,4}(?:\.\d{1,4}[a-z]?)?\Z")

_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


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
# partition key, so `#` and control characters must not survive.
_FR_CITATION_RE = re.compile(r"\A\d{1,4}\s+FR\s+\d{1,7}\Z")


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
