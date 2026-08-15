"""The compiled graph and the hand-written DynamoDB checkpointer.

The end-to-end test here is the one that would have caught an integration
mistake the per-node tests cannot: nodes that each work in isolation but hand
each other the wrong keys, or a fan-in that runs before both branches finish.
It runs the real compiled LangGraph with every node's seam stubbed, so it
exercises the wiring and nothing else.
"""
import pytest
from conftest import FIXTURES  # noqa: F401  (path setup)

from graph import amendment_graph as ag, nodes
from graph.checkpoint import CheckpointTooLargeError, DynamoDBSaver
from graph.graph import build_graph
from shared.models import Chunk


# --------------------------------------------------------------- topology
def test_the_graph_has_the_nodes_spec_03_names():
    g = build_graph().get_graph()
    assert {n for n in g.nodes} - {"__start__", "__end__"} == {
        "supervisor", "retrieval_agent", "timeline_agent", "crossref_agent",
        "applicability", "verdict", "hitl_gate"}


def test_timeline_and_crossref_fan_out_and_fan_in():
    """The parallel pair, and the join. Both branches must leave
    `retrieval_agent` and both must land on `applicability` — if either edge is
    missing, one branch's output silently never reaches the verdict."""
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("retrieval_agent", "timeline_agent") in edges
    assert ("retrieval_agent", "crossref_agent") in edges
    assert ("timeline_agent", "applicability") in edges
    assert ("crossref_agent", "applicability") in edges


def test_retrieval_precedes_the_parallel_pair():
    """Pins the recorded deviation from SPEC/03's diagram (see graph.py). If
    the true parallel fan-out is ever adopted, this test is the thing that
    should fail and force the spec and the wiring to be changed together."""
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("supervisor", "retrieval_agent") in edges
    assert ("supervisor", "timeline_agent") not in edges
    assert ("supervisor", "crossref_agent") not in edges


# ------------------------------------------------------------- end to end
@pytest.fixture
def stubbed(monkeypatch):
    """Every seam stubbed; the wiring left real."""
    chunk = Chunk(chunk_id="2025-00830#0000", text="Removal of 21 CFR 74.303.",
                  citation_path="21 CFR 74.303", doc_type="order",
                  fr_doc_number="2025-00830", cfr_title="21", cfr_part="74",
                  pub_date=None, effective_date=None, compliance_date=None)
    timeline = ag.DocTimeline(
        doc_number="2025-00830", citation="90 FR 4628", pub_date="2025-01-16",
        effective_dates=({"date": "2027-01-15", "applies_to": "food"},))

    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": {"products": ["frosting"], "claims": []},
        "intent": "timeline", "profile_sufficient": True})
    monkeypatch.setattr(nodes, "retrieval_agent", lambda s: {"retrieved": [chunk]})
    # Real fact-flattening over a stub timeline: the wiring test should carry
    # a realistic payload across the fan-in, not an empty list that would pass
    # even if the branch returned nothing.
    monkeypatch.setattr(nodes, "timeline_agent",
                        lambda s: {"timeline_facts": nodes._facts_for(timeline)})
    monkeypatch.setattr(nodes, "crossref_agent", lambda s: {"crossrefs": []})
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "Stop by January 15, 2027 (90 FR 4628).",
        "verdict_rows": [], "citations": ["90 FR 4628"],
        "confidence": 0.9,
        "dropped_citations": [], "status": "ok"})
    return chunk


def test_a_confident_run_reaches_the_end_with_an_answer_and_citations(stubbed):
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["status"] == "ok"
    assert state["citations"] == ["90 FR 4628"]
    assert "January 15, 2027" in state["answer"]


def test_both_parallel_branches_land_before_the_verdict(stubbed):
    """The fan-in. `timeline_facts` is produced by one branch and `crossrefs`
    by the other; both must be present in the final state, which they can only
    be if `applicability` waited for both."""
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["timeline_facts"]
    assert state["crossrefs"] == []
    assert any(f["kind"] == "operative_deadline" for f in state["timeline_facts"])


def test_a_low_confidence_run_ends_pending_review(monkeypatch, stubbed):
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "unsure", "verdict_rows": [], "citations": [],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["status"] == "pending_review"
    assert "0.30" in state["review_reason"]


def test_an_underspecified_run_ends_needs_input(monkeypatch, stubbed):
    """SPEC/03's HITL demonstration, minus the resume half. q10's shape."""
    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": {}, "intent": "other", "profile_sufficient": False})
    state = build_graph().invoke({"query": "Are we affected?"})
    assert state["status"] == "needs_input"


