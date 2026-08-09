"""Shared data models. TODO(all specs): extend as milestones need."""
from dataclasses import dataclass, field

from shared import validate

# Chunk metadata keys a filter may reference. Anything else in a probe's
# `filters` object is a typo or a field that does not exist, and both must
# fail loudly: an unknown key that is silently ignored turns a filtered probe
# into an unfiltered one, which still scores green. Same failure class as the
# out-of-enum `doc_type` that motivated MEDIUM-1 in M01c.
KEYWORD_FIELDS = ("cfr_title", "cfr_part", "doc_type", "fr_doc_number")
DATE_FIELDS = ("pub_date", "effective_date", "compliance_date", "version_date")


@dataclass
class Chunk:
    chunk_id: str
    text: str
    citation_path: str          # e.g. "21 CFR 101.65(d)(2)"
    doc_type: str               # final_rule | delay_notice | cfr_section | ...
    fr_doc_number: str | None
    cfr_title: str | None
    cfr_part: str | None
    pub_date: str | None        # ISO dates
    effective_date: str | None
    compliance_date: str | None
    version_date: str | None = None
    embedding: list[float] | None = None
    score: float = 0.0

    @classmethod
    def from_metadata(cls, chunk_id: str, md: dict, *, score: float = 0.0) -> "Chunk":
        """Rebuild a Chunk from the metadata both tiers persist at ingest.

        S3 Vectors metadata (processor._put_vectors) and the AOSS document
        source (retrieval.reindex) carry identical key names by construction,
        so one reader serves both. If they ever diverge, criterion 3's Jaccard
        gate is measuring the divergence rather than retrieval drift — which
        is why this is one function and not two.
        """
        return cls(
            chunk_id=chunk_id,
            text=md.get("chunk_text") or "",
            citation_path=md.get("citation_path") or "",
            doc_type=md.get("doc_type") or "",
            fr_doc_number=md.get("fr_doc_number"),
            cfr_title=md.get("cfr_title"),
            cfr_part=md.get("cfr_part"),
            pub_date=md.get("pub_date"),
            effective_date=md.get("effective_date"),
            compliance_date=md.get("compliance_date"),
            version_date=md.get("version_date"),
            score=score,
        )


@dataclass(frozen=True)
class DateRange:
    """Inclusive ISO-8601 date bounds. Either end may be open."""
    gte: str | None = None
    lte: str | None = None

    def contains(self, value: str | None) -> bool:
        """A document with no such date is NEVER in range (ADR-0006).

        This is the whole of the date-attribution rule expressed as code: a
        date filter selects documents that *establish* that date. The delay
        notice sets no compliance date, so `compliance_date` is None on its
        chunks and a 2028 range must exclude them. Returning True for None —
        the ordinary "no value, no constraint" reflex — would make the filter
        assert that the delay is what makes 2028 operative, which is the
        conflation q01 exists to trap.

        ISO-8601 dates compare correctly as strings (fixed-width, big-endian),
        which is why no parsing happens here.
        """
        if value is None:
            return False
        if self.gte is not None and value < self.gte:
            return False
        return not (self.lte is not None and value > self.lte)


@dataclass
class Filters:
    cfr_title: str | None = None
    cfr_part: str | None = None
    doc_type: str | None = None
    fr_doc_number: str | None = None
    pub_date: DateRange | None = None
    effective_date: DateRange | None = None
    compliance_date: DateRange | None = None
    version_date: DateRange | None = None

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Filters":
        """Build from a probe's `filters` object (SPEC/02 probe schema).

        Strict by construction: unknown keys, non-ISO dates and out-of-enum
        doc_types raise rather than being dropped. The harness passes probe
        filters here unmodified, so this is the only place that decides what a
        probe's filter means — both tiers then consume the same object.
        """
        if not raw:
            return cls()
        kwargs: dict = {}
        for key, value in raw.items():
            if key in KEYWORD_FIELDS:
                kwargs[key] = _keyword(key, value)
            elif key in DATE_FIELDS:
                kwargs[key] = _date_range(key, value)
            else:
                raise validate.ValidationError(
                    f"unknown filter field {key!r}; expected one of "
                    f"{sorted(KEYWORD_FIELDS + DATE_FIELDS)}")
        return cls(**kwargs)

    def matches(self, chunk: Chunk) -> bool:
        """Client-side authority for what a filter means.

        Both tiers push filters down into their engine AND re-check here, so
        the two engines cannot disagree about filter semantics — only about
        ranking. Without this, an S3 Vectors metadata filter and an
        OpenSearch bool/filter clause would each define the contract in their
        own dialect, and criterion 3's Jaccard gate would be measuring dialect
        drift rather than retrieval drift.
        """
        for key in KEYWORD_FIELDS:
            want = getattr(self, key)
            if want is not None and getattr(chunk, key, None) != want:
                return False
        for key in DATE_FIELDS:
            rng = getattr(self, key)
            if rng is not None and not rng.contains(getattr(chunk, key, None)):
                return False
        return True

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None
                   for f in KEYWORD_FIELDS + DATE_FIELDS)


def _keyword(key: str, value) -> str:
    if not isinstance(value, str) or not value:
        raise validate.ValidationError(f"filter {key!r} must be a non-empty string")
    if key == "cfr_title":
        return validate.cfr_title(value, field=f"filter {key}")
    if key == "cfr_part":
        return validate.cfr_part(value, field=f"filter {key}")
    if key == "doc_type":
        return validate.doc_type(value, field=f"filter {key}")
    return value


def _date_range(key: str, value) -> DateRange:
    if not isinstance(value, dict):
        raise validate.ValidationError(
            f"filter {key!r} must be an object with 'gte' and/or 'lte'")
    extra = set(value) - {"gte", "lte"}
    if extra:
        raise validate.ValidationError(
            f"filter {key!r} has unsupported bound(s) {sorted(extra)}")
    rng = DateRange(
        gte=validate.optional_iso_date(value.get("gte"), field=f"filter {key}.gte"),
        lte=validate.optional_iso_date(value.get("lte"), field=f"filter {key}.lte"))
    if rng.gte is None and rng.lte is None:
        raise validate.ValidationError(f"filter {key!r} has no bounds")
    if rng.gte is not None and rng.lte is not None and rng.gte > rng.lte:
        raise validate.ValidationError(
            f"filter {key!r} range is inverted: {rng.gte} > {rng.lte}")
    return rng


@dataclass
class VerdictRow:
    product: str
    trigger: str
    required_change: str
    real_deadline: str
    confidence: float
    citations: list[str] = field(default_factory=list)
