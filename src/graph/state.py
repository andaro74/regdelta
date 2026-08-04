"""LangGraph state (SPEC/03)."""
from typing import TypedDict

from shared.models import Chunk, VerdictRow


class RegDeltaState(TypedDict, total=False):
    query: str
    company_profile: dict
    retrieved: list[Chunk]
    timeline_facts: list[dict]
    crossrefs: list[dict]
    verdict_rows: list[VerdictRow]
    confidence: float
    citations: list[str]
    status: str  # ok | pending_review | needs_input | degraded
