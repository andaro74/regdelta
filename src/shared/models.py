"""Shared data models. TODO(all specs): extend as milestones need."""
from dataclasses import dataclass, field


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
    embedding: list[float] | None = None
    score: float = 0.0


@dataclass
class Filters:
    cfr_title: str | None = None
    cfr_part: str | None = None
    doc_type: str | None = None
    effective_after: str | None = None
    compliance_before: str | None = None


@dataclass
class VerdictRow:
    product: str
    trigger: str
    required_change: str
    real_deadline: str
    confidence: float
    citations: list[str] = field(default_factory=list)
