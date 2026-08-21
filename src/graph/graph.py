"""Graph wiring (SPEC/03).

    supervisor -> retrieval_agent -> {timeline_agent, crossref_agent}
               -> applicability -> verdict -> hitl_gate -> END

## One deviation from SPEC/03, recorded rather than made silently

SPEC/03 draws the fan-out as `supervisor -> parallel {retrieval, timeline,
crossref}`. Here retrieval runs FIRST and the other two fan out from it.

The reason is a dependency the diagram does not show: both `timeline_agent` and
`crossref_agent` need to know which documents are in play, and at M03 the only
thing that knows is the retrieved page. Running them beside retrieval would
mean each doing its own document selection — a second and third retrieval call
per question, with three nodes free to disagree about which documents the
question is about. The parallelism that matters is still there: the two nodes
that can run concurrently do, and they are the slow pair (a registry scan and a
GSI lookup), while retrieval was never going to overlap with them usefully.

**This is a PM-seat item, not a settled decision.** SPEC/03's Nodes section is
the spec of record and it says parallel; this file is engineering's account of
why that shape did not survive contact. If the true parallel fan-out is wanted,
it needs a document-selection step in `supervisor` that does not exist yet —
which is a spec change, and `pm-spec-reviewer` owns it. Nothing in SPEC/03's
"Done when" turns on the topology, so this does not block the milestone; it
should not be allowed to quietly become the spec either.
"""
from graph import instrument, nodes
from graph.state import RegDeltaState


def build_graph(checkpointer=None):
    """Compile the agent graph.

    `checkpointer` is optional so the graph can be built and run in a test or a
    local shim with no DynamoDB. It is required for the resume half of SPEC/03's
    HITL criterion — without it a `pending_review` run has nowhere to pause and
    `/resume/{id}` has nothing to continue from. See graph/checkpoint.py.
    """
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(RegDeltaState)

    # EVERY NODE IS WRAPPED (SPEC/06 Observability: "span per graph node").
    # Wrapped HERE rather than by decorating the functions in nodes.py, for
    # three reasons. The seam stays out of the answer path — nodes.py's own
    # docstring says its injectable seams "are not features - nothing in the
    # answer path branches on them", and an emitter baked into each node would
    # be a fourth thing every unit test has to tolerate. The wrapper sees each
    # node's RETURN VALUE, which is strictly more than the merged state: it
    # observes a key before LangGraph can drop an undeclared one, which is how
    # `stop_reason` was lost. And `instrument.observed` keeps the original on
    # `__wrapped__`, so the load driver and the tests can still call the real
    # function without emitting anything.

    builder.add_node("supervisor", instrument.observed("supervisor", nodes.supervisor))
    builder.add_node("retrieval_agent", instrument.observed("retrieval_agent", nodes.retrieval_agent))
    builder.add_node("timeline_agent", instrument.observed("timeline_agent", nodes.timeline_agent))
    builder.add_node("crossref_agent", instrument.observed("crossref_agent", nodes.crossref_agent))
    builder.add_node("applicability", instrument.observed("applicability", nodes.applicability))
    builder.add_node("verdict", instrument.observed("verdict", nodes.verdict))
    builder.add_node("hitl_gate", instrument.observed("hitl_gate", nodes.hitl_gate))

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "retrieval_agent")

    # Fan out, then fan in. LangGraph runs both branches in one superstep and
    # only enters `applicability` once BOTH have returned — the join is the
    # pair of edges below, not an explicit barrier node.
    builder.add_edge("retrieval_agent", "timeline_agent")
    builder.add_edge("retrieval_agent", "crossref_agent")
    builder.add_edge("timeline_agent", "applicability")
    builder.add_edge("crossref_agent", "applicability")

    builder.add_edge("applicability", "verdict")
    builder.add_edge("verdict", "hitl_gate")

    # The resume path. `hitl_gate` pauses on `interrupt()`; when a reviewer
    # supplies what was missing it returns status="resumed", and the run goes
    # back through retrieval rather than ending — because the thing that was
    # missing (a company profile) changes what should be retrieved and what the
    # verdict says, so releasing the draft answer unchanged would be answering
    # the question the reviewer had already identified as unanswerable.
    #
    # Every other outcome ends. `hitl_gate` caps the number of passes, so this
    # cycle cannot spin: one resume is the demonstrated flow, and a second
    # would mean the supplied input did not resolve the reason for pausing.
    builder.add_conditional_edges("hitl_gate", _after_hitl,
                                  {"retrieval_agent": "retrieval_agent", END: END})

    return builder.compile(checkpointer=checkpointer)


def _after_hitl(state: RegDeltaState) -> str:
    from langgraph.graph import END

    if state.get("status") == "resumed":
        return "retrieval_agent"
    return END