# ------------------------------------------------------------ checkpointer
class _FakeTable:
    """DynamoDB stand-in supporting the three shapes the saver issues."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        hit = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(hit)} if hit else {}

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)

    def query(self, KeyConditionExpression=None, ProjectionExpression=None,
              ScanIndexForward=True, Limit=None):
        values = getattr(KeyConditionExpression, "_values", ())
        if len(values) == 2 and hasattr(values[0], "_values"):
            pk, prefix = values[0]._values[1], values[1]._values[1]
        else:                                   # bare pk equality
            pk, prefix = values[1], ""
        rows = [dict(v) for (p, s), v in self.items.items()
                if p == pk and s.startswith(prefix)]
        rows.sort(key=lambda i: i["sk"], reverse=not ScanIndexForward)
        return {"Items": rows[:Limit] if Limit else rows}

    def batch_writer(self):
        return _FakeBatch(self)


class _FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def put_item(self, Item):
        self.table.put_item(Item)

    def delete_item(self, Key):
        self.table.delete_item(Key)


def _config(thread="t1", ns="", checkpoint_id=None):
    cfg = {"thread_id": thread, "checkpoint_ns": ns}
    if checkpoint_id:
        cfg["checkpoint_id"] = checkpoint_id
    return {"configurable": cfg}


def _checkpoint(cid, **channels):
    return {"v": 1, "id": cid, "ts": "2026-08-12T00:00:00+00:00",
            "channel_values": channels or {"query": "hello"},
            "channel_versions": {}, "versions_seen": {}}


def test_a_checkpoint_round_trips_through_the_serializer():
    """The whole reason this file is hand-written: a checkpoint that fails to
    round-trip looks exactly like a run that had nothing to resume."""
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1", query="When?"), {"step": 1}, {})

    tup = saver.get_tuple(_config())
    assert tup is not None
    assert tup.checkpoint["id"] == "ckpt-1"
    assert tup.checkpoint["channel_values"]["query"] == "When?"
    assert tup.metadata["step"] == 1


def test_the_latest_checkpoint_wins_when_no_id_is_given():
    """Resume takes the newest superstep. LangGraph's ids are UUIDv6, so the
    sort key is time-ordered and a descending query is a recency query."""
    saver = DynamoDBSaver(table=_FakeTable())
    for cid in ("ckpt-1", "ckpt-2", "ckpt-3"):
        saver.put(_config(), _checkpoint(cid), {"step": 1}, {})
    assert saver.get_tuple(_config()).checkpoint["id"] == "ckpt-3"


def test_a_specific_checkpoint_can_be_fetched_by_id():
    saver = DynamoDBSaver(table=_FakeTable())
    for cid in ("ckpt-1", "ckpt-2"):
        saver.put(_config(), _checkpoint(cid), {"step": 1}, {})
    tup = saver.get_tuple(_config(checkpoint_id="ckpt-1"))
    assert tup.checkpoint["id"] == "ckpt-1"


def test_parent_config_is_carried_so_a_resume_can_walk_back():
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1"), {"step": 1}, {})
    saver.put(_config(checkpoint_id="ckpt-1"), _checkpoint("ckpt-2"), {"step": 2}, {})

    tup = saver.get_tuple(_config(checkpoint_id="ckpt-2"))
    assert tup.parent_config["configurable"]["checkpoint_id"] == "ckpt-1"


def test_pending_writes_replay_in_the_order_they_were_written():
    """Zero-padding in the sort key is what makes this true — unpadded, write
    10 sorts before write 2 and the channels replay out of order."""
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1"), {"step": 1}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"),
                     [(f"channel{i}", i) for i in range(12)], "task-a")

    writes = saver.get_tuple(_config(checkpoint_id="ckpt-1")).pending_writes
    assert [w[1] for w in writes] == [f"channel{i}" for i in range(12)]
    assert [w[2] for w in writes] == list(range(12))
    assert {w[0] for w in writes} == {"task-a"}


def test_threads_do_not_see_each_other():
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(thread="t1"), _checkpoint("ckpt-1", query="a"), {}, {})
    saver.put(_config(thread="t2"), _checkpoint("ckpt-2", query="b"), {}, {})
    assert saver.get_tuple(_config(thread="t1")).checkpoint["channel_values"]["query"] == "a"
    assert saver.get_tuple(_config(thread="t2")).checkpoint["channel_values"]["query"] == "b"


def test_an_unknown_thread_returns_none_rather_than_raising():
    assert DynamoDBSaver(table=_FakeTable()).get_tuple(_config()) is None


def test_a_missing_thread_id_is_an_error_not_a_default():
    """A checkpoint written under a default thread is a checkpoint no resume
    will ever find."""
    with pytest.raises(ValueError, match="thread_id"):
        DynamoDBSaver(table=_FakeTable()).get_tuple({"configurable": {}})


def test_an_oversized_checkpoint_raises_with_the_fix_named():
    """DynamoDB's 400KB item limit, surfaced as our error rather than a generic
    botocore ValidationException — the fix is to spill to S3 and the message
    has to say so."""
    saver = DynamoDBSaver(table=_FakeTable())
    with pytest.raises(CheckpointTooLargeError, match="spill the large channel to S3"):
        saver.put(_config(), _checkpoint("big", blob="x" * 500_000), {}, {})


def test_delete_thread_removes_checkpoints_and_writes():
    table = _FakeTable()
    saver = DynamoDBSaver(table=table)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"), [("c", 1)], "task-a")
    assert table.items

    saver.delete_thread("t1")
    assert table.items == {}


def test_a_ttl_is_set_on_every_item():
    """The review window. A paused run whose checkpoint expires cannot be
    resumed, so the value is a product decision — but its absence would be a
    table that grows without bound."""
    table = _FakeTable()
    saver = DynamoDBSaver(table=table, ttl_days=7)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"), [("c", 1)], "task-a")
    assert all("ttl" in item for item in table.items.values())


def test_the_graph_compiles_with_the_saver_attached():
    """The two halves have to fit: SPEC/03's resume criterion needs the graph
    compiled WITH a checkpointer, and nothing else in the suite proves they
    are compatible."""
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    assert app.checkpointer is not None
