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
from graph import nodes
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

    builder.add_node("supervisor", nodes.supervisor)
    builder.add_node("retrieval_agent", nodes.retrieval_agent)
    builder.add_node("timeline_agent", nodes.timeline_agent)
    builder.add_node("crossref_agent", nodes.crossref_agent)
    builder.add_node("applicability", nodes.applicability)
    builder.add_node("verdict", nodes.verdict)
    builder.add_node("hitl_gate", nodes.hitl_gate)

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
    builder.add_edge("hitl_gate", END)

    return builder.compile(checkpointer=checkpointer)
