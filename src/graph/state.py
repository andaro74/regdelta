"""LangGraph state (SPEC/03).

`total=False` throughout: nodes return PARTIAL updates and LangGraph merges
them, so every key is absent until some node sets it. Reading with `.get()` and
a default is the contract, not defensive style.

Keys are disjoint across the parallel branches on purpose — `timeline_agent`
owns `timeline_facts`, `crossref_agent` owns `crossrefs`, and neither writes
what the other reads. That is what lets them fan out without a reducer: two
nodes returning the same key in one superstep is a conflict LangGraph cannot
settle for us, and settling it with "last writer wins" would make the answer
depend on scheduling.
"""
from typing import TypedDict

from shared.models import Chunk, VerdictRow


class RegDeltaState(TypedDict, total=False):
    # --- request
    query: str
    company_profile: dict

    # --- supervisor
    intent: str                  # timeline | applicability | lookup | other
    profile_sufficient: bool     # false -> hitl_gate ends with needs_input

    # --- parallel branches
    retrieved: list[Chunk]
    timeline_facts: list[dict]   # from the amendment graph, never from prose
    crossrefs: list[dict]

    # --- synthesis
    applicability: dict
    answer: str
    verdict_rows: list[VerdictRow]
    confidence: float
    citations: list[str]
    #: Citations the model claimed that the sources did not support. Recorded
    #: rather than discarded silently: a model reaching for uncited authority
    #: is a finding about the answer, and q03 is the reason it is worth seeing.
    dropped_citations: list[str]

    # --- gate
    status: str                  # ok | pending_review | needs_input | degraded
    review_reason: str
