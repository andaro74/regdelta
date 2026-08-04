"""Graph wiring (SPEC/03). TODO: StateGraph(RegDeltaState); supervisor ->
parallel {retrieval_agent, timeline_agent, crossref_agent} -> applicability
-> verdict -> hitl_gate; DynamoDB checkpointer (STATE_TABLE) so
pending_review runs resume exactly where they paused."""


def build_graph():
    raise NotImplementedError("SPEC/03")
