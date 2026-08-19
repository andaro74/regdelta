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
    #: Which tier ACTUALLY answered — "aoss" | "s3vectors" — straight from
    #: `router.Resolution`, never from `active_tier()`. The difference is the
    #: whole point: `active_tier()` reads SSM and reports what the system is
    #: CONFIGURED to, while the router falls back to S3 Vectors on any AOSS
    #: error. Reporting the former is how two Tier A runs get scored as
    #: two-tier coverage, which is the failure router.py's own docstring names.
    #: Absent on a run that never reached retrieval (rejected, needs_input).
    retrieval_tier: str
    #: Why the hot tier did not answer, when it was configured and did not.
    #: None on a clean run; a silent fallback is the thing being made loud.
    retrieval_fallback: str | None
    timeline_facts: list[dict]   # from the amendment graph, never from prose
    #: True when documents WERE in play and the graph produced no dated fact for
    #: any of them. `timeline_facts == []` cannot express this: it is also what
    #: "no documents in play" looks like, and the two need opposite treatment.
    #: Set by `timeline_agent`, read by `_needs_review`.
    timeline_degraded: bool
    crossrefs: list[dict]
    #: The cross-referenced sections as TEXT, ready to fence into the verdict
    #: prompt. Separate from `crossrefs` because that field is the audit trail —
    #: which citation resolved, to what, or why it did not — and this is the
    #: payload. Until 2026-08-16 only the audit trail existed and nothing read
    #: it, so the node resolved references and threw the answer away.
    crossref_chunks: list

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
    #: ok | pending_review | needs_input | rejected | resumed | degraded.
    #: `resumed` is transient — it is what the conditional edge out of
    #: `hitl_gate` reads to send the run back through retrieval, and it is
    #: replaced by a terminal status on the second pass.
    status: str
    review_reason: str
    #: How many times this run has come back through the gate. Bounds the
    #: resume cycle: one resume is the demonstrated flow, and a second would
    #: mean the reviewer's input did not resolve the reason for pausing.
    hitl_passes: int
